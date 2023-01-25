#!/usr/bin/env python

# import sys
# import os
from typing import List
import datetime
import logging
from queue import Queue, Full, Empty
from daemon.packetSerial import PacketSerial
from daemon.packet import Packet, HWEvent, ErrorType # noqa


logger = logging.getLogger('daemon.ctrlPanel')
# The buffer of Arduino is increased to 256 bytes (if it works)
# it was changed in platformio config file in VSCode
# 256 / 7bytes => 36 packets until buffer is full
MAX_PACKETS_IN_SEND_QUEUE = 36
SEND_HELLO_INTERVALL = 30  # seconds


class ControlPanel:
    def __init__(self):
        self._lastSentHello = None
        self._lastReceivedHello = None
        self._mainInputsOn = False
        self._mainLedsOn = False
        self._mainaudioOn = False
        self._mainMasterOn = bool(False)
        self._mainDemo = int(0)
        self._packet_sendqueue = Queue(MAX_PACKETS_IN_SEND_QUEUE)
        self._packet_receivedqueue = Queue()
        self._pserial = PacketSerial(self._packet_receivedqueue, self._packet_sendqueue)
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
            logger.info("ControlPanel stopping. Clearing packet queue...")
            with self._packet_sendqueue.mutex:
                self._packet_sendqueue.queue.clear()
                self._packet_sendqueue.all_tasks_done.notify_all()
                self._packet_sendqueue.unfinished_tasks = 0
            self._pserial.close_connection()
        except Exception as e:
            logger.error(e)

    def process(self) -> None:
        ''' Call this method regularly to process packets'''
        self.process_packets()
        if self.time_to_send_hello():
            self._pserial.send_hello()

    def process_packets(self) -> None:
        try:
            while(self._packet_receivedqueue.qsize > 0):
                self.__act(self._packet_receivedqueue.get(block=True, timeout=2))
        except Empty:
            pass

    def __act(self, packet: Packet) -> None:
        try:
            if(packet.hwEvent == HWEvent.BOOTMEGA):
                logger.info("Received BOOTMEGA packet. Mega was (re)booted")
                # TODO - Do Reset routine
                # send/return from this func RequestStatus packet to get current status
                self._packet_sendqueue.put(Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1)
                pass
            elif(packet.hwEvent == HWEvent.HELLO):
                self._lastReceivedHello = datetime.datetime.now()
                return None
            elif(packet.hwEvent == HWEvent.RESET):
                logger.info("Received RESET packet. starting reset routine")
                # TODO - Do Reset routine
                # send/return from this func RequestStatus packet to get current status
                self._packet_sendqueue.put(Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1)
                pass
            elif(packet.hwEvent == HWEvent.STATUS):
                # Status packet. Target == Switch pin.
                # Nothing has changed. Do not trigger switch behaviour
                pass
            elif(packet.hwEvent == HWEvent.SWITCH):
                # A switch has changed status. React
                self.switchStatusChanged(packet)
                pass
            elif(packet.hwEvent == HWEvent.UNDEFINED):
                logger.error("Recevied undefined package: %s", packet)
                pass
        except Full:
            pass
    
    def switchStatusChanged(self, packet: Packet) -> Packet:
        '''Handles button logic'''
        if packet.target == 12:  # MainSwitch
            self.shutdownPanel(packet.val)
        if not self._mainMasterOn: return

        if packet.target == 15:  # Inputs on / off
            self._mainInputsOn = bool(packet.val)
        if packet.target == 14:  # Backlight
            # TODO - turn off btn LEDs also?
            self._packet_sendqueue.put(Packet(HWEvent.SWITCH, 43, packet.val))
        if packet.target == 16:  # Sound on / off
            self._mainaudioOn = bool(packet.val)
        if not self._mainInputsOn: return

        if packet.target >= 2 and packet.target <= 11:
            self.playSound(packet)
        if packet.target >=17 and packet.target <= 26:  #pin 20,21 is excluded
            self.apply_sound_effect(packet)
        if packet.target == 27:
            self._record_audio(packet)
        if packet.target >=28 and packet.target <= 31:
            self.set_relays(packet)
        if packet.target >=32 and packet.target <= 37:
            self.ledstripControl(packet)
        if packet.target >=101 and packet.target <= 108:
            # analog controls adds '100' to pinnr
            self.ledstripControl(packet)
        if packet.target >=38 and packet.target <= 41:
            self.set_relays(packet)

    def set_relays(self, packet : Packet):
        # IF ControlSwitch=ON, set relay!
        # relayPin = packet.target + 16
        # self._packet_sendqueue.put(Packet(HWEvent.SWITCH, relayPin, packet.val))
        raise Exception()

    def time_to_send_hello(self):
        """ Is it time to send hello yet?"""
        if (self._lastSentHello is None or
                (datetime.datetime.now() - self._lastSentHello).total_seconds() > SEND_HELLO_INTERVALL):
            return True
        else:
            return False

"""
self._mainInputsOn = False
self._mainLedsOn = False
self._mainaudioOn = False
self._mainMasterOn = False
self.mainDemo = 0

HWEVENT:
UNDEFINED = 0,
LED = 1
I2CALED = 2
I2CBLED = 3
I2CCLED = 4
SWITCH = 5
DEMO = 6
BLINK = 7  # remember to turn OFF LED after Blink (Val == 16)
STATUS = 8
HELLO = 9
RESET = 10
BOOTMEGA = 11  # A package with this Event is sent when Mega starts up.

BLINKTARGET
AUDIO_PRESETBTNS = 200
SPEAKER_LEDS = 201
"""
# Button(s) pin,name,section,coordXY
# LEDS      pin,name,section,coordXY,board,minV,maxV
#
# Button LEDS (pin nr, PWMboard.#.pin)
