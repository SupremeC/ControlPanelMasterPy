"""ControlPanel_Class"""

import datetime
import logging
from queue import Empty, Full, Queue
import random
import threading
import time
from typing import List
from Pyro5.api import expose
from .wled import WLED  # WledStateSnapshot, SegmentState
from daemon.audio_ctrl import AudioCtrl, SysAudioEvent as aevent, EffectType
from .pyro_daemon import PyroDaemon
from .ctrls import CtrlNotFoundException, HwCtrls, LEDCtrl
from .packet import HWEvent, Packet, BlinkTarget  # noqa
from daemon.packet_serial import PacketSerial
from daemon.openaiWrapper import OpenAiWrapper
from daemon.gCalender import Calender

logger = logging.getLogger("daemon.ctrlPanel")
# The serial buffer of Arduino is increased to 256 bytes (if it works)
# it was changed in platformio config file in VSCode
# COBS adds an additional stop byte as well as '0' escaping, so lets assume each packet is 10 bytes.
# 256 / 10bytes => 25 packets until buffer is full.
# average arduino loop duration is ~25ms. In theory, that allows us
# to send (1000/25ms)*25packets = 1000 packets per second.
MAX_PACKETS_IN_SEND_QUEUE = 100
SEND_HELLO_INTERVALL = 120  # seconds


