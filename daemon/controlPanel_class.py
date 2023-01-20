#!/usr/bin/env python

# import sys
# import os
import datetime
import logging
import packetSerial


logger = logging.getLogger('daemon.ctrlPanel')
SEND_HELLO_INTERVALL = 30


class ControlPanel:
    def __init__(self):
        """do important INIT stuff"""
        self._lastSentHello = None
        self._lastReceivedHello = None
        self._pserial = packetSerial.PacketSerial()
        logger.info("ControlPanel init. Port=" + self._pserial.port)

    def start(self):
        """Opens serial connection and other stuff"""
        try:
            self._pserial.open_connection()
        except Exception as e:
            logger.error(e)

    def stop(self):
        """Closes serial connection and does general cleanup"""
        try:
            logger.info("ControlPanel stopping...")
            self._pserial.close()
            logger.info("ControlPanel stopped")
        except Exception as e:
            logger.error(e)

    def update(self):
        packets = self._pserial.read_packets()
        self.process_packets(packets)
        if self.time_to_send_hello():
            self._pserial.send_hello()

    def time_to_send_hello(self):
        """ Is it time to send hello yet?"""
        if (self._lastSentHello is None or
                (datetime.now() - self._lastSentHello).total_seconds()):
            return True
        else:
            return False

    def process_packets(self, packets):
        pass
