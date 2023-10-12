#!/usr/bin/env python



import collections
from queue import Queue
import daemon.packet_serial
import daemon.setup_logger
from daemon.packet import Packet, HWEvent, ErrorType # noqa
import unittest   # noqa
import unittest.mock as mock
from unittest.mock import ANY
from datetime import datetime, timedelta
import time
from daemon.sliding_window import SlidingWindow
import serial


class Test_Threading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # arrange
        pass

    @mock.patch("serial.Serial")
    def test_Threading_threadskilledcorrectly(self, mock_serial):
        # arrange
        self._packet_receivedqueue = Queue()
        self._packet_sendqueue = Queue(30)
        ps = daemon.packet_serial.PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue)
        # mock_serial.is_open = True

        # act
        ps.open_connection()
        time.sleep(1)

        #assert stuff
        mock_serial.assert_called_once_with(port=ANY, baudrate=115200)

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

    @mock.patch("serial.tools.list_ports.comports", autospec=True)
    def test_SerialPort_findArduino(self, mock_serial_comports):
        # arrange
        p = collections.namedtuple('p', ('device', 'name', 'manufacturer', 'hwid'))
        ports = [
                p('dev0','dev0Name', 'dev0Manuf', 0),
                p(None,'dev1Name', 'dev1Manuf', 1),
                p('dev2',None, 'dev2Manuf', 2),
                p('dev3','dev3Name', None, 3),
                p('dev4','dev4Name', 'dev1Manuf', None),
                p('dev5','MyOwnArduinoMegaMock', 'Arduino', 5) # <-- this is the one I should find
                ]

        mock_serial_comports.return_value = ports
        self._packet_receivedqueue = Queue()
        self._packet_sendqueue = Queue(30)
        ps = daemon.packet_serial.PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue)

        # act
        port = ps.find_port_to_arduino()

        # assert
        self.assertIsNotNone(port, "Port is not found")
        self.assertEqual("dev5", port, "Wrong Port found")

    @classmethod
    def tearDownClass(cls):
        pass

if __name__ == '__main__':
    unittest.main()
 