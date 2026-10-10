#!/usr/bin/env python
"""Unit tests for daemon.packet"""

import unittest

from daemon.packet import Packet, HWEvent, ErrorType


class Test_PacketContructor(unittest.TestCase):
    def test_NoParamsConstructor(self):
        # act
        p = Packet()

        # assert (default values)
        self.assertEqual(p.hw_event, HWEvent.UNDEFINED)
        self.assertEqual(p.target, 0)
        self.assertEqual(p.error, ErrorType.NONE_)
        self.assertEqual(p.val, 0)

    def test_1ParamsConstructor(self):
        # arrange
        hw = 7
        ta = 42
        er = 2
        va = 55000
        mutable_bytes = bytearray()
        mutable_bytes.append(hw)
        mutable_bytes.append(ta)
        mutable_bytes.append(er)
        mutable_bytes.extend(va.to_bytes(length=2, byteorder="little", signed=False))

        # act
        p = Packet(bytes(mutable_bytes))

        # assert
        self.assertEqual(p.hw_event, hw)
        self.assertEqual(p.target, ta)
        self.assertEqual(p.error, er)
        self.assertEqual(p.val, va)

    def test_1ParamsConstructor_unknownEventIsIgnored(self):
        # arrange: first byte 200 is not a valid HWEvent
        raw = bytes([200, 1, 0, 0, 0])

        # act
        p = Packet(raw)

        # assert: packet keeps its default values
        self.assertEqual(p.hw_event, HWEvent.UNDEFINED)
        self.assertEqual(p.target, 0)
        self.assertEqual(p.val, 0)

    def test_3ParamsConstructor(self):
        # arrange
        event = HWEvent.BLINKFOREVER
        target = 100
        val = 64000

        # act
        p = Packet(event, target, val)

        # assert
        self.assertEqual(p.hw_event, event)
        self.assertEqual(p.target, target)
        self.assertEqual(p.error, ErrorType.NONE_)
        self.assertEqual(p.val, val)
        self.assertTrue(p.hw_event == event, "can I compare Enums with ==")
        self.assertTrue(p.hw_event is event, "can I compare Enums with 'is'")
        self.assertTrue(p.hw_event == 7, "can I compare Enums with int")

    def test_asBytes(self):
        # arrange
        p = Packet(HWEvent.HELLO, 42, 1000)

        # act
        b = p.as_bytes()

        # assert
        self.assertEqual(len(b), 5)
        self.assertEqual(b[0], 9)
        self.assertEqual(b[1], 42)
        self.assertEqual(b[2], 0)
        self.assertEqual(int.from_bytes(b[-2:], byteorder="little"), 1000)

    def test_asBytes_roundTrip(self):
        # arrange
        original = Packet(HWEvent.RELAY, 45, 1)

        # act
        parsed = Packet(original.as_bytes())

        # assert
        self.assertEqual(parsed.hw_event, original.hw_event)
        self.assertEqual(parsed.target, original.target)
        self.assertEqual(parsed.error, original.error)
        self.assertEqual(parsed.val, original.val)

    def test_PrintRepr(self):
        # arrange
        p = Packet(HWEvent.HELLO, 42, 1000)
        p.error = ErrorType.FAILEDTOPARSEPACKET

        # act
        actual_packet_repr = str(p)

        # assert
        self.assertTrue(actual_packet_repr.startswith("Packet("))
        self.assertTrue("target" in actual_packet_repr)
        self.assertTrue(len(actual_packet_repr) > 30)

    def test_asHumanFriendlyStr(self):
        # arrange
        p = Packet(HWEvent.HELLO, 42, 1000)
        p.error = ErrorType.FAILEDTOPARSEPACKET

        # act
        s = p.as_human_friendly_str()

        # assert
        self.assertIn("HELLO", s)
        self.assertIn("t=42", s)
        self.assertIn("v=1000", s)
        self.assertIn("FAILEDTOPARSEPACKET", s)


if __name__ == "__main__":
    unittest.main()
