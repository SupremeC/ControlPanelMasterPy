#!/usr/bin/env python

# TODO!
#############################
# new Flag: InRecordingMode: bool
#   - Assign new Audio when B1-10 is pressed
# Cache and play Sound
# Record Audio to mem/file
# Apply Audio effects from Pedalboard
# Play "click on HwSwitch event?"`
# Control LED Strip(s) via Serial or over WiFi
# Do logger create new logfiles every day. Rotation?



from typing import List
import datetime
import logging
from queue import Queue, Full, Empty
from daemon.packetSerial import PacketSerial
from daemon.packet import Packet, HWEvent, ErrorType # noqa
from daemon.auxClass import HwCtrls, Hwctrl


logger = logging.getLogger('daemon.ctrlPanel')
# The buffer of Arduino is increased to 256 bytes (if it works)
# it was changed in platformio config file in VSCode
# 256 / 7bytes => 36 packets until buffer is full
MAX_PACKETS_IN_SEND_QUEUE = 36
SEND_HELLO_INTERVALL = 30  # seconds


class ControlPanel:
    def __init__(self):
        self._lastSentHello: datetime.datetime = None
        self._lastReceivedHello: datetime.datetime = None
        self._ctrls: HwCtrls = HwCtrls()
        self._mainMasterOn: Hwctrl
        self._mainInputsOn: Hwctrl
        self._mainaudioOn: Hwctrl
        self._mainbacklight: Hwctrl
        self._mainDemo: int = 0
        self._mainRecording: bool = False
        self._packet_sendqueue: Queue = Queue(MAX_PACKETS_IN_SEND_QUEUE)
        self._packet_receivedqueue: Queue = Queue()
        self._pserial: PacketSerial = PacketSerial(self._packet_receivedqueue, self._packet_sendqueue)
        logger.info("ControlPanel init. Using serial Port=" + self._pserial.port)

    def start(self):
        """Opens serial connection and start Read and Write worker threads"""
        try:
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

    def _process_packets(self) -> None:
        try:
            while(self._packet_receivedqueue.qsize > 0):
                self.__act(self._packet_receivedqueue.get(block=True, timeout=2))
        except Empty:
            pass

    def __act(self, packet: Packet) -> None:
        try:
            if(packet.hwEvent == HWEvent.BOOTMEGA):
                logger.info("Received BOOTMEGA packet. Mega was (re)booted")
                self.reset()
                # send/return from this func RequestStatus packet to get current status
                self._packet_sendqueue.put(Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1)
                pass
            elif(packet.hwEvent == HWEvent.HELLO):
                self._lastReceivedHello = datetime.datetime.now()
                return None
            elif(packet.hwEvent == HWEvent.RESET):
                logger.info("Received RESET packet. starting reset routine")
                self.reset()
                # send/return from this func RequestStatus packet to get current status
                self._packet_sendqueue.put(Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1)
                pass
            elif(packet.hwEvent == HWEvent.STATUS):
                # Status packet. Target == Switch pin.
                # Nothing has changed. Do not trigger switch behaviour
                pass
            elif(packet.hwEvent == HWEvent.SWITCH):
                # A switch has changed status. React
                self._switchStatusChanged(packet)
                pass
            elif(packet.hwEvent == HWEvent.UNDEFINED):
                logger.error("Recevied undefined package: %s", packet)
                pass
        except Full:
            pass
    
    def _switchStatusChanged(self, packet: Packet) -> Packet:
        '''Handles button logic'''
        if packet.target == 12:  # MainSwitch
            self.set_panelstatus(bool(packet.val))
        if not self._mainMasterOn.state: return

        if packet.target == 15:  # Inputs on / off
            self._mainInputsOn.set_state(bool(packet.val))

        if packet.target == 14:  # Backlight
            self.sendPackets(self._mainbacklight.set_state(bool(packet.val)))
            # TODO - turn off btn LEDs also?
        if packet.target == 16:  # Sound on / off
            self._mainaudioOn.state = bool(packet.val)

        if not self._mainInputsOn.state: return

        if packet.target >= 2 and packet.target <= 11:
            self.playSound(packet)
        if packet.target >=17 and packet.target <= 26:  #pin 20,21 is excluded
            self.apply_sound_effect(packet)
        if packet.target == 27:
            self._record_audio(packet)
        if packet.target >=28 and packet.target <= 31:
            self._set_relays(packet)
        if packet.target >=32 and packet.target <= 37:
            self.ledstripControl(packet)
        if packet.target >=38 and packet.target <= 41:
            self._set_relays(packet, safetyctrl = True)
        if packet.target >=101 and packet.target <= 108:
            # analog controls adds '100' to pinnr
            self.ledstripControl(packet)
        if packet.target == 109:
            self._setVolume(packet)
        
    def _set_relays(self, packet: Packet, safetyctrl: bool = False):
        try:
            if safetyctrl:
                ctrl = self._ctrls.get_ctrl(packet.target)
                self.sendPackets(ctrl.set_state(bool(packet.val)))
            else:
                slave = self._ctrls.get_slavectrl(packet.target)
                self.sendPackets(slave.set_state(bool(packet.val)))
        except Exception as e:
            logger.error(e)

        # IF ControlSwitch=ON, set relay!
        # relayPin = packet.target + 16
        # self._packet_sendqueue.put(Packet(HWEvent.SWITCH, relayPin, packet.val))
        raise Exception()

    def sendPackets(self, packets: List, block: bool = False, timeout: float = None) -> None:
        for p in packets:
            self._packet_sendqueue.put(p, block, timeout)

    def time_to_send_hello(self) -> bool:
        """ Is it time to send hello yet?"""
        if (self._lastSentHello is None or
                (datetime.datetime.now() - self._lastSentHello)
                    .total_seconds() > SEND_HELLO_INTERVALL):
            return True
        else:
            return False

    def reset(self):
        self._ctrls.reset()
        self.clearPacketQueue()
        self._mainMasterOn: Hwctrl = self._ctrls.get_ctrl(12)
        self._mainInputsOn: Hwctrl = self._ctrls.get_ctrl(15)
        self._mainaudioOn: Hwctrl = self._ctrls.get_ctrl(16)

    def set_panelstatus(self, state: bool):
        self._mainMasterOn.state = state
        if not state:
            self.sendPackets(self._ctrls.set_allLeds(False))


    def clearPacketQueue(self):
        with self._packet_sendqueue.mutex:
            logger.info("clearing packet queue of {}".format(self._packet_sendqueue.qsize))
            self._packet_sendqueue.queue.clear()
            self._packet_sendqueue.all_tasks_done.notify_all()
            self._packet_sendqueue.unfinished_tasks = 0

# Button(s) pin,name,section,coordXY
# LEDS      pin,name,section,coordXY,board,minV,maxV
#
# Button LEDS (pin nr, PWMboard.#.pin)
