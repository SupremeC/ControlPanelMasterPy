#!/usr/bin/env python
"""Unit tests for daemon.packet_serial.

pyserial is mocked so the tests never touch /dev/ttyACM0 (which the live
daemon owns).
"""

import collections
from queue import Queue
import time
import unittest
import unittest.mock as mock
from unittest.mock import ANY

import daemon.packet_serial
from daemon.packet import Packet, HWEvent


_PortInfo = collections.namedtuple("_PortInfo", ("device", "name", "manufacturer", "hwid"))
_FAKE_PORTS = [
    _PortInfo("dev0", "dev0Name", "dev0Manuf", 0),
    _PortInfo(None, "dev1Name", "dev1Manuf", 1),
    _PortInfo("dev2", None, "dev2Manuf", 2),
    _PortInfo("dev3", "dev3Name", None, 3),
    _PortInfo("dev4", "dev4Name", "dev1Manuf", None),
    _PortInfo("dev5", "MyOwnArduinoMegaMock", "Arduino", 5),  # <-- the one to find
]


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@mock.patch("serial.tools.list_ports.comports", autospec=True)
class Test_PacketSerial(unittest.TestCase):
    def _make(self, mock_comports) -> daemon.packet_serial.PacketSerial:
        mock_comports.return_value = _FAKE_PORTS
        self._packet_receivedqueue = Queue()
        self._packet_sendqueue = Queue(30)
        return daemon.packet_serial.PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue
        )

    def test_SerialPort_findArduino(self, mock_comports):
        # arrange
        ps = self._make(mock_comports)

        # act
        port = ps.find_port_to_arduino()

        # assert
        self.assertEqual("dev5", port, "Wrong Port found")
        self.assertEqual("dev5", ps.port)

    def test_SerialPort_noArduino(self, mock_comports):
        # arrange
        ps = self._make(mock_comports)
        mock_comports.return_value = _FAKE_PORTS[:-1]

        # act
        port = ps.find_port_to_arduino()

        # assert
        self.assertTrue(port.startswith("Error"))

    @mock.patch("serial.Serial")
    def test_Threading_threadskilledcorrectly(self, mock_serial, mock_comports):
        # arrange
        fake_port = mock_serial.return_value
        fake_port.is_open = True
        fake_port.in_waiting = 0
        ps = self._make(mock_comports)

        # act
        ps.open_connection()

        # assert
        mock_serial.assert_called_once_with(port="dev5", baudrate=115200)
        self.assertTrue(ps.is_conn_open)
        self.assertTrue(ps._readserial_thread.is_alive(), "ReadThread should be running")
        self.assertTrue(ps._writeserial_thread.is_alive(), "WriteThread should be running")

        ps.close_connection()

        fake_port.close.assert_called_once()
        self.assertIsNone(ps._readserial_thread, "ReadThread should be stopped")
        self.assertIsNone(ps._writeserial_thread, "WriteThread should be stopped")
        self.assertFalse(ps._rshutdown_flag.is_set(), "read Flag must be reset")
        self.assertFalse(ps._sshutdown_flag.is_set(), "write Flag must be reset")

    @mock.patch("serial.Serial")
    def test_Threading_sendQueueIsWrittenToPort(self, mock_serial, mock_comports):
        # arrange
        fake_port = mock_serial.return_value
        fake_port.is_open = True
        fake_port.in_waiting = 0
        ps = self._make(mock_comports)
        packet = Packet(HWEvent.HELLO, 33, 44)

        # act
        ps.open_connection()
        try:
            self._packet_sendqueue.put(packet)
            self.assertTrue(
                _wait_until(lambda: fake_port.write.call_count >= 2),
                "packet was never written to the port",
            )
        finally:
            ps.close_connection()

        # assert: COBS-encoded packet followed by the divider byte
        fake_port.write.assert_has_calls(
            [mock.call(b"\x03\t!\x02,\x01"), mock.call(b"\x00")]
        )
        self.assertEqual(ps.last_sent, [packet])
        self.assertTrue(self._packet_sendqueue.empty())

    @mock.patch("serial.Serial")
    def test_Threading_receivedBytesAreQueuedAsPackets(self, mock_serial, mock_comports):
        # arrange
        fake_port = mock_serial.return_value
        fake_port.is_open = True
        # one packet waiting, then nothing
        fake_port.in_waiting = 7
        fake_port.read_until.return_value = b"\x03\t!\x02,\x01\x00"

        def read_until(*_args, **_kwargs):
            fake_port.in_waiting = 0
            return b"\x03\t!\x02,\x01\x00"

        fake_port.read_until.side_effect = read_until
        ps = self._make(mock_comports)

        # act
        ps.open_connection()
        try:
            self.assertTrue(
                _wait_until(lambda: not self._packet_receivedqueue.empty()),
                "no packet was received",
            )
        finally:
            ps.close_connection()

        # assert
        received = self._packet_receivedqueue.get_nowait()
        self.assertEqual(received.hw_event, HWEvent.HELLO)
        self.assertEqual(received.target, 33)
        self.assertEqual(received.val, 44)
        self.assertEqual(ps.last_received, [received])

    def test_send_hello_queuesHelloPacket(self, mock_comports):
        # arrange
        ps = self._make(mock_comports)

        # act
        ps.send_hello()

        # assert
        p = self._packet_sendqueue.get_nowait()
        self.assertEqual(p.hw_event, HWEvent.HELLO)


if __name__ == "__main__":
    unittest.main()
