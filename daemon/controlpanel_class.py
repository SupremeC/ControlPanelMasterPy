"""ControlPanel_Class"""


import datetime
import logging
from queue import Empty, Full, Queue
from typing import List
from Pyro5.api import expose

from daemon.audio_ctrl import AudioCtrl, SysAudioEvent as aevent
from .pyro_daemon import PyroDaemon
from .ctrls import CtrlNotFoundException, HwCtrls, LEDCtrl, LED_ON, LED_OFF
from .packet import HWEvent, Packet  # noqa
from .packet_serial import PacketSerial

logger = logging.getLogger("daemon.ctrlPanel")
# The buffer of Arduino is increased to 256 bytes (if it works)
# it was changed in platformio config file in VSCode
# 256 / 7bytes => 36 packets until buffer is full
MAX_PACKETS_IN_SEND_QUEUE = 36
SEND_HELLO_INTERVALL = 30  # seconds


class ControlPanel:
    """Master class (besides controlPanelDaemon of course)"""

    pyrodaemon: PyroDaemon

    def __init__(self):
        self._last_sent_hello: datetime.datetime = None
        self._last_received_hello: datetime.datetime = None
        self._ctrls: HwCtrls = HwCtrls()
        self._packet_sendqueue: Queue = Queue(MAX_PACKETS_IN_SEND_QUEUE)
        self._packet_receivedqueue: Queue = Queue()
        self._pserial: PacketSerial = PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue
        )
        self._audioCtrl: AudioCtrl = AudioCtrl()
        logger.info("ControlPanel init. Using serial Port=%s", self._pserial.port)

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
            self.reset()
            self._pserial.close_connection()
            self.pyrodaemon.stop()
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
                logger.warning("Recevied undefined package: %s", packet)
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
                if not mastersw.state:
                    p_tosend.extend(self._ctrls.set_all_leds(False))
                    self.send_packets(p_tosend)
                    return
            if packet.target == inputsw.pin:  # Inputs on / off
                p_tosend.extend(inputsw.set_state(bool(packet.val)))
            if packet.target == 14:  # Backlight
                p_tosend.extend(
                    self._ctrls.get_ctrl_by_name("BacklightSw").set_state(packet.val)
                )
                relayctrl = self._ctrls.get_ctrl_by_name("BacklightRelay")
                p_tosend.extend(relayctrl.set_state(bool(packet.val)))
            if packet.target == soundsw.pin:  # Sound on / off
                p_tosend.extend(soundsw.set_state(bool(packet.val)))
                self.audio_volume(new_vol=0)

            self.send_packets(p_tosend)
            p_tosend.clear()
            if not inputsw.state:
                return

            if packet.target >= 2 and packet.target <= 11 and packet.val == 1:
                self._audioCtrl.recsaved_play(packet.target)
            if packet.target >= 2 and packet.target <= 11 and packet.val == 100:
                self._audioCtrl.restore_original_audio(packet.target)
            if packet.target >= 17 and packet.target <= 26:  # pin 20,21 is excluded
                self._audioCtrl.apply_effect(packet, self)
            if packet.target == 27 and packet.val:
                self._audioCtrl.sysaudio_play(aevent.REC_STARTED)
                self._audioCtrl.start_recording()
            if packet.target == 27 and packet.val == 0:
                self._audioCtrl.sysaudio_play(aevent.REC_STOPPED)
                self._audioCtrl.stop_recording()
            if packet.target >= 28 and packet.target <= 31:
                self._set_relays(packet)
            if packet.target >= 32 and packet.target <= 37:
                self.ledstrip_control(packet)
            if packet.target >= 38 and packet.target <= 41:  # uttag, vägglampa
                self._set_relays(packet, safetyctrl=True)
            if packet.target >= 52 and packet.target <= 59:  # lestrip_analog
                # analog controls (A0 == 52, A1=53, ...)
                self.ledstrip_control(packet)
            if packet.target == 60:
                self.audio_volume(packet=packet)
        except Exception:
            logger.error(packet)
            logger.exception("exception in function switch_status_changed()")
        finally:
            if not no_action:
                self.send_packets(p_tosend)

    def audio_volume(self, packet: Packet = None, new_vol: int = None) -> None:
        """Clamps volume to 0-100, and sets master volume"""
        vol = None
        if packet is not None and packet.val is not None:
            vol = LEDCtrl.clamp(packet.val, 0, 100)
        elif new_vol is not None:
            vol = LEDCtrl.clamp(new_vol, 0, 100)
        else:
            return
        self._audioCtrl.set_volume(vol)

    def _set_relays(self, packet: Packet, safetyctrl: bool = False):
        try:
            if safetyctrl:
                flipsw = self._ctrls.get_ctrl(packet.target)
                flipsw.set_state(bool(packet.val))
                self.send_packets(flipsw.set_state_of_leds(bool(packet.val), True))
            else:
                btn = self._ctrls.get_slavectrl(packet.target)
                btn.set_state(not btn.state)  # invert, since btn is momentary
                self.send_packets(btn.set_state(bool(packet.val)))  # set RELAY state

        except Full:
            logger.exception("Sendqueue was full. Packet(s) could not be sent")
        except CtrlNotFoundException:
            logger.exception("Ctrl not found")
            raise

        # TODO
        # IF ControlSwitch=ON, set relay!
        # relayPin = packet.target + 16
        # self._packet_sendqueue.put(Packet(HWEvent.SWITCH, relayPin, packet.val))

    def ledstrip_control(self, packet: Packet):
        """TODO"""

    def send_packets(
        self, packets: List, block: bool = False, timeout: float = None
    ) -> None:
        """Puts the packet into sendQueue. It will be picked up ASAP by packetSerial thread"""
        try:
            for p in packets:
                self._packet_sendqueue.put(p, block, timeout)
        except Full:
            logger.error("SendQueue was full. Packet(s) could not be sent")

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
            # send RequestStatus packet to get actual ctrls status
            self._packet_sendqueue.put(
                Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1
            )
        except (Full, TimeoutError) as err:
            logger.error(err)
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


# Button(s) pin,name,section,coordXY
# LEDS      pin,name,section,coordXY,board,minV,maxV
#
# Button LEDS (pin nr, PWMboard.#.pin)
