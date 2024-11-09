"""
Ctrls Class
=================================

- Contains classes for hardware controls
- function __load_ctrls contains all hw definitions

"""

import datetime
from dataclasses import dataclass, field
import logging
from typing import List, Optional
from daemon.packet import HWEvent, Packet, PwmBoard

NO_LED: int = -1
NO_PIN: int = -1
SWITCH_OFF: bool = False
SWITCH_ON: bool = True
PWM_MAX: int = 4094
PWM_MED: int = 2000
PWM_LOW: int = 800
DEFAULT_PWM: int = PWM_LOW
LED_ON: bool = True
LED_OFF: bool = False


logger = logging.getLogger("daemon.HwCtrl")


@dataclass
class LEDCtrl:
    """Represents a single, dumb, LED

    :param ledboard: If the LedPin refers to a pin on PwmBoard, specify that here
    :param led_pin: The PinNr of the LED. Can be both on Arduino.Mega and PwmBoard
    :param led_state: current state of LED
    :param led_on_val: The Value to send as 'ON'
    :param led_off_val: The Value to send as 'OFF'
    :param led_is_indicator: If Ctrl.State changes, should LED.State also change
    :param led_follow_invert: requires led_is_indicator.
        Inverts the state of Led compared to Ctrl.State"""

    ledboard: PwmBoard = PwmBoard.NONE_
    pin: int = NO_LED
    state: int = LED_OFF
    on_value: int = 1
    max_value: int = 1
    is_indicator: bool = False
    follow_invert: bool = False

    def set_led_state(self, new_state: bool, new_value: int = None) -> Packet:
        """Uses ledonVal and ledOffVal to set LED value unless value
        is provided"""
        value = self.on_value if new_state else 0
        value = new_value if new_value is not None else value
        value = self.clamp(value, 0, self.on_value)
        if self.follow_invert:
            value = self._invert_int(value, 0, self.on_value)
        if self.ledboard != PwmBoard.NONE_ and self.pin != NO_LED:
            self.state = new_state
            return Packet(self.ledboard, self.pin, value)
        if self.pin != NO_LED:
            self.state = new_state
            return Packet(HWEvent.LED, self.pin, value)
        raise LEDException(
            "Could not change state of LED because no PIN was configured"
        )

    def blink(self, endHigh: bool = True, forever: bool = False) -> List[Packet]:
        if self.ledboard == PwmBoard.NONE_:
            return
        p = self.pin
        if self.ledboard == PwmBoard.I2CBLED:
            p = 20 + self.pin
        if self.ledboard == PwmBoard.I2CCLED:
            p = 40 + self.pin
        if forever:
            e = HWEvent.BLINKFOREVER
        else:
            e = HWEvent.BLINK3ENDHIGH if endHigh else HWEvent.BLINK3ENDLOW
            if e == HWEvent.BLINK3ENDHIGH:
                self.set_led_state(800)
        return [Packet(e, p, 2)]

    def blink_stop(self) -> None:
        if self.ledboard == PwmBoard.NONE_:
            return
        p = 20 + self.pin if self.ledboard == PwmBoard.I2CBLED else 40 + self.pin
        self.set_led_state(0)
        return [Packet(HWEvent.BLINKFOREVER, p, 0)]

    @staticmethod
    def clamp(val: int, minval: int, maxval: int) -> int:
        """Clamps input into the range [ minval, maxval ].

        Args:
            val (int): The input
            minval (int):  lower-bound of the range to be clamped to
            maxval (int): upper-bound of the range to be clamped to

        Returns:
            int: result of clamp op.
        """
        if val < minval:
            return minval
        if val > maxval:
            return maxval
        return val

    @staticmethod
    def _invert_int(val: int, start: int, end: int) -> int:
        # is range inverted=
        negstep = start > end

        # clamp value within valid range
        actual_min = end if negstep else start
        actual_max = start if negstep else end
        cval = max(min(actual_max, val), actual_min)

        new_val = (actual_max - cval) + start
        return new_val


