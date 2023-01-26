#!/usr/bin/env python


from dataclasses import dataclass, field
from typing import List
from daemon.packet import PwmBoard, Packet, HWEvent

NoLed: int = 0
swOff: bool = False
swOn: bool = True
PwmMax: int = 4094


@dataclass
class Hwctrl:
    pin: int = 0
    state: bool = swOff
    ledboard: PwmBoard = PwmBoard.NONE_
    ledPin: int = NoLed
    ledState: int = swOff
    ledonVal: int = 1
    ledOffVal: int = 0

    def __eq__(self, other):
        if isinstance(other, Hwctrl):
            return self.pin == other.pin
        return False

    def set_state(self, new_state: bool) -> List:
        '''Set state and returns a packet to turn on ctrl.ledpin'''
        self.state = bool(new_state)
        val = self.ledonVal if self.state else self.ledOffVal
        if self.ledboard != PwmBoard.NONE_ and self.ledPin != NoLed:
            self.ledState = self.state
            return [Packet(self.ledboard, self.ledPin, val),]
        elif self.ledPin != NoLed:
            self.ledState = self.state
            return [Packet(HWEvent.SWITCH, self.ledPin, val),]
        return []


@dataclass
class Analogctrl(Hwctrl):
    state: int = 0

    def __eq__(self, other):
        if isinstance(other, Analogctrl):
            return self.pin == other.pin
        return False

    def set_state(self, new_state: int) -> List:
        '''Set state and returns a packet to turn on ctrl.ledpin'''
        self.state = new_state
        val = self.ledonVal if self.state else self.ledOffVal
        if self.ledboard != PwmBoard.NONE_ and self.ledPin != NoLed:
            self.ledState = bool(self.state)
            return [Packet(self.ledboard, self.ledPin, val),]
        elif self.ledPin != NoLed:
            self.ledState = bool(self.state)
            return [Packet(HWEvent.SWITCH, self.ledPin, val),]
        return []


@dataclass
class Aux(Hwctrl):
    slave_pin: int = 0
    slave_state: bool = swOff
    slave_ledboard: int = PwmBoard.NONE_
    slave_ledPin: int = NoLed
    slave_ledOnVal: int = 1
    slave_ledOffVal: int = 0

    def __eq__(self, other):
        if isinstance(other, Hwctrl):
            return self.pin == other.pin
        return False

    def set_Slstate(self, new_state: bool) -> list:
        '''Set Slave state and returns a packet to turn on ctrl.slave_ledPin'''
        self.slave_state = new_state
        val = self.slave_ledOnVal if self.slave_state else self.slave_ledOffVal
        if self.slave_ledboard != PwmBoard.NONE_ and self.slave_ledPin != NoLed:
            return [Packet(self.slave_ledboard, self.slave_ledPin, val),]
        elif self.slave_ledPin != NoLed:
            return [Packet(HWEvent.SWITCH, self.slave_ledPin, val),]
        return []


class AuxCtrls:
    ctrls: list
    def __init__(self):
        # key = pin
        self.ctrls = []
        self.reset()

    def get_auxctrl(self, pin) -> Aux:
        for ctrl in self.ctrls:
            if ctrl.pin == pin:
                return ctrl
        raise Exception("No Ctrl found with pin={pin}")

    def get_slavectrl(self, pin) -> Aux:
        for ctrl in self.ctrls:
            if ctrl.slave_pin == pin:
                return ctrl
        raise Exception("No Slave Ctrl found with pin={pin}")

    def reset(self):
        '''Reset all controls to their initial state'''
        self.ctrls.clear()
        self.ctrls.append(Aux(pin=38, slave_pin=28,slave_ledOnVal=PwmMax,
            slave_ledPin= 9, slave_ledboard=PwmBoard.I2CCLED))
        self.ctrls.append(Aux(pin=39, slave_pin=29,slave_ledOnVal=PwmMax,
            slave_ledPin=10, slave_ledboard=PwmBoard.I2CCLED))
        self.ctrls.append(Aux(pin=40, slave_pin=30,slave_ledOnVal=PwmMax,
            slave_ledPin=11, slave_ledboard=PwmBoard.I2CCLED))
        self.ctrls.append(Aux(pin=41, slave_pin=31,slave_ledOnVal=PwmMax,
            slave_ledPin=12, slave_ledboard=PwmBoard.I2CCLED))