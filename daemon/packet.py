#!/usr/bin/env python

import logging
from dataclasses import dataclass, field
from enum import IntEnum  # , verify, UNIQUE

logger = logging.getLogger('daemon.PacketSerial.Packet')

# @verify(UNIQUE)
class HWEvent  (IntEnum):
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


# @verify(UNIQUE)
class ErrorType (IntEnum):
    NONE_ = 0,
    UNKNOWNEVENT = 1
    LEDINVALIDVALUE = 2
    INVALIDTARGET = 3
    INVALIDPWMBOARD = 4
    INVALIDBLINKTARGET = 5
    INVALIDBLINKVALUE = 6
    FAILEDTOPARSEPACKET = 7
    OTHER_ = 254


# @verify(UNIQUE)
class BlinkTarget (IntEnum):
    AUDIO_PRESETBTNS = 200
    SPEAKER_LEDS = 201


class PwmBoard (IntEnum):
    NONE_ = 0,
    I2CALED = HWEvent.I2CALED
    I2CBLED = HWEvent.I2CBLED
    I2CCLED = HWEvent.I2CCLED


@dataclass
class Packet:
    hwEvent: HWEvent = HWEvent.UNDEFINED
    target: int = 0
    error: ErrorType = ErrorType.NONE_
    val: int = 0

    def __init__(self, *args):
        if len(args) == 0:
            return
        if len(args) == 1:
            self.parse_bytes(args[0])
            return
        if len(args) == 3:
            self.hwEvent = args[0]
            self.target = args[1]
            self.val = args[2]

    def parse_bytes(self, bytes: bytes) -> None:
        """ Parse bytes into packet values"""
        try:
            self.hwEvent = HWEvent(bytes[0])
            self.target = bytes[1]
            self.error = ErrorType(bytes[2])
            self.val = int.from_bytes(bytes[-2:],
                                      byteorder='little', signed=False)
        except Exception as e:
            logger.error(e)
            self.error = ErrorType.FAILEDTOPARSEPACKET
            self.hwEvent = HWEvent.UNDEFINED
            self.target = 0
            self.val = 0

    def as_bytes(self) -> bytes:
        ba = bytearray()
        ba.extend(int(self.hwEvent).to_bytes(
            length=1, byteorder='little', signed=False))
        ba.extend(self.target.to_bytes(
            length=1, byteorder='little', signed=False))
        ba.extend(int(self.error).to_bytes(
            length=1, byteorder='little', signed=False))
        ba.extend(self.val.to_bytes(
            length=2, byteorder='little', signed=False))
        return bytes(ba)

'''
    def __str__(self):
        format("HWEvent: %s(%d)" /
               "Target: %s" /
               "Error: %s(%d)" /
               "Val: %s",
               self.hwEvent.name, self.hwEvent.value,
               self.target,
               self.error.name, self.error.value,
               self.val)
'''


