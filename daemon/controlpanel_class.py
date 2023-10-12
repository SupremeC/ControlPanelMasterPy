"""ControlPanel_Class"""


import datetime
import logging
from queue import Empty, Full, Queue
from typing import List

from .ctrls_class import Hwctrl, HwCtrls
from .packet import HWEvent, Packet  # noqa
from .packet_serial import PacketSerial

logger = logging.getLogger('daemon.ctrlPanel')
# The buffer of Arduino is increased to 256 bytes (if it works)
# it was changed in platformio config file in VSCode
# 256 / 7bytes => 36 packets until buffer is full
MAX_PACKETS_IN_SEND_QUEUE = 36
SEND_HELLO_INTERVALL = 30  # seconds


class ControlPanel:
    """
    Master class (besides controlPanelDaemon of course)
    """
    def __init__(self):
        self._last_sent_hello: datetime.datetime = None
        self._last_received_hello: datetime.datetime = None
        self._ctrls: HwCtrls = HwCtrls()
        self._mainMasterOn: Hwctrl
        self._mainInputsOn: Hwctrl
        self._mainaudioOn: Hwctrl
        self._main_demo: int = 0
        self._packet_sendqueue: Queue = Queue(MAX_PACKETS_IN_SEND_QUEUE)
        self._packet_receivedqueue: Queue = Queue()
        self._pserial: PacketSerial = PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue)
        logger.info("ControlPanel init. Using serial Port=%s", self._pserial.port)

    def start(self):
        """Opens serial connection and start Read and Write worker threads"""
        try:
            self.reset()
            self._pserial.open_connection()
        except Exception as e:
            logger.error(e)

    def stop(self):
        """Closes serial connection and does general cleanup"""
        try:
            logger.info("ControlPanel stopping...")
            self.reset()
            self._pserial.close_connection()
        except Exception as e:
            logger.error(e)

    def process(self) -> None:
        ''' Call this method regularly to process packets'''
        self._process_packets()
        if self.time_to_send_hello():
            self._pserial.send_hello()
            self._last_sent_hello = datetime.datetime.now

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
                self._set_status_no_action(packet)
            elif packet.hw_event == HWEvent.SWITCH:
                # A switch has changed status. React
                self._switch_status_changed(packet)
            elif packet.hw_event == HWEvent.UNDEFINED:
                logger.warning("Recevied undefined package: %s", packet)
        except Full as err_full:
            logger.error(err_full)
        except Exception as error:
            logger.error(error)


    def _switch_status_changed(self, packet: Packet) -> Packet:
        '''Handles button logic'''
        try:
            if packet.target == 12:  # MainSwitch
                self.set_panelstatus(bool(packet.val))
            if not self._mainMasterOn.state:
                return
            if packet.target == 15:  # Inputs on / off
                self._mainInputsOn.set_state(bool(packet.val))
            if packet.target == 14:  # Backlight
                p = self._ctrls.get_ctrl_by_name("BacklightSw").set_state(packet.val)
                self.send_packets(p) # turn on/off LED indicator
                relayctrl = self._ctrls.get_ctrl_by_name("BacklightRelay")
                p2 = relayctrl.set_state(bool(packet.val))
                self.send_packets(p2) # turn PowerRelay on/ff for backlight pwr
            if packet.target == 16:  # Sound on / off
                self._mainaudioOn.state = bool(packet.val)
            if not self._mainInputsOn.state:
                return
            if packet.target >= 2 and packet.target <= 11:
                self.playSound(packet)
            if packet.target >=17 and packet.target <= 26:  #pin 20,21 is excluded
                self.apply_sound_effect(packet)
            if packet.target == 27:
                self._record_audio(packet)
            if packet.target >=28 and packet.target <= 31:
                self._set_relays(packet)
            if packet.target >=32 and packet.target <= 37:
                self.ledstrip_control(packet)
            if packet.target >=38 and packet.target <= 41:
                self._set_relays(packet, safetyctrl = True)
            if packet.target >=52 and packet.target <= 59:
                # analog controls (A0 == 52, A1=53, ...)
                self.ledstrip_control(packet)
            if packet.target == 60:
                self._setVolume(packet)
        except Exception as err:
            logger.error(err)

    def _set_relays(self, packet: Packet, safetyctrl: bool = False):
        try:
            if safetyctrl:
                # turn on slave ctrls (LEDs)
                relayctrl = self._ctrls.get_ctrl(packet.target)
                self.send_packets(relayctrl.set_state(bool(packet.val)))
            else:
                # activate actual RELAY output
                slavectrl = self._ctrls.get_slavectrl(packet.target)
                self.send_packets(slavectrl.set_state(bool(packet.val)))
        except Exception as e:
            logger.error(e)

        # TODO
        # IF ControlSwitch=ON, set relay!
        # relayPin = packet.target + 16
        # self._packet_sendqueue.put(Packet(HWEvent.SWITCH, relayPin, packet.val))

    def ledstrip_control(self, packet: Packet):
        """TODO"""

    def send_packets(self, packets: List, block: bool = False, timeout: float = None) -> None:
        """ Puts the packet into sendQueue. It will be picked up ASAP by packetSerial thread"""
        for p in packets:
            self._packet_sendqueue.put(p, block, timeout)

    def time_to_send_hello(self) -> bool:
        """ Is it time to send hello yet?"""
        if (self._last_sent_hello is None or
                (datetime.datetime.now() - self._last_sent_hello)
                    .total_seconds() > SEND_HELLO_INTERVALL):
            return True
        else:
            return False

    def reset(self):
        """
        Resets internal HW ctrls status
        Clears outgoing queue
        Sends request-STATUS msg to Arduino to syncronize
        ctrls between the systems.
        """
        logger.debug("reseting 'controlPanel_class' instance")
        try:
            self._ctrls.reset()
            self.clear_packet_queue()
            self._mainMasterOn: Hwctrl = self._ctrls.get_ctrl(12)
            self._mainInputsOn: Hwctrl = self._ctrls.get_ctrl(15)
            self._mainaudioOn: Hwctrl = self._ctrls.get_ctrl(16)
            # send RequestStatus packet to get actual ctrls status
            self._packet_sendqueue.put(Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1)
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

# Button(s) pin,name,section,coordXY
# LEDS      pin,name,section,coordXY,board,minV,maxV
#
# Button LEDS (pin nr, PWMboard.#.pin)
