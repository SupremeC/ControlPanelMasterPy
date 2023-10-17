"""Packet is the class used to send and receive data from Arduino
"""


from datetime import datetime
import logging
from dataclasses import dataclass
from enum import IntEnum  # , verify, UNIQUE

logger = logging.getLogger("daemon.PacketSerial.Packet")


# @verify(UNIQUE)
class HWEvent(IntEnum):
    """HWEvent"""

    UNDEFINED = (0,)
    LED = 1
    I2CALED = 2
    I2CBLED = 3
    I2CCLED = 4
    SWITCH = 5
    DEMO = 6
    BLINK = 7
    STATUS = 8
    """ Status report of a ctrl/led/relay. Does this hold up? """
    HELLO = 9
    RESET = 10
    """ When sent: Ask Mega to do Reboot """
    BOOTMEGA = 11
    """ A package with this Event is sent when Mega starts up. """


# @verify(UNIQUE)
class ErrorType(IntEnum):
    """Packet Error enum"""

    NONE_ = 0
    UNKNOWNEVENT = 1
    LEDINVALIDVALUE = 2
    INVALIDTARGET = 3
    INVALIDPWMBOARD = 4
    INVALIDBLINKTARGET = 5
    INVALIDBLINKVALUE = 6
    FAILEDTOPARSEPACKET = 7
    OTHER_ = 254


# @verify(UNIQUE)
class BlinkTarget(IntEnum):
    """Special Target. Affects multiple LEDs"""

    AUDIO_PRESETBTNS = 200
    SPEAKER_LEDS = 201


class PwmBoard(IntEnum):
    """PwmBoard"""

    NONE_ = 0
    I2CALED = HWEvent.I2CALED
    I2CBLED = HWEvent.I2CBLED
    I2CCLED = HWEvent.I2CCLED


@dataclass
class Packet:
    """
    Packet class. Supported struct to comunicate with Arduino over Serial

    Args:
        0 args: Init Packet with default values
            hw_event = HWEvent.UNDEFINED
            target = 0
            error = ErrorType.NONE_
            val = 0
        1 args:
            bytes. The bytes are parsed into Packet values
        3 args:
            *1st: hw_event
            *2nd: target
            *3rd: value
    """

    created: datetime
    hw_event: HWEvent = HWEvent.UNDEFINED
    target: int = 0
    error: ErrorType = ErrorType.NONE_
    val: int = 0

    def __init__(self, *args):
        self.created = datetime.now()
        if len(args) == 0:
            return
        if len(args) == 1:
            self.parse_bytes(args[0])
            return
        if len(args) == 3:
            self.hw_event = args[0]
            self.target = args[1]
            self.val = args[2]

    def parse_bytes(self, byte_arr: bytes) -> None:
        """Parse bytes into packet values"""
        try:
            self.hw_event = HWEvent(byte_arr[0])
            self.target = byte_arr[1]
            self.error = ErrorType(byte_arr[2])
            self.val = int.from_bytes(byte_arr[-2:], byteorder="little", signed=False)
        except IndexError as e:
            logger.error(e)
            self.error = ErrorType.FAILEDTOPARSEPACKET
            self.hw_event = HWEvent.UNDEFINED
            self.target = 0
            self.val = 0

    def as_bytes(self) -> bytes:
        """return Packet converted to bytes"""
        ba = bytearray()
        ba.extend(
            int(self.hw_event).to_bytes(length=1, byteorder="little", signed=False)
        )
        ba.extend(self.target.to_bytes(length=1, byteorder="little", signed=False))
        ba.extend(int(self.error).to_bytes(length=1, byteorder="little", signed=False))
        ba.extend(self.val.to_bytes(length=2, byteorder="little", signed=False))
        return bytes(ba)

    def as_human_friendly_str(self) -> str:
        """Packet as a human-friendly readable string"""
        r = self.created.strftime("%H:%M:%S") + "   "
        r += self.hw_event.name.ljust(9, " ") + "_"
        r += f"t={str(self.target).ljust(3, ' ')}_v={self.val}"
        if self.error is not None and self.error != ErrorType.NONE_:
            r += f"  error={self.error.name}"
        return r

    @staticmethod
    def packet_class_to_dict(obj):
        """Pyro: Serialization of Packet class"""
        return {
            "__class__": "pyro-custom-Packet",
            "target-attr": obj.target,
            "val-attr": obj.val,
            "created-attr": obj.created.isoformat(),
            "error-attr": obj.error,
            "hw_event-attr": obj.hw_event,
        }

    @staticmethod
    def packet_dict_to_class(_classname, d):
        """Pyro: Deserialization of Packet class"""
        o = Packet()
        o.target = d["target-attr"]
        o.val = d["val-attr"]
        o.created = datetime.fromisoformat(d["created-attr"])
        o.error = ErrorType(d["error-attr"])
        o.hw_event = HWEvent(d["hw_event-attr"])
        return o