class ControlPanel:
    """Master class (besides controlPanelDaemon of course)"""

    pyrodaemon: PyroDaemon
    demo_on: bool = False

    def __init__(self):
        self._last_sent_hello: datetime.datetime = None
        self._last_received_hello: datetime.datetime = None
        self._ctrls: HwCtrls = HwCtrls()
        self._packet_sendqueue: Queue = Queue(MAX_PACKETS_IN_SEND_QUEUE)
        self._packet_receivedqueue: Queue = Queue()
        self._pserial: PacketSerial = PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue
        )
        self.demo_on: bool = False
        self.alarm_on: bool = False
        self.cal = Calender(self.on_cal_alarm, self.on_cal_sunrise)
        self.ai = OpenAiWrapper()
        self._audioctrl: AudioCtrl = AudioCtrl(self.speakerLeds)
        self.wled_instance = WLED()
        logger.info("ControlPanel init. Using serial Port=%s", self._pserial.port)
        logger.info(self.wled_instance)

    def start(self):
        """Opens serial connection and start Read and Write worker threads"""
        try:
            self.reset()
            self._pserial.open_connection()
            logger.info("StartingPyro daemon...")
            self.pyrodaemon = PyroDaemon(self)
            self.pyrodaemon.daemon = True
            self.pyrodaemon.start()  # do not use 'Run()'
            logger.debug("waiting for Pyro...")
            self.pyrodaemon.started.wait()
            self.pyrodaemon.write_uri_file()
            logger.info("Pyro daemon started")
        except Exception as e:
            logger.error(e)

    def stop(self):
        """Closes serial connection and does general cleanup"""
        try:
            logger.info("ControlPanel stopping...")
            self.demo_on = False
            self.reset()
            self._pserial.close_connection()
            self.pyrodaemon.stop()
            self.wled_instance.close_serial_conn()
        except Exception as e:
            logger.error(e)

    def process(self) -> None:
        """Call this method regularly to process packets"""
        try:
            self._process_packets()
            if self.time_to_send_hello():
                self._pserial.send_hello()
                self._last_sent_hello = datetime.datetime.now()
        except Exception as e:
            logger.exception(e)

    def _process_packets(self) -> None:
        try:
            while self._packet_receivedqueue.qsize() > 0:
                self.__act(self._packet_receivedqueue.get(block=True, timeout=2))
                self._packet_receivedqueue.task_done()
        except Empty:
            pass

    def __act(self, packet: Packet) -> None:
        try:
            if packet.hw_event == HWEvent.BOOTMEGA:
                logger.info("Received BOOTMEGA packet. Mega was (re)booted")
                self.reset()
            elif packet.hw_event == HWEvent.HELLO:
                self._last_received_hello = datetime.datetime.now()
            elif packet.hw_event == HWEvent.RESET:
                logger.info("Received RESET packet. starting reset routine")
                self.reset()
            elif packet.hw_event == HWEvent.STATUS:
                # Status packet. Target == Switch pin.
                self._switch_status_changed(packet, no_action=True)
            elif packet.hw_event == HWEvent.SWITCH:
                # A switch has changed status. React
                self._switch_status_changed(packet)
            elif packet.hw_event == HWEvent.UNDEFINED:
                logger.warning("Received undefined package: %s", packet)
        except Full as err_full:
            logger.error(err_full)
        except Exception as error:
            logger.error(error)

    def _switch_status_changed(self, packet: Packet, no_action: bool = False) -> Packet:
        """Handles button logic"""
        try:
            p_tosend = []
            mastersw = self._ctrls.get_ctrl_by_name("masterSw")
            inputsw = self._ctrls.get_ctrl_by_name("InputsSw")
            soundsw = self._ctrls.get_ctrl_by_name("SoundSw")

            if packet.target == 12:  # MainSwitch
                mastersw.state = bool(packet.val)
                if mastersw.state:
                    self._audioctrl.sysaudio_play(aevent.SYSTEM_ON)
                else:
                    p_tosend.extend(self._ctrls.set_all_leds(False))
                    self.wled_instance.set_wled_state(False)
                    self._audioctrl.sysaudio_play(aevent.SYSTEM_OFF)
                    self.send_packets(p_tosend)
                    return
            if packet.target == inputsw.pin:  # Inputs on / off
                p_tosend.extend(inputsw.set_state(bool(packet.val)))
            if packet.target == 14:  # Backlight
                self.cp_bg_lights(packet)
            if packet.target == soundsw.pin:  # Sound on / off
                p_tosend.extend(soundsw.set_state(bool(packet.val)))
                self._audioctrl.enable_sound(bool(packet.val))

            self.send_packets(p_tosend)
            p_tosend.clear()

            if self.demo_on and packet.target not in range(54, 63):  # analog ctrls
                self.demo_on = False
                return
            if self.alarm_on and packet.target not in range(54, 63):  # analog ctrls
                self.alarm_on = False
                self._audioctrl.stop_alarm()
                self.ai_talk
                return

            if not mastersw.state or not inputsw.state:
                return

            if packet.target >= 2 and packet.target <= 11 and packet.val == 1:
                self.send_packets(
                    self._ctrls.get_slavectrl(packet.target).leds[0].blink()
                )
                self._audioctrl.recsaved_play(packet.target)
            if packet.target >= 2 and packet.target <= 11 and packet.val == 100:
                self._audioctrl.save_rec_to_hwswitch(packet.target)
                self.send_packets(
                    self._ctrls.get_slavectrl(packet.target).leds[0].blink(True)
                )
                self._audioctrl.sysaudio_play(aevent.REC_SAVED)
                return
            if packet.target >= 2 and packet.target <= 11 and packet.val == 200:
                # Restore Audio OR Demo
                if packet.target == 5:
                    self.demo_on = not self.demo_on
                    if self.demo_on:
                        self._audioctrl.sysaudio_play(aevent.DEMOMODE)
                        demo_thread = threading.Thread(
                            target=self.wrapped_demo_run,
                            kwargs=None,
                        )
                        demo_thread.start()
                else:
                    self._audioctrl.restore_original_audio(packet.target)
                return
            if packet.target in [17, 18, 19, 22, 23, 24, 25, 26]:  # Effect btns
                if self._audioctrl.current_filepath is None:
                    self._audioctrl.sysaudio_play(aevent.FAILED)
                else:
                    self.apply_soundeffect(packet)
                    self.send_packets(
                        Packet(HWEvent.BLINK3ENDHIGH, BlinkTarget.AUDIO_PRESETBTNS, 2)
                    )
                return
            if packet.target == 27 and packet.val:
                self._audioctrl.sysaudio_play(aevent.REC_STARTED, True)
                self._audioctrl.start_recording()
                return
            if packet.target == 27 and packet.val == 0:
                self._audioctrl.stop_recording()
                self._audioctrl.sysaudio_play(aevent.REC_STOPPED)
                ai_ctrl = self._ctrls.get_slavectrl(69)
                self.send_packets(ai_ctrl.leds[0].blink(True))
                self.send_packets(
                    Packet(HWEvent.BLINK3ENDHIGH, BlinkTarget.EFFECT_BTNS, 2)
                )
                self.send_packets(
                    Packet(HWEvent.BLINK3ENDHIGH, BlinkTarget.AUDIO_PRESETBTNS, 2)
                )
                self._audioctrl._play_tmp_rec()
                return
            if packet.target >= 66 and packet.target <= 69:
                self._set_relays(packet, is_safetyctrl=False)
                return
            if packet.target >= 32 and packet.target <= 37:
                self.ledstrip_control(packet)
                return
            if packet.target >= 38 and packet.target <= 41:
                self._set_relays(packet, is_safetyctrl=True)
                return
            if packet.target >= 52 and packet.target <= 59:  # ledtrip_analog
                # analog controls (A0 == 52, A1=53, ...)
                self.ledstrip_control(packet)
                return
            if packet.target == 62:
                self.audio_volume(
                    self.map_value(val=packet.val, out_min=0, out_max=100)
                )
                return
        except Exception:
            logger.error(packet)
            logger.exception("exception in function switch_status_changed()")
            self._audioctrl.sysaudio_play(aevent.FAILED)
        finally:
            if not no_action:
                self.send_packets(p_tosend)

    def apply_soundeffect(self, packet: Packet):
        btn = self._ctrls.get_ctrl(packet.target)
        match packet.target:
            case 17:
                self._audioctrl.apply_effect(EffectType.BITCRUSH, None)
            case 18:
                self._audioctrl.apply_effect(EffectType.PHASER, None)
            case 19:
                self._audioctrl.apply_effect(EffectType.REVERSE, None)
            case 22:
                self._audioctrl.apply_effect(EffectType.TIMESTRETCH, None)
            case 23:
                self._audioctrl.apply_effect(EffectType.PITCHLOWER, None)
            case 24:
                self._audioctrl.apply_effect(EffectType.PITCHHIGHER, None)
            case 25:
                self._audioctrl.apply_effect(EffectType.TIMECOMPRESS, None)
            case 26:
                self._audioctrl.apply_effect(EffectType.REVERB, None)
        self.send_packets(btn.leds[0].blink())

    def wrapped_demo_run(self) -> None:
        self._led_ctrls = self._ctrls._get_all_leds()
        while self.demo_on:
            rnd_item = random.choice(self._led_ctrls)
            self.send_packets(rnd_item.set_led_state(not rnd_item.state))
            time.sleep(0.1)

    def cp_bg_lights(self, packet: Packet) -> None:
        """background light ON/OFF"""
        if packet.target == 14:
            ctrl = self._ctrls.get_ctrl_by_name("BacklightSw")
            relay = self._ctrls.get_ctrl_by_name("BacklightRelay")
            if packet.val:
                self._audioctrl.sysaudio_play(aevent.BG_LIGHT_ON)
            else:
                self._audioctrl.sysaudio_play(aevent.BG_LIGHT_OFF)

            relay.set_state(bool(packet.val))
            send = []
            send = ctrl.set_state(packet.val)
            send.append(Packet(HWEvent.RELAY, relay.pin, 1 if packet.val == 0 else 0))
            if ctrl.quick_state_change:
                logger.info(
                    "All non-indicator LEDs ON"
                    if relay.state
                    else "All non-indicator LEDs OFF"
                )
                send.extend(self._ctrls.set_all_nonindicatorleds(relay.state))
            self.send_packets(send)

    def audio_volume(self, new_vol: int = None) -> None:
        """Clamps volume to 0-100, and sets master volume"""
        vol = LEDCtrl.clamp(new_vol, 0, 100)
        return self._audioctrl.set_volume(vol)

    def _set_relays(self, packet: Packet, is_safetyctrl: bool = False):
        try:
            if is_safetyctrl:
                flipsw = self._ctrls.get_ctrl(packet.target)
                new_state = bool(packet.val)
                if new_state:
                    self.send_packets(flipsw.slaves[0].leds[0].blink(True))
                    pass
                else:
                    if packet.target == 38:  # Bed lamp
                        self.send_packets(flipsw.slaves[0].set_state(True))
                        time.sleep(0.1)
                        self.send_packets(flipsw.slaves[0].set_state(False))
                    else:
                        # turn off slave relay
                        self.send_packets(flipsw.slaves[0].set_state(False))
                self._audioctrl.sysaudio_play(aevent.FLIP_SWITCH)
                flipsw.set_state(new_state)
            else:
                btn = self._ctrls.get_slavectrl(packet.target)
                if btn.parent.state:
                    if btn.pin == 69 and self._audioctrl.current_filepath is None:
                        self.ai_talk(btn, False)
                    elif btn.pin == 69 and self._audioctrl.current_filepath is not None:
                        self.ai_talk(btn, True)
                    else:
                        self._audioctrl.sysaudio_play(aevent.BTN_CLICKED)
                        new_state = packet.val if packet.target == 67 else not btn.state
                        self.send_packets(btn.set_state(new_state))

        except Full:
            logger.exception("Sendqueue was full. Packet(s) could not be sent")
            self._audioctrl.sysaudio_play(aevent.FAILED)
        except CtrlNotFoundException:
            logger.exception("Ctrl not found")
            raise

    def ai_talk(self, p_btn, p_audio_call: bool) -> None:
        ai_thread = threading.Thread(
            target=self.wrapped_ai_talk,
            kwargs=dict(btn=p_btn, audio_call=p_audio_call),
        )
        ai_thread.start()

    def wrapped_ai_talk(self, btn, audio_call: bool) -> None:
        try:
            if audio_call:
                self.send_packets(btn.leds[0].blink(forever=True))
                audio_str = self._audioctrl._read_wav_file(
                    self._audioctrl.current_filepath
                )
                self.ai._send_audio_chat(audio_str)
                self._audioctrl.play_bytes(self.ai.audio)
                self.send_packets(btn.leds[0].blink_stop())
            else:
                self.send_packets(btn.leds[0].blink(forever=True))
                self.ai.upcomingEvents(self.cal.get_todays_events())
                self._audioctrl.play_bytes(self.ai.audio)
                self.send_packets(btn.leds[0].blink_stop())
        except Exception as e:
            self.sysaudio_play(aevent.FAILED)
            logger.error(e)

    def speakerLeds(self, on: bool) -> None:
        if on:
            self.send_packets(Packet(HWEvent.BLINKFOREVER, BlinkTarget.SPEAKER_LEDS, 1))
        else:
            self.send_packets(Packet(HWEvent.BLINKFOREVER, BlinkTarget.SPEAKER_LEDS, 0))

    def on_cal_alarm(self) -> None:
        self.alarm_on = True
        self._audioctrl.sysaudio_play(aevent.ALARM, False, 20)
        # sleep 5
        # Play ai morning greeting?
        pass

    def on_cal_sunrise(self, duration: int) -> None:
        self.wled_instance.do_sunrise(duration * 60)

    def ledstrip_control(self, packet: Packet):
        """Sends commands (translated from packet) to LED-strip"""
        if packet.target == 35:  # on/off/reset
            segmentId = 1
            if packet.val == 100:
                self.wled_instance._change_effect(0, segmentId)
                return
            segment_state = (
                self.wled_instance.read_state().seg_state[segmentId].seg_state
            )
            led_ctrl = self._ctrls.get_ctrl(packet.target)
            self.send_packets(led_ctrl.set_state(not segment_state))
            # self.send_packets(led_ctrl.set_state(True))
            self.wled_instance.toggle_wled_state(segmentId)

        if packet.target == 36:
            self.wled_instance.previous_effect(1)
        if packet.target == 37:
            self.wled_instance.next_effect(1)
        if packet.target == 55:
            self.wled_instance.set_brightness(self.map_value(packet.val), 1)
        if packet.target >= 54 and packet.target <= 57:
            self._ctrls.get_ctrl(packet.target).set_state(self.map_value(packet.val))
            red_ctrl = self._ctrls.get_ctrl(54)
            green_ctrl = self._ctrls.get_ctrl(56)
            blue_ctrl = self._ctrls.get_ctrl(57)
            color = [red_ctrl.state, green_ctrl.state, blue_ctrl.state]
            self.wled_instance.set_color(color, 1)

    def map_value(self, val, in_min=0, in_max=1023, out_min=0, out_max=255):
        # Ensure value is within the input range
        val = max(in_min, min(val, in_max))
        # Map the value
        return (val - in_min) * (out_max - out_min) // (in_max - in_min) + out_min

    def send_packets(
        self, packets: List, block: bool = False, timeout: float = None
    ) -> None:
        """Puts the packet(s) into sendQueue.
        It will be picked up ASAP by packetSerial thread"""
        if not hasattr(packets, "__iter__"):
            packets = [packets]
        try:
            for p in packets:
                self._packet_sendqueue.put(p, block, timeout)
        except Full:
            logger.error("SendQueue was full. Packet(s) could not be sent")
            self._audioctrl.sysaudio_play(aevent.FAILED)

    def time_to_send_hello(self) -> bool:
        """Is it time to send hello yet?"""
        return (
            self._last_sent_hello is None
            or (datetime.datetime.now() - self._last_sent_hello).total_seconds()
            > SEND_HELLO_INTERVALL
        )

    def reset(self):
        """
        Resets internal HW ctrls status
        Clears outgoing queue
        Sends request-STATUS msg to Arduino to syncronize
        ctrls between the systems.
        """
        logger.debug("resetting 'controlPanel_class' instance")
        try:
            self._ctrls.reset()
            self.clear_packet_queue()
            # send RequestStatus packet to get ctrls status
            self._packet_sendqueue.put(
                Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1
            )
        except (Full, TimeoutError) as err:
            logger.error(err)
            self._audioctrl.sysaudio_play(aevent.FAILED)
        else:
            logger.debug("reset done")

    def set_panelstatus(self, state: bool):
        """Set MainMaster on/off

        if OFF: Send Packet to turn all LEDs off
        """
        self._mainMasterOn.state = state
        if not state:
            self.send_packets(self._ctrls.set_all_leds(False))

    def clear_packet_queue(self):
        """Clear outgoing Packet queue, duh!"""
        if self._packet_sendqueue.qsize() > 0:
            while not self._packet_sendqueue.empty():
                try:
                    self._packet_sendqueue.get(block=False)
                except Empty:
                    continue
                self._packet_sendqueue.task_done()
            logger.debug("SendQueue is now cleared.")
        else:
            logger.debug("SendQueue is empty. Good")

    # ==============================================
    # ========== PURO EXPOSED METHODS ==============
    # ==============================================

    @expose
    def say_hello(self) -> str:
        """Pyro exposed function"""
        return "Well hello there stranger! I'm ControlPanelDaemon"

    @expose
    def get_status(self) -> str:
        """Pyro exposed function"""
        status = {}
        status.update({"Read Queue": self._packet_receivedqueue.qsize()})
        status.update({"Send Queue": self._packet_sendqueue.qsize()})
        status.update(
            {
                "Last Sent Hello": (
                    "-"
                    if self._last_sent_hello is None
                    else self._last_sent_hello.isoformat()
                )
            }
        )
        status.update(
            {
                "Last Incoming Hello": (
                    "-"
                    if self._last_received_hello is None
                    else self._last_received_hello.isoformat()
                )
            }
        )
        status.update({"Volume": "TODO"})
        status.update(
            {
                "Main Switch": self._bool_to_onoffstr(
                    self._ctrls.get_ctrl_by_name("masterSw").state
                )
            }
        )
        status.update(
            {
                "Inputs Switch": self._bool_to_onoffstr(
                    self._ctrls.get_ctrl_by_name("InputsSw").state
                )
            }
        )
        status.update(
            {
                "Sound Switch": self._bool_to_onoffstr(
                    self._ctrls.get_ctrl_by_name("SoundSw").state
                )
            }
        )
        return status

    @expose
    def get_latest_rpackets(self) -> List[Packet]:
        """The last X RECEIVED packets"""
        return self._pserial.last_received

    @expose
    def get_latest_spackets(self) -> List[Packet]:
        """The last X SENT packets"""
        return self._pserial.last_sent

    @staticmethod
    def _bool_to_onoffstr(b: bool) -> str:
        return "ON" if b else "OFF"


if __name__ == "__main__":
    myCP = ControlPanel()
    myCP.start()
    pass