@dataclass
class Hwctrl:
    """
    :param section: Group ctrls together with the same section
    :param pin: The Arduino.MEGA PinNr. Use '-1' if N.A.
    :param state: current state of switch
    :param name: Human friendly name of Ctrl
    :param leds (optional): LEDs that is logically bound to this ctrl
    :param slaves (optional): Ctrls that is logically bound to this ctrl
    """

    section: str
    pin: int = 0
    state: bool = SWITCH_OFF
    name: str = ""
    state_change_date: datetime = datetime.datetime.now()
    quick_state_change: bool = False
    leds: Optional[List[LEDCtrl]] = field(default_factory=list)
    slaves: Optional[List] = field(default_factory=list)  # List[Hwctrl]
    follow_parent: bool = False
    hw_type: HWEvent = HWEvent.UNDEFINED
    invert: bool = False

    def __eq__(self, other):
        if isinstance(other, Hwctrl):
            return self.pin == other.pin
        return False

    def add_slave(self, slave: any) -> None:
        """Add a Slave to this Ctrl"""
        slave.parent = self
        self.slaves.append(slave)

    def set_state(self, new_state: bool, report: bool = False) -> List[Packet]:
        """Set state and optionally returns a packet to turn on related LEDs
        and slave ctrls"""
        new_state = not new_state if self.invert else new_state
        self.state = bool(new_state)
        self.quick_state_change = (
            datetime.datetime.now() - self.state_change_date
        ).total_seconds() < 1
        self.state_change_date = datetime.datetime.now()
        packets = self.set_state_of_leds(new_state, True)
        if report:
            packets.append(Packet(self.hw_type, self.pin, self.state))
        for slave in self.slaves:
            if not slave.follow_parent:
                continue
            packets.extend(slave.set_state(new_state, True))
        return packets

    def set_state_of_leds(
        self,
        new_state: bool,
        onlyindicators: bool = False,
    ) -> List[Packet]:
        """Turn related LEDs on/off

        Args:
            new_state (bool): ON / OFF
            onlyfollow (bool, optional): Only set state for those LEDs that
                are configured to follow state of this ctrl. Defaults to False.

        Returns:
            List[Packet]: Packets to instruct Arduino to turn LEDs on/off
        """
        react_packets = []
        for led in self.leds:
            if led.is_indicator or not onlyindicators:
                react_packets.append(led.set_led_state(new_state))
        return react_packets


@dataclass
class Analogctrl(Hwctrl):
    """Overrides HwCtrl. Allows <state> to accept
    values up to 65534"""

    state: int = 0

    def __eq__(self, other):
        if isinstance(other, Analogctrl):
            return self.pin == other.pin
        return False

    def set_state(self, new_state: int) -> List[Packet]:
        """Set state and returns a packet to turn on ctrl.ledpin"""
        if new_state >= 65534:
            raise ValueError("State can not be greater than 65534")
        if new_state < 0:
            raise ValueError("State can not be lower then 0 (zero)")
        self.state = new_state
        # we consider anything above 0 as ON-state.
        # Might have to reconsider this
        return self.set_state_of_leds(bool(new_state), True)


