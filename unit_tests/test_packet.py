#!/usr/bin/env python

"""
import sys
from pathlib import Path
sys.path[0] = str(Path(sys.path[0]).parent)
"""


from daemon.packet import Packet, HWEvent, ErrorType   # noqa
import unittest   # noqa


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
        mutable_bytes.append(hw)  # hw.to_bytes(1, "little", signed=False)
        mutable_bytes.append(ta)
        mutable_bytes.append(er)
        mutable_bytes.extend(va.to_bytes(length=2,
                                         byteorder='little', signed=False))

        # act
        p = Packet(bytes(mutable_bytes))

        # assert (default values)
        self.assertEqual(p.hw_event, hw)
        self.assertEqual(p.target, ta)
        self.assertEqual(p.error, er)
        self.assertEqual(p.val, va)

    def test_3ParamsConstructor(self):
        # arrange
        event = HWEvent.BLINK
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
        self.assertEqual(b[0], 9)
        self.assertEqual(b[1], 42)
        self.assertEqual(int.from_bytes(b[-2:], byteorder='little'), 1000)

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


if __name__ == '__main__':
    unittest.main()
