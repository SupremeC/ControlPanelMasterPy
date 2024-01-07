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

    def __eq__(self, other):
        if isinstance(other, Hwctrl):
            return self.pin == other.pin
        return False

    def add_slave(self, slave: Hwctrl) -> None:
        """Add a Slave to this Ctrl"""
        slave.parent = self
        self.slaves.append(slave)

    def set_state(self, new_state: bool) -> List[Packet]:
        """Set state and optionally returns a packet to turn on related LEDs"""
        self.state = bool(new_state)
        self.quick_state_change = (
            datetime.datetime.now() - self.state_change_date
        ).total_seconds() < 2
        self.state_change_date = datetime.datetime.now()
        packets = self.set_state_of_leds(new_state, True)
        for slave in self.slaves:
            if not slave.follow_parent:
                continue
            packets.extend(slave.set_state(new_state))
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
                    if not led.led_is_indicator:
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

    def reset(self):
        """Reset all controls to their initial state"""
        self.ctrls.clear()
        self.__load_ctrls()

    def dim_lights(self, intensity: int = 100) -> List[Packet]:
        """Dim all LEDs (both ctrls and indicators) to supplied intensity
        This will not affect Backlight

        Args:
            intensity (int, optional): 0-100. Defaults to 100.

        Returns:
            List[Packet]: List of command packages
        """
        pass

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
        self._list_ledstripl_controls()
        self._list_ledstripr_controls()

    def _list_ledstripr_controls(self):
        lsr_pwr = Hwctrl(pin=32, section="ledstripR", name="RightLedStripPowerBtn")
        lsr_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=5,
                on_value=PWM_MAX,
                is_indicator=False,
            )
        )
        lsr_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=8,
                on_value=PWM_MAX,
                is_indicator=True,
            )
        )
        lsr_preveffect = Hwctrl(
            pin=33, section="ledstripR", name="RightLedStripPreEffectBtn"
        )
        lsr_preveffect.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=6,
                on_value=PWM_MAX,
                is_indicator=False,
            )
        )
        lsr_nexteffect = Hwctrl(
            pin=34, section="ledstripR", name="RightLedStripNextEffectBtn"
        )
        lsr_nexteffect.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=7,
                on_value=PWM_MAX,
                is_indicator=False,
            )
        )
        self.ctrls.extend([lsr_pwr, lsr_preveffect, lsr_nexteffect])
        self.ctrls.append(Analogctrl(pin=105, section="ledstripR", name="R Intensity"))
        self.ctrls.append(Analogctrl(pin=106, section="ledstripR", name="R Red"))
        self.ctrls.append(Analogctrl(pin=107, section="ledstripR", name="R Green"))
        self.ctrls.append(Analogctrl(pin=108, section="ledstripR", name="R Blue"))

    def _list_ledstripl_controls(self):
        lsl_pwr = Hwctrl(pin=35, section="ledstripL", name="LeftLedStripPowerBtn")
        lsl_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=1,
                on_value=PWM_MAX,
                is_indicator=False,
            )
        )
        lsl_pwr.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CCLED,
                pin=4,
                on_value=PWM_MAX,
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
                on_value=PWM_MAX,
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
                on_value=PWM_MAX,
                is_indicator=False,
            )
        )
        self.ctrls.extend([lsl_pwr, lsl_preveffect, lsl_nexteffect])
        self.ctrls.append(Analogctrl(pin=101, section="ledstripL", name="L Intensity"))
        self.ctrls.append(Analogctrl(pin=102, section="ledstripL", name="L Red"))
        self.ctrls.append(Analogctrl(pin=103, section="ledstripL", name="L Green"))
        self.ctrls.append(Analogctrl(pin=104, section="ledstripL", name="L Blue"))

    def _list_aux_controls(self):
        aux_flip1 = Hwctrl(pin=38, section="aux", name="auxFlip1")
        aux_flip1.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=50, on_value=1))
        aux_flip1btn = Hwctrl(pin=66, section="aux", name="auxflip1Btn")
        aux_flip1btn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=9, on_value=PWM_MAX)
        )
        aux_flip1btn.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.NONE_,
                pin=48,
                on_value=1,
                is_indicator=True,
            )
        )
        aux_flip1btn.add_slave(Hwctrl(pin=45, section="relay", follow_parent=True))
        aux_flip1.add_slave(aux_flip1btn)

        ###########################################################

        aux_flip2 = Hwctrl(pin=39, section="aux", name="auxFlip2")
        aux_flip2.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=51, on_value=1))
        aux_flip2btn = Hwctrl(pin=67, section="aux", name="auxflip2Btn")
        aux_flip2btn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=10, on_value=PWM_MAX)
        )
        aux_flip2btn.add_slave(Hwctrl(pin=46, section="relay", follow_parent=True))
        aux_flip2.add_slave(aux_flip2btn)

        ###########################################################

        aux_flip3 = Hwctrl(pin=40, section="aux", name="auxFlip3")
        aux_flip3.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=52, on_value=1))
        aux_flip3btn = Hwctrl(pin=68, section="aux", name="auxflip3Btn")
        aux_flip3btn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=11, on_value=PWM_MAX)
        )
        aux_flip3btn.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.NONE_,
                pin=49,
                on_value=1,
                is_indicator=True,
            )
        )
        aux_flip2btn.add_slave(Hwctrl(pin=47, section="relay", follow_parent=True))
        aux_flip3.add_slave(aux_flip3btn)

        ############################################################

        aux_lamp = Hwctrl(pin=41, section="aux", name="bedLampFlip")
        aux_lamp.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=53, on_value=1))
        aux_lampbtn = Hwctrl(pin=69, section="aux", name="bedLampBtn")
        aux_lampbtn.leds.append(
            LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=12, on_value=PWM_MAX)
        )
        aux_lamp.add_slave(aux_lampbtn)
        self.ctrls.extend([aux_flip1, aux_flip2, aux_flip3, aux_lamp])

    def _list_waveformcollider_controls(self):
        for i in range(0, 8):  # including 0, not including 8
            wf_effbtn = Hwctrl(pin=i + 17, section="waveform", name=f"effectbtn{i+7}")
            wf_effbtn.leds.append(
                LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=i + 4, on_value=PWM_MAX)
            )
            self.ctrls.append(wf_effbtn)

        wf_speaker = Hwctrl(pin=NO_PIN, section="waveform", name="speaker")
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=12,
                on_value=PWM_MAX,
                is_indicator=True,
            )
        )
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=13,
                on_value=PWM_MAX,
                is_indicator=True,
            )
        )
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=14,
                on_value=PWM_MAX,
                is_indicator=True,
            )
        )
        wf_speaker.leds.append(
            LEDCtrl(
                ledboard=PwmBoard.I2CBLED,
                pin=15,
                on_value=PWM_MAX,
                is_indicator=True,
            )
        )
        wf_volumectrl = Analogctrl(
            pin=109, section="waveform", name="volumectrl"
        )  # Volume ctrl
        wf_rec = Hwctrl(pin=27, section="waveform", name="recordbtn")
        wf_rec.leds.append(LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=0, on_value=PWM_MAX))
        self.ctrls.extend([wf_speaker, wf_volumectrl, wf_rec])

    def _list_subspacesat_controls(self):
        for i in range(0, 6):  # including 0, not including 6
            sscflip = Hwctrl(pin=NO_PIN, section="subspace", name=f"sscflip{i+1}")
            sscflip.leds.append(
                LEDCtrl(ledboard=PwmBoard.I2CALED, pin=i + 10, on_value=PWM_MAX)
            )

            sscbtn = Hwctrl(pin=i + 2, section="subspace", name=f"sccbtn{i+1}")
            sscbtn.leds.append(
                LEDCtrl(ledboard=PwmBoard.I2CALED, pin=i, on_value=PWM_MAX)
            )
            self.ctrls.extend([sscflip, sscbtn])
        for i in range(0, 4):  # including 0, not including 4
            sscflip = Hwctrl(pin=NO_PIN, section="subspace", name=f"sscflip{i+7}")
            sscflip.leds.append(
                LEDCtrl(ledboard=PwmBoard.I2CBLED, pin=i, on_value=PWM_MAX)
            )

            sscbtn = Hwctrl(pin=i + 8, section="subspace", name=f"sccbtn{i+7}")
            sscbtn.leds.append(
                LEDCtrl(ledboard=PwmBoard.I2CALED, pin=i + 6, on_value=PWM_MAX)
            )
            self.ctrls.extend([sscflip, sscbtn])

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
                on_value=PWM_MAX,
                is_indicator=True,
            )
        )
        ma_backl.slaves.append(Hwctrl(pin=43, name="BacklightRelay", section="master"))

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
                on_value=PWM_MAX,
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
                on_value=PWM_MAX,
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
