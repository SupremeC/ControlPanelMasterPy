#!/usr/bin/env python
"""Unit tests for the COBS encode/decode helpers in daemon.packet_serial"""

import unittest

from daemon.packet_serial import PacketSerial
from daemon.packet import Packet, HWEvent, ErrorType


class Test_COBS(unittest.TestCase):
    def test_Encode(self):
        # arrange
        expected = b"\x03\t!\x02,\x01"
        p = Packet(HWEvent.HELLO, 33, 44)

        # act
        actual = PacketSerial.encode_packet(p)

        # assert: the packet divider (b'\x00') is NOT part of the encoded packet
        self.assertEqual(actual, expected)
        self.assertNotIn(0, actual)

    def test_Decode(self):
        # arrange: decode_packet expects the divider byte to be stripped already
        expected = Packet(HWEvent.HELLO, 33, 44)

        # act
        actual = PacketSerial.decode_packet(b"\x03\t!\x02,\x01")

        # assert
        self.assertEqual(expected.hw_event, actual.hw_event)
        self.assertEqual(expected.target, actual.target)
        self.assertEqual(expected.error, actual.error)
        self.assertEqual(expected.val, actual.val)

    def test_RoundTrip(self):
        # arrange
        original = Packet(HWEvent.I2CBLED, 7, 4094)

        # act
        decoded = PacketSerial.decode_packet(PacketSerial.encode_packet(original))

        # assert
        self.assertEqual(decoded.hw_event, HWEvent.I2CBLED)
        self.assertEqual(decoded.target, 7)
        self.assertEqual(decoded.error, ErrorType.NONE_)
        self.assertEqual(decoded.val, 4094)


if __name__ == "__main__":
    unittest.main()
