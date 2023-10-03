#!/usr/bin/env python

# TODO Global!
#############################
# Move one ledstrip to ceiling lamp?
# Bedlamp - which one?
# Bedlamp - support dimming? How?
# Add USB socket to drawing
# Add text to effect btns?
# How to restore (btn)state when either Mega or Mastery reboots?


# TODO MasterPY!
#############################
# Cache and play Sound
#  - Stop playback of clip when new Clip plays
#  - Stop Playback of clip when recording
#  - Stop temp-playback when applying effect
#  - Stop temp-playback when existing clip starts to play
# Play "click on HwSwitch event?"`
# Play "workingOnIt" when Applying effect?
# Control LED Strip(s) via Serial or over WiFi
 

# TODO MEGA!
#############################
# ButtonClass jled  and jled-pca9685-hal
# analog btn handler & conversion
# analog "+100" ID support
# 


import datetime
import logging
from queue import Empty, Full, Queue
from typing import List

from .ctrlsClass import Hwctrl, HwCtrls
from .packet import ErrorType, HWEvent, Packet  # noqa
from .packetSerial import PacketSerial
from .slidingWindowClass import SlidingWindow

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
        self._packet_sendqueue: Queue = Queue(MAX_PACKETS_IN_SEND_QUEUE)
        self._packet_receivedqueue: Queue = Queue()
        self._pserial: PacketSerial = PacketSerial(self._packet_receivedqueue, self._packet_sendqueue)
        logger.info("ControlPanel init. Using serial Port=" + self._pserial.port)

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
        logger.debug("process.loop()...")
        self._process_packets()
        if self.time_to_send_hello():
            self._pserial.send_hello()
        logger.debug("process.loop() complete")
        
    def _process_packets(self) -> None:
        logger.debug("_process_packets loop...")
        try:
            while(self._packet_receivedqueue.qsize() > 0):
                self.__act(self._packet_receivedqueue.get(block=True, timeout=2))
                self._packet_receivedqueue.task_done()
        except Empty:
            pass
        logger.debug("_process_packets loop: complete")

    def __act(self, packet: Packet) -> None:
        try:
            if(packet.hwEvent == HWEvent.BOOTMEGA):
                logger.info("Received BOOTMEGA packet. Mega was (re)booted")
                self.reset()
                pass
            elif(packet.hwEvent == HWEvent.HELLO):
                self._lastReceivedHello = datetime.datetime.now()
                return None
            elif(packet.hwEvent == HWEvent.RESET):
                logger.info("Received RESET packet. starting reset routine")
                self.reset()
                pass
            elif(packet.hwEvent == HWEvent.STATUS):
                # Status packet. Target == Switch pin.
                self._set_status_no_action(packet)
                pass
            elif(packet.hwEvent == HWEvent.SWITCH):
                # A switch has changed status. React
                self._switchStatusChanged(packet)
                pass
            elif(packet.hwEvent == HWEvent.UNDEFINED):
                logger.warn("Recevied undefined package: %s", packet)
                pass
        except Full as errFull:
            logger.error(errFull)
        except Exception as error:
            logger.error(errFull)
            pass

    
    def _switchStatusChanged(self, packet: Packet) -> Packet:
        try:
            '''Handles button logic'''
            if packet.target == 12:  # MainSwitch
                self.set_panelstatus(bool(packet.val))
            if not self._mainMasterOn.state: return

            if packet.target == 15:  # Inputs on / off
                self._mainInputsOn.set_state(bool(packet.val))
            if packet.target == 14:  # Backlight
                self.sendPackets(self._mainbacklight.set_state(bool(packet.val)))
                # TODO - turn off btn LEDs also? YES!
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
            if packet.target >=52 and packet.target <= 59:
                # analog controls (A0 == 52, A1=53, ...)
                self.ledstripControl(packet)
            if packet.target == 60:
                self._setVolume(packet)
        except Exception as err:
            logger.error(err)

    def _set_relays(self, packet: Packet, safetyctrl: bool = False):
        try:
            if safetyctrl:
                # turn on slave ctrls (LEDs)
                relayctrl = self._ctrls.get_ctrl(packet.target)
                self.sendPackets(relayctrl.set_state(bool(packet.val)))
            else:
                # activate actual RELAY output
                slavectrl = self._ctrls.get_slavectrl(packet.target)
                self.sendPackets(slavectrl.set_state(bool(packet.val)))
        except Exception as e:
            logger.error(e)

        # TODO
        # IF ControlSwitch=ON, set relay!
        # relayPin = packet.target + 16
        # self._packet_sendqueue.put(Packet(HWEvent.SWITCH, relayPin, packet.val))
        raise Exception()

    def ledstripControl(self, packet: Packet):
        pass

    def sendPackets(self, packets: List, block: bool = False, timeout: float = None) -> None:
        """ Puts the packet into sendQueue. It will be picked up ASAP by packetSerial thread"""
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
        logger.debug("reseting 'controlPanel_class' instance")
        try:
            self._ctrls.reset()
            self.clearPacketQueue()
            self._mainMasterOn: Hwctrl = self._ctrls.get_ctrl(12)
            self._mainInputsOn: Hwctrl = self._ctrls.get_ctrl(15)
            self._mainaudioOn: Hwctrl = self._ctrls.get_ctrl(16)
            # send RequestStatus packet to get actual ctrls status
            self._packet_sendqueue.put(Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1)
        except Exception as err:
            logger.error(err)
        else:
            logger.debug("reset done")

    def set_panelstatus(self, state: bool):
        self._mainMasterOn.state = state
        if not state:
            self.sendPackets(self._ctrls.set_allLeds(False))


    def clearPacketQueue(self):
        if(self._packet_sendqueue.qsize() > 0):
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
