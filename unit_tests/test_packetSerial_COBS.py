#!/usr/bin/env python


from daemon.packet_serial import PacketSerial
from daemon.packet import Packet, HWEvent, ErrorType   # noqa
import unittest   # noqa

class Test_COBS(unittest.TestCase):
    def test_Encode(self):
        # arrange
        expected = b'\x03\t!\x02,\x01'
        p = Packet(HWEvent.HELLO, 33, 44)

        # act
        actual = PacketSerial.encode_packet(p)

        # assert (default values)
        self.assertEqual(actual, expected)

    def test_Decode(self):
        # arrange
        expected = Packet(HWEvent.HELLO, 33, 44)

        # act
        actual = PacketSerial.decode_packet( b'\x03\t!\x02,\x01\x00')

        # assert (default values)
        self.assertEqual(expected.hw_event, actual.hw_event)
        self.assertEqual(expected.target, actual.target)
        self.assertEqual(expected.error, actual.error)
        self.assertEqual(expected.val, actual.val)


if __name__ == '__main__':
    unittest.main()
 