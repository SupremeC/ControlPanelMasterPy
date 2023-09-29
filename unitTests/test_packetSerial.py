#!/usr/bin/env python


from queue import Queue
import daemon.packetSerial
import daemon.setup_logger
from daemon.packet import Packet, HWEvent, ErrorType # noqa
import unittest   # noqa
from datetime import datetime, timedelta
import time
from daemon.slidingWindowClass import SlidingWindow



class Test_Threading(unittest.TestCase):
    def test_Threading_threadskilledcorrectly(self):
        # arrange
        self._packet_receivedqueue = Queue()
        self._packet_sendqueue = Queue(30)
        ps = daemon.packetSerial.PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue)

        # act
        ps.open_connection()
        time.sleep(1)

        # assert that threads are running
        self.assertTrue(ps._readserial_thread.is_alive(), "ReadThread should be running")
        self.assertTrue(ps._writeserial_thread.is_alive(), "WriteThread should be running")
        ps.close_connection()
         # assert that threads are stopped
        self.assertFalse(ps._readserial_thread.is_alive(), "ReadThread should be stopped")
        self.assertFalse(ps._writeserial_thread.is_alive(), "WriteThread should be stopped")
        # assert that signal is reset
        self.assertFalse(ps._rshutdown_flag.is_set(), "read Flag must be reset")
        self.assertFalse(ps._sshutdown_flag.is_set(), "write Flag must be reset")

    def test_SerialPort_findArduino(self):
        '''Requires an actual Arduino connected to one of the USB ports'''
        # arrange
        self._packet_receivedqueue = Queue()
        self._packet_sendqueue = Queue(30)
        ps = daemon.packetSerial.PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue)

        # act
        port = ps.find_arduino()

        # assert
        self.assertIsNotNone(port, "Port is not found")
        self.assertFalse("Error" in port, "Port not found")


if __name__ == '__main__':
    unittest.main()
 