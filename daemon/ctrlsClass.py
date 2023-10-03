#!/usr/bin/env python


from dataclasses import dataclass, field
from typing import List

from daemon.packet import HWEvent, Packet, PwmBoard

NO_LED: int = -1
SWITCH_OFF: bool = False
SWITCH_ON: bool = True
PWM_MAX: int = 4094


@dataclass
class Hwctrl:
    '''
    :param section: Group ctrls together with the same section
    :param pin: The Arduino.MEGA PinNr. Use '-1' if N.A.
    :param state: current state of switch
    :param name: Human friendly name of Ctrl
    :param ledboard: If the LedPin refers to a pin on PwmBoard, specify that here
    :param ledPin: The PinNr of the LED. Can be both on Arduino.Mega and PwmBoard
    :param ledState: current state of LED
    :param ledonVal: The Value to send as 'ON'
    :param ledOffVal: The Value to send as 'OFF'
    :param ledFollowState: If Ctrl.State changes, should LED.State also change
    :param ledFollowInvert: requires ledFollowState. Inverts the state of Led compared to Ctrl.State
    :param slaves: Ctrls that is logically bound to this ctrl
    '''
    section: str
    pin: int = 0
    state: bool = SWITCH_OFF
    name: str = ""
    ledboard: PwmBoard = PwmBoard.NONE_
    ledPin: int = NO_LED
    ledState: int = SWITCH_OFF
    ledonVal: int = 1
    ledOffVal: int = 0
    ledFollowState: bool = True
    ledFollowInvert: bool = False
    slaves: List = field(default_factory=list)  # List[Hwctrl]

    def __eq__(self, other):
        if isinstance(other, Hwctrl):
            return self.pin == other.pin
        return False

    def set_state(self, new_state: bool) -> List[Packet]:
        '''Set state and returns a packet to turn on ctrl.ledpin'''
        self.state = bool(new_state)
        return [] if not self.ledFollowState else self.set_led_state(self.state, self.ledFollowInvert)

    def set_led_state(self, new_state: bool, invert: bool = False) -> List[Packet]:
        '''Uses ledonVal and ledOffVal to set LED value'''
        val = self.ledonVal if new_state else self.ledOffVal
        if invert: val = self._invert_int(val, self.ledOffVal, self.ledOffVal)
        if self.ledboard != PwmBoard.NONE_ and self.ledPin != NO_LED:
            self.ledState = self.state
            return [Packet(self.ledboard, self.ledPin, val)]
        elif self.ledPin != NO_LED:
            self.ledState = self.state
            return [Packet(HWEvent.LED, self.ledPin, val)]
        return []

    def _invert_int(val: int, start: int, end: int) -> int:
        # is range inverted=
        negstep = start > end

        # clamp value within valid range
        actualMin = end if negstep else start
        actualMax = start if negstep else end
        cVal = max(min(actualMax, val), actualMin)

        newVal = (actualMax - cVal) + start
        return newVal


@dataclass
class Analogctrl(Hwctrl):
    state: int = 0

    def __eq__(self, other):
        if isinstance(other, Analogctrl):
            return self.pin == other.pin
        return False

    def set_state(self, new_state: int) -> List[Packet]:
        '''Set state and returns a packet to turn on ctrl.ledpin'''
        self.state = new_state
        return [] if not self.ledFollowState else self.set_led_state(self.state)