class HwCtrls:
    """HwCtrls"""

    ctrls: List[Hwctrl]

    def __init__(self):
        # key = pin
        self.ctrls: List[Hwctrl] = []
        self.reset()

    def set_all_nonindicatorleds(self, new_state: bool) -> List[Packet]:
        """Set all non-indicator LEDS ON or OFF"""
        ps: List[Packet] = []
        for ctrl in self.ctrls:
            for led in ctrl.leds:
                if not led.is_indicator:
                    ps.append(led.set_led_state(new_state))
            for slavectrl in ctrl.slaves:
                for led in slavectrl.leds:
                    if not led.is_indicator:
                        ps.append(led.set_led_state(new_state))
        return ps

    def get_ctrl(self, pin: int) -> Hwctrl:
        """
        Searches top level controls for a matching Pin

        :returns: Ctrl.
        :raises Exception: CtrlNotFoundException when no ctrl found
        """
        for ctrl in self.ctrls:
            if ctrl.pin == pin:
                return ctrl
        raise CtrlNotFoundException(pin, f"No top-level Ctrl found with pin={pin}")

    def get_ctrl_by_name(self, name: str) -> Hwctrl:
        """
        Searches all controls for a matching Name

        :returns: Ctrl.
        :raises Exception: CtrlNotFoundException when no ctrl found
        """
        pin_that_does_not_exist = -666
        found_ctrl = self.get_slavectrl(pin_that_does_not_exist, name)
        if found_ctrl is not None:
            return found_ctrl
        raise CtrlNotFoundException(
            -1, f"No Ctrl (searching all) found with name={name}"
        )

    def get_slavectrl(self, pin: int, name: str = None) -> Hwctrl:
        """
        Searches through all controls (including)
        slave controls for a matching Pin or name

        :returns: Ctrl.
        :raises Exception: CtrlNotFoundException when no ctrl found
        """
        for ctrl in self.ctrls:
            found_ctrl = HwCtrls.__get_slavectrl(ctrl, pin, name)
            if found_ctrl is not None:
                return found_ctrl
        raise CtrlNotFoundException(
            pin, f"No Ctrl (searching all) found with pin={pin}"
        )

    @staticmethod
    def __get_slavectrl(ctrl: Hwctrl, pin: int, name: str = None) -> Hwctrl:
        if ctrl.pin == pin:
            return ctrl
        if name is not None and ctrl.name == name:
            return ctrl
        for slave in ctrl.slaves:
            if slave.pin == pin:
                return slave
            if name is not None and slave.name == name:
                return slave
            r = HwCtrls.__get_slavectrl(slave, pin)
            if r is not None:
                return r
        return None

    def _get_all_leds(self) -> list:
        leds = []
        for ctrl in self.ctrls:
            leds.extend(ctrl.leds)
            for child in ctrl.slaves:
                leds.extend(child.leds)
        return leds

    def reset(self):
        """Reset all controls to their initial state"""
        self.ctrls.clear()
        self.__load_ctrls()

    @staticmethod
    def __set_all_leds(pctrl: Hwctrl, state: bool, section=None) -> List[Packet]:
        ps: List[Packet] = []
        if section is None or pctrl.section == section:
            ps.extend(pctrl.set_state_of_leds(state))
        for slave in pctrl.slaves:
            ps.extend(HwCtrls.__set_all_leds(slave, state, section))
        return ps

    def set_all_leds(self, state: bool, section=None) -> List[Packet]:
        """
        Turns all LEDs On/Off for a specific section.
        Use :param section=None to set ALL LEDs

        :param state: turn LEDs On or Off
        :param section: Name of section. Use None to target all Ctrls
        :returns: List[Packet] commands for LEDs
        """
        ps: List[Packet] = []
        for ctrl in self.ctrls:
            ps.extend(HwCtrls.__set_all_leds(ctrl, state, section))
        return ps

    @staticmethod
    def __get_all_ctrls_flat(pctrl: Hwctrl, section) -> List[Hwctrl]:
        cs: List[Hwctrl] = []
        if section is None or pctrl.section == section:
            cs.append(pctrl)
        for slave in pctrl.slaves:
            cs.extend(HwCtrls.__get_all_ctrls_flat(slave, section))
        return cs

    def _get_all_ctrls_flat(self, section=None) -> List[Hwctrl]:
        cs: List[Hwctrl] = []
        for ctrl in self.ctrls:
            cs.extend(HwCtrls.__get_all_ctrls_flat(ctrl, section))
        return cs

    def __load_ctrls(self):
        self._list_master_controls()
        self._list_subspacesat_controls()
        self._list_waveformcollider_controls()
        self._list_aux_controls()
        self._list_ledstripWindow_controls()
        self._list_ledstripr_controls()

    def _list_ledstripr_controls(self):
        lsr_pwr = Hwctrl(pin=32, section="ledstripR", name="RightLedStripPowerBtn")
        lsr_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=5,
                on_value=DEFAULT_PWM,
                is_indicator=False,
            )
        )
        lsr_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=8,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        lsr_preveffect = Hwctrl(
            pin=34, section="ledstripR", name="RightLedStripPreEffectBtn"
        )
        lsr_preveffect.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=6,
                on_value=DEFAULT_PWM,
                is_indicator=False,
            )
        )
        lsr_nexteffect = Hwctrl(
            pin=33, section="ledstripR", name="RightLedStripNextEffectBtn"
        )
        lsr_nexteffect.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=7,
                on_value=DEFAULT_PWM,
                is_indicator=False,
            )
        )
        r_int = Analogctrl(pin=58, section="ledstripR", name="R Intensity")
        r_int.set_state(125)
        r_red = Analogctrl(pin=59, section="ledstripR", name="R Red")
        r_red.set_state(125)
        r_green = Analogctrl(pin=60, section="ledstripR", name="R Green")
        r_green.set_state(125)
        r_blue = Analogctrl(pin=61, section="ledstripR", name="R Blue")
        r_blue.set_state(125)
        self.ctrls.extend(
            [lsr_pwr, lsr_preveffect, lsr_nexteffect, r_int, r_red, r_green, r_blue]
        )

    def _list_ledstripWindow_controls(self):
        lsl_pwr = Hwctrl(pin=35, section="ledstripL", name="LeftLedStripPowerBtn")
        lsl_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=1,
                on_value=DEFAULT_PWM,
                is_indicator=False,
            )
        )
        lsl_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=4,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        lsl_preveffect = Hwctrl(
            pin=36, section="ledstripL", name="LeftLedStripPreEffectBtn"
        )
        lsl_preveffect.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=2,
                on_value=DEFAULT_PWM,
                is_indicator=False,
            )
        )
        lsl_nexteffect = Hwctrl(
            pin=37, section="ledstripL", name="LeftLedStripNextEffectBtn"
        )
        lsl_nexteffect.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=3,
                on_value=DEFAULT_PWM,
                is_indicator=False,
            )
        )
        l_int = Analogctrl(pin=55, section="ledstripL", name="L Intensity")
        l_int.set_state(125)
        l_red = Analogctrl(pin=54, section="ledstripL", name="L Red")
        l_red.set_state(125)
        l_green = Analogctrl(pin=56, section="ledstripL", name="L Green")
        l_green.set_state(125)
        l_blue = Analogctrl(pin=57, section="ledstripL", name="L Blue")
        l_blue.set_state(125)
        self.ctrls.extend(
            [lsl_pwr, lsl_preveffect, lsl_nexteffect, l_int, l_red, l_green, l_blue]
        )

    def _list_aux_controls(self):
        # #################### BED LAMP ############################
        aux_bedlampFlip = Hwctrl(pin=38, section="aux", name="auxFlipBedlamp")
        aux_bedlampFlip.leds.append(
            LEDCtrl(ledboard=PwmBoard.NONE_, pin=50, on_value=1)
        )
        aux_bedlampBtn = Hwctrl(pin=67, section="aux", name="auxflipBedlampBtn")
        aux_bedlampBtn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=12, on_value=DEFAULT_PWM)
        )
        aux_bedlampBtn.add_slave(
            Hwctrl(
                pin=45,
                hw_type=HWEvent.RELAY,
                invert=True,
                section="relay",
                follow_parent=True,
            )
        )
        aux_bedlampFlip.add_slave(aux_bedlampBtn)

        # ###################### BED SOCKET ########################
        aux_bedSocketFlip = Hwctrl(pin=41, section="aux", name="bedSocketFlip")
        aux_bedSocketFlip.leds.append(
            LEDCtrl(ledboard=PwmBoard.NONE_, pin=52, on_value=1)
        )
        aux_bedSocketbtn = Hwctrl(pin=66, section="aux", name="bedSocketBtn")
        aux_bedSocketbtn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=11, on_value=DEFAULT_PWM)
        )
        aux_bedSocketbtn.add_slave(
            Hwctrl(
                pin=46,
                hw_type=HWEvent.RELAY,
                invert=True,
                section="relay",
                follow_parent=True,
            )
        )
        aux_bedSocketbtn.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.NONE_,
                pin=48,
                on_value=1,
                is_indicator=True,
            )
        )
        aux_bedSocketFlip.add_slave(aux_bedSocketbtn)

        # ##################### BYRÅ SOCKET ########################
        aux_drawerFlip = Hwctrl(pin=40, section="aux", name="auxFlipbyrå")
        aux_drawerFlip.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=51, on_value=1))
        aux_drawerBtn = Hwctrl(pin=68, section="aux", name="auxflipByråBtn")
        aux_drawerBtn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=10, on_value=DEFAULT_PWM)
        )
        aux_drawerBtn.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.NONE_,
                pin=49,
                on_value=1,
                is_indicator=True,
            )
        )
        aux_drawerBtn.add_slave(
            Hwctrl(
                pin=47,
                hw_type=HWEvent.RELAY,
                invert=True,
                section="relay",
                follow_parent=True,
            )
        )
        aux_drawerFlip.add_slave(aux_drawerBtn)

        # ###############         NOT IN USE        ################
        aux_flip2 = Hwctrl(pin=39, section="aux", name="auxNA")
        aux_flip2.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=53, on_value=1))
        aux_flip2btn = Hwctrl(pin=69, section="aux", name="auxNA_Btn")
        aux_flip2btn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=9, on_value=DEFAULT_PWM)
        )
        # aux_flip2btn.add_slave(Hwctrl(pin=44, section="relay", follow_parent=True))
        aux_flip2.add_slave(aux_flip2btn)

        # #########################################
        self.ctrls.extend(
            [aux_bedlampFlip, aux_flip2, aux_drawerFlip, aux_bedSocketFlip]
        )

    def _list_waveformcollider_controls(self):
        e17 = Hwctrl(pin=17, section="waveform", name="effectbtn17")
        e17.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=10, on_value=DEFAULT_PWM)
        )
        e18 = Hwctrl(pin=18, section="waveform", name="effectbtn18")
        e18.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=6, on_value=DEFAULT_PWM))
        e19 = Hwctrl(pin=19, section="waveform", name="effectbtn19")
        e19.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=11, on_value=DEFAULT_PWM)
        )
        e22 = Hwctrl(pin=22, section="waveform", name="effectbtn22")
        e22.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=4, on_value=DEFAULT_PWM))
        e23 = Hwctrl(pin=23, section="waveform", name="effectbtn23")
        e23.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=9, on_value=DEFAULT_PWM))
        e24 = Hwctrl(pin=24, section="waveform", name="effectbtn24")
        e24.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=5, on_value=DEFAULT_PWM))
        e25 = Hwctrl(pin=25, section="waveform", name="effectbtn25")
        e25.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=8, on_value=DEFAULT_PWM))
        e26 = Hwctrl(pin=26, section="waveform", name="effectbtn26")
        e26.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=7, on_value=DEFAULT_PWM))
        self.ctrls.extend([e17, e18, e19, e22, e23, e24, e25, e26])

        wf_speaker = Hwctrl(pin=NO_PIN, section="waveform", name="speaker")
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=12,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=13,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=14,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=15,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        wf_volumectrl = Analogctrl(
            pin=109, section="waveform", name="volumectrl"
        )  # Volume ctrl
        wf_rec = Hwctrl(pin=27, section="waveform", name="recordbtn")
        wf_rec.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=0, on_value=DEFAULT_PWM)
        )
        self.ctrls.extend([wf_speaker, wf_volumectrl, wf_rec])

    def _list_subspacesat_controls(self):
        f1 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip1")
        f1.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=10, on_value=DEFAULT_PWM))
        f1b = Hwctrl(pin=2, section="subspace", name="sccbtn1")
        f1b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=9, on_value=DEFAULT_PWM))
        f2 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip2")
        f2.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=11, on_value=DEFAULT_PWM))
        f2b = Hwctrl(pin=3, section="subspace", name="sccbtn2")
        f2b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=8, on_value=DEFAULT_PWM))
        f3 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip3")
        f3.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=12, on_value=DEFAULT_PWM))
        f3b = Hwctrl(pin=4, section="subspace", name="sccbtn3")
        f3b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=5, on_value=DEFAULT_PWM))
        f4 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip4")
        f4.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=13, on_value=DEFAULT_PWM))
        f4b = Hwctrl(pin=5, section="subspace", name="sccbtn4")
        f4b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=6, on_value=DEFAULT_PWM))
        f5 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip5")
        f5.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=14, on_value=DEFAULT_PWM))
        f5b = Hwctrl(pin=6, section="subspace", name="sccbtn5")
        f5b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=4, on_value=DEFAULT_PWM))
        f6 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip6")
        f6.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=15, on_value=DEFAULT_PWM))
        f6b = Hwctrl(pin=7, section="subspace", name="sccbtn6")
        f6b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=3, on_value=DEFAULT_PWM))
        f7 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip7")
        f7.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=0, on_value=DEFAULT_PWM))
        f7b = Hwctrl(pin=8, section="subspace", name="sccbtn7")
        f7b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=2, on_value=DEFAULT_PWM))
        f8 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip8")
        f8.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=1, on_value=DEFAULT_PWM))
        f8b = Hwctrl(pin=9, section="subspace", name="sccbtn8")
        f8b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=7, on_value=DEFAULT_PWM))
        f9 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip9")
        f9.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=2, on_value=DEFAULT_PWM))
        f9b = Hwctrl(pin=10, section="subspace", name="sccbtn9")
        f9b.leds.append(LEDCtrl(ledboard=PwmBoard.I2CALED, pin=0, on_value=DEFAULT_PWM))
        f10 = Hwctrl(pin=NO_PIN, section="subspace", name="sscflip10")
        f10.leds.append(LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=3, on_value=DEFAULT_PWM))
        f10b = Hwctrl(pin=11, section="subspace", name="sccbtn10")
        f10b.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CALED, pin=1, on_value=DEFAULT_PWM)
        )
        self.ctrls.extend([f1, f1b, f2, f2b, f3, f3b, f4, f4b, f5, f5b])
        self.ctrls.extend([f6, f6b, f7, f7b, f8, f8b, f9, f9b, f10, f10b])

    def _list_master_controls(self):
        self.ctrls.append(Hwctrl(pin=12, name="masterSw", section="master"))

        ma_backl = Hwctrl(pin=14, name="BacklightSw", section="master")
        ma_backl.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.NONE_,
                pin=63,
                on_value=1,
                is_indicator=False,
            )
        )
        ma_backl.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=15,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        ma_backl.slaves.append(Hwctrl(pin=44, name="BacklightRelay", section="master"))

        ma_inputsw = Hwctrl(pin=15, name="InputsSw", section="master")
        ma_inputsw.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.NONE_,
                pin=64,
                on_value=1,
                is_indicator=False,
            )
        )
        ma_inputsw.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=14,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )

        ma_soundsw = Hwctrl(pin=16, name="SoundSw", section="master")
        ma_soundsw.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.NONE_,
                pin=65,
                on_value=1,
                is_indicator=False,
            )
        )
        ma_soundsw.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=13,
                on_value=DEFAULT_PWM,
                is_indicator=True,
            )
        )
        self.ctrls.extend([ma_backl, ma_inputsw, ma_soundsw])


class CtrlNotFoundException(Exception):
    """
    Raised when searching for a HwCtrl and not finding
    a matching HwCtrl
    """

    def __init__(self, pin: int, msg: str = None):
        self.pin = pin
        self.msg = (
            f"pin={pin}. {msg}"
            if msg is not None
            else f"pin={pin}. Ctrl with pin={pin} was not found"
        )
        super().__init__(self.msg)


class LEDException(Exception):
    """
    Raised when LED reached invalid state
    or attempting to perform an action which
    the LED could not support
    """
