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

import serial

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
    def _make(self, mock_comports, ports=_FAKE_PORTS) -> daemon.packet_serial.PacketSerial:
        mock_comports.return_value = ports
        self._packet_receivedqueue = Queue()
        self._packet_sendqueue = Queue(30)
        ps = daemon.packet_serial.PacketSerial(
            self._packet_receivedqueue, self._packet_sendqueue
        )
        ps.RECONNECT_INTERVAL = 0.05
        self.addCleanup(ps.stop)
        return ps

    @staticmethod
    def _fake_port(mock_serial):
        fake_port = mock_serial.return_value
        fake_port.is_open = True
        fake_port.in_waiting = 0
        return fake_port

    def test_SerialPort_findArduino(self, mock_comports):
        # arrange
        mock_comports.return_value = _FAKE_PORTS

        # act
        port = daemon.packet_serial.PacketSerial.find_port_to_arduino()

        # assert
        self.assertEqual("dev5", port, "Wrong Port found")

    def test_SerialPort_noArduino(self, mock_comports):
        # arrange
        mock_comports.return_value = _FAKE_PORTS[:-1]

        # act
        port = daemon.packet_serial.PacketSerial.find_port_to_arduino()

        # assert
        self.assertIsNone(port)

    @mock.patch("serial.Serial")
    def test_constructor_opensNothing(self, mock_serial, mock_comports):
        # act
        ps = self._make(mock_comports)

        # assert
        mock_comports.assert_not_called()
        mock_serial.assert_not_called()
        self.assertIsNone(ps.port)
        self.assertIsNone(ps.connected_at)
        self.assertIsNone(ps._readserial_thread)
        self.assertFalse(ps.is_conn_open)

    @mock.patch("serial.Serial")
    def test_start_opensPortAndStartsThreads(self, mock_serial, mock_comports):
        # arrange
        self._fake_port(mock_serial)
        ps = self._make(mock_comports)

        # act
        ps.start()

        # assert
        mock_serial.assert_called_once_with(port="dev5", baudrate=115200, timeout=1)
        self.assertEqual("dev5", ps.port)
        self.assertIsNotNone(ps.connected_at)
        self.assertTrue(ps.is_conn_open)
        self.assertTrue(ps._readserial_thread.is_alive(), "ReadThread should be running")
        self.assertTrue(ps._writeserial_thread.is_alive(), "WriteThread should be running")

    @mock.patch("serial.Serial")
    def test_open_flushesBeforeAnythingElse(self, mock_serial, mock_comports):
        # arrange
        fake_port = self._fake_port(mock_serial)
        ps = self._make(mock_comports)

        # act
        ps.start()

        # assert: input dropped, then a lone divider ends any half frame
        fake_port.reset_input_buffer.assert_called_once()
        self.assertEqual(mock.call(b"\x00"), fake_port.write.call_args_list[0])

    @mock.patch("serial.Serial")
    def test_open_writeFails_portClosedAndRetried(self, mock_serial, mock_comports):
        # arrange
        fake_port = self._fake_port(mock_serial)
        fake_port.write.side_effect = [serial.SerialException("gone"), None, None, None]
        ps = self._make(mock_comports)

        # act
        ps.start()

        # assert
        fake_port.close.assert_called_once()
        self.assertTrue(_wait_until(lambda: ps.is_conn_open), "never retried")

    @mock.patch("serial.Serial")
    def test_stop_stopsThreadsAndClosesPort(self, mock_serial, mock_comports):
        # arrange
        fake_port = self._fake_port(mock_serial)
        ps = self._make(mock_comports)
        ps.start()
        read_thread, write_thread = ps._readserial_thread, ps._writeserial_thread

        # act
        ps.stop()

        # assert
        fake_port.close.assert_called_once()
        self.assertFalse(read_thread.is_alive())
        self.assertFalse(write_thread.is_alive())
        self.assertIsNone(ps._readserial_thread)
        self.assertIsNone(ps._writeserial_thread)
        self.assertFalse(ps.is_conn_open)

    @mock.patch("serial.Serial")
    def test_stop_twiceIsNoop(self, mock_serial, mock_comports):
        # arrange
        fake_port = self._fake_port(mock_serial)
        ps = self._make(mock_comports)
        ps.start()

        # act
        ps.stop()
        ps.stop()

        # assert
        fake_port.close.assert_called_once()

    @mock.patch("serial.Serial")
    def test_stop_beforeStartIsNoop(self, mock_serial, mock_comports):
        # arrange
        ps = self._make(mock_comports)

        # act
        ps.stop()

        # assert
        mock_serial.return_value.close.assert_not_called()
        self.assertFalse(ps.is_conn_open)

    @mock.patch("serial.Serial")
    def test_start_withoutArduino_connectsWhenItAppears(self, mock_serial, mock_comports):
        # arrange
        self._fake_port(mock_serial)
        ps = self._make(mock_comports, ports=_FAKE_PORTS[:-1])

        # act
        with self.assertLogs("daemon.PacketSerial", "WARNING") as logs:
            ps.start()
            self.assertTrue(_wait_until(lambda: mock_comports.call_count >= 3))
        self.assertFalse(ps.is_conn_open)
        mock_comports.return_value = _FAKE_PORTS

        # assert
        self.assertTrue(_wait_until(lambda: ps.is_conn_open), "never connected")
        self.assertTrue(ps._readserial_thread.is_alive())
        missing = [r for r in logs.output if "Arduino not found" in r]
        self.assertEqual(1, len(missing), "a missing Mega must be logged once")

    @mock.patch("serial.Serial")
    def test_connectionLost_reconnects(self, mock_serial, mock_comports):
        # arrange
        fake_port = mock_serial.return_value
        fake_port.is_open = True
        reads = {"n": 0}

        def in_waiting():
            reads["n"] += 1
            if reads["n"] == 2:
                raise serial.SerialException("device disconnected")
            return 0

        type(fake_port).in_waiting = mock.PropertyMock(side_effect=in_waiting)
        ps = self._make(mock_comports)

        # act
        ps.start()
        first_connect = ps.connected_at

        # assert
        self.assertTrue(_wait_until(lambda: mock_serial.call_count >= 2), "no reconnect")
        self.assertTrue(_wait_until(lambda: ps.connected_at != first_connect))
        fake_port.close.assert_called_once()
        self.assertTrue(_wait_until(lambda: ps.is_conn_open))

    @mock.patch("serial.Serial")
    def test_packetsAreDroppedWhileDisconnected(self, mock_serial, mock_comports):
        # arrange
        ps = self._make(mock_comports, ports=_FAKE_PORTS[:-1])
        ps.start()

        # act
        self._packet_sendqueue.put(Packet(HWEvent.HELLO, 1, 1))

        # assert
        self.assertTrue(_wait_until(self._packet_sendqueue.empty), "packet never taken")
        mock_serial.return_value.write.assert_not_called()
        self.assertEqual([], ps.last_sent)

    @mock.patch("serial.Serial")
    def test_Threading_sendQueueIsWrittenToPort(self, mock_serial, mock_comports):
        # arrange
        fake_port = self._fake_port(mock_serial)
        ps = self._make(mock_comports)
        packet = Packet(HWEvent.HELLO, 33, 44)

        # act
        ps.start()
        try:
            self._packet_sendqueue.put(packet)
            self.assertTrue(
                _wait_until(lambda: fake_port.write.call_count >= 2),
                "packet was never written to the port",
            )
        finally:
            ps.stop()

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

        def read_until(*_args, **_kwargs):
            fake_port.in_waiting = 0
            return b"\x03\t!\x02,\x01\x00"

        fake_port.read_until.side_effect = read_until
        ps = self._make(mock_comports)

        # act
        ps.start()
        try:
            self.assertTrue(
                _wait_until(lambda: not self._packet_receivedqueue.empty()),
                "no packet was received",
            )
        finally:
            ps.stop()

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