class HwCtrls:
    ctrls: List[Hwctrl]
    def __init__(self):
        # key = pin
        self.ctrls: List[Hwctrl] = []
        self.reset()

    def get_ctrl(self, pin: int) -> Hwctrl:
        """
        Searches top level controls for a matching Pin

        :returns: Ctrl.  'None' if not found
        :raises Exception: raises an exception when no ctrl found
        """
        for ctrl in self.ctrls:
            if ctrl.pin == pin:
                return ctrl
        raise Exception("No top-level Ctrl found with pin={}".format(pin))

    def __get_slavectrl(ctrl: Hwctrl, pin: int) -> Hwctrl:
        if ctrl.pin == pin:
            return ctrl
        for slave in ctrl.slaves:
            if slave.pin == pin:
                return slave
            else:
                r = HwCtrls.__get_slavectrl(slave, pin)
                if r is not None:
                    return r
        return None

    def get_slavectrl(self, pin: int) -> Hwctrl:
        """
        Searches through all controls (including)
        slave controls for a matching Pin

        :returns: Ctrl.
        :raises Exception: raises an exception when no ctrl found
        """
        for ctrl in self.ctrls:
            foundCtrl = HwCtrls.__get_slavectrl(ctrl, pin)
            if foundCtrl is not None: return foundCtrl
        raise Exception("No Ctrl (searching all) found with pin={}".format(pin))

    def reset(self):
        '''Reset all controls to their initial state'''
        self.ctrls.clear()
        self.__load_ctrls()


    def __set_allLeds(pctrl: Hwctrl, state: bool, section = None) -> List[Packet]:
        ps: List[Packet] = []
        if section is None or pctrl.section == section:
            ps.extend(pctrl.set_led_state(state))
        for slave in pctrl.slaves:
            ps.extend(HwCtrls.__set_allLeds(slave, state, section))
        return ps

    def set_allLeds(self, state: bool, section = None) -> List[Packet]:
        """
        Turns all LEDs On/Off for a specific section.
        Use :param section=None to set ALL LEDs

        :param state: turn LEDs On or Off
        :param section: Name of section. Use None to target all Ctrls
        :returns: List[Packet] commands for LEDs
        """
        ps: List[Packet] = []
        for ctrl in self.ctrls:
            ps.extend(HwCtrls.__set_allLeds(ctrl, state))
        return ps

    def __get_allCtrls_flat(pctrl: Hwctrl, section) -> List[Hwctrl]:
        cs: List[Hwctrl] = []
        if section is None or pctrl.section == section:
            cs.append(pctrl)
        for slave in pctrl.slaves:
            cs.extend(HwCtrls.__get_allCtrls_flat(slave, section))
        return cs

    def _getAllCtrls_flat(self, section = None) -> List[Hwctrl]:
        cs: List[Hwctrl] = []
        for ctrl in self.ctrls:
            cs.extend(HwCtrls.__get_allCtrls_flat(ctrl, section))
        return cs

    def __load_ctrls(self):
        # MASTER
        self.ctrls.append(Hwctrl(pin=12, name="masterSw", section="master"))
        ma_a = Hwctrl(pin=14, name="BacklightSw", section="master")
        ma_a.slaves.append(Hwctrl(pin=-1, name="BacklightIndictr", 
            ledPin=13,section="master", ledboard=PwmBoard.I2CCLED, ledonVal=PWM_MAX))
        ma_a.slaves.append(Hwctrl(pin=43, name="BacklightRelay", section="master"))
        ma_b = Hwctrl(pin=15, name="InputsSw", section="master")
        ma_b.slaves.append(Hwctrl(pin=-1, name="InputsIndictr", 
            ledPin=14,section="master", ledboard=PwmBoard.I2CCLED, ledonVal=PWM_MAX))
        ma_c = Hwctrl(pin=16, name="SoundSw", section="master")
        ma_c.slaves.append(Hwctrl(pin=-1, name="SoundIndictr", 
            ledPin=15,section="master", ledboard=PwmBoard.I2CCLED, ledonVal=PWM_MAX))
        self.ctrls.extend([ma_a, ma_b, ma_c])

        # Subspace Sat Comm
        for i in range(0,6):  # not including 6
            su1 = Hwctrl(pin=-1, section="subspace", ledPin=i+10, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CALED)
            su1.slaves.append(Hwctrl(pin=i+2, ledPin=i, ledonVal=PWM_MAX, section="subspace", ledboard=PwmBoard.I2CALED))
            self.ctrls.append(su1)
        for i in range(0,4):  # not including 4
            su2 = Hwctrl(pin=-1, section="subspace", ledPin=i, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CBLED)
            su2.slaves.append(Hwctrl(pin=i+8, ledPin=i+6, ledonVal=PWM_MAX, section="subspace", ledboard=PwmBoard.I2CALED))
            self.ctrls.append(su2)

        # Waveform Collider
        for i in range(0,8):  # not including 8
            self.ctrls.append(Hwctrl(pin=i+17, ledPin=i+4, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CBLED, section="waveform"))
        self.ctrls.append(Hwctrl(pin=-1, ledPin=12, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CBLED, section="waveform"))
        self.ctrls.append(Hwctrl(pin=-1, ledPin=13, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CBLED, section="waveform"))
        self.ctrls.append(Hwctrl(pin=-1, ledPin=14, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CBLED, section="waveform"))
        self.ctrls.append(Hwctrl(pin=-1, ledPin=15, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CBLED, section="waveform"))
        self.ctrls.append(Analogctrl(pin=109, section="waveform"))  # Volume ctrl
        self.ctrls.append(Hwctrl(pin=27, ledPin=0, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CCLED, section="waveform"))


        # AUX
        aa = Hwctrl(pin=38, section="aux")
        aa.slaves.append(Hwctrl(pin=28,ledPin=9,section="aux", ledboard=PwmBoard.I2CCLED, ledonVal=PWM_MAX))
        ab = Hwctrl(pin=39, section="aux")
        ab.slaves.append(Hwctrl(pin=29,ledPin=10,section="aux", ledboard=PwmBoard.I2CCLED, ledonVal=PWM_MAX))
        ac = Hwctrl(pin=40, section="aux")
        ac.slaves.append(Hwctrl(pin=30,ledPin=11,section="aux", ledboard=PwmBoard.I2CCLED, ledonVal=PWM_MAX))
        ad = Hwctrl(pin=41, section="aux")
        ad.slaves.append(Hwctrl(pin=31,ledPin=12,section="aux", ledboard=PwmBoard.I2CCLED, ledonVal=PWM_MAX))
        self.ctrls.extend([aa,ab,ac,ad])

        # LED STRIP 1  (LEFT)
        ls_a = Hwctrl(pin=35, ledPin=1, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CCLED, section="ledstripL")
        ls_a.slaves.append(Hwctrl(pin=-1, ledPin=4, ledboard=PwmBoard.I2CCLED, section="ledstripL"))
        self.ctrls.append(ls_a)
        self.ctrls.append(Hwctrl(pin=36, ledPin=2, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CCLED, section="ledstripL"))
        self.ctrls.append(Hwctrl(pin=37, ledPin=3, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CCLED, section="ledstripL"))
        self.ctrls.append(Analogctrl(pin=101, section="ledstripL"))  # Intensity
        self.ctrls.append(Analogctrl(pin=102, section="ledstripL"))  # Red
        self.ctrls.append(Analogctrl(pin=103, section="ledstripL"))  # Green
        self.ctrls.append(Analogctrl(pin=104, section="ledstripL"))  # Blue

        # LED STRIP 2  (RIGHT)
        ls_b = Hwctrl(pin=32, ledPin=5, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CCLED, section="ledstripR")
        ls_b.slaves.append(Hwctrl(pin=-1, ledPin=8, ledboard=PwmBoard.I2CCLED, section="ledstripR"))
        self.ctrls.append(ls_b)
        self.ctrls.append(Hwctrl(pin=33, ledPin=6, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CCLED, section="ledstripR"))
        self.ctrls.append(Hwctrl(pin=34, ledPin=7, ledonVal=PWM_MAX, ledboard=PwmBoard.I2CCLED, section="ledstripR"))
        self.ctrls.append(Analogctrl(pin=105, section="ledstripR"))  # Intensity
        self.ctrls.append(Analogctrl(pin=106, section="ledstripR"))  # Red
        self.ctrls.append(Analogctrl(pin=107, section="ledstripR"))  # Green
        self.ctrls.append(Analogctrl(pin=108, section="ledstripR"))  # Blue