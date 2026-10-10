#!/usr/bin/env python
"""Unit tests for the hardware control data classes in daemon.ctrls"""

import unittest

from daemon.packet import HWEvent, PwmBoard
from daemon.ctrls import (
    Analogctrl,
    CtrlNotFoundException,
    HwCtrls,
    Hwctrl,
    LEDCtrl,
    LEDException,
    SWITCH_OFF,
    SWITCH_ON,
    NO_LED,
    NO_PIN,
)


class Test_LEDCtrl(unittest.TestCase):
    def test_set_led_state_megaPin(self):
        led = LEDCtrl(ledboard=PwmBoard.NONE_, pin=50, on_value=1)

        p = led.set_led_state(True)

        self.assertEqual(p.hw_event, HWEvent.LED)
        self.assertEqual(p.target, 50)
        self.assertEqual(p.val, 1)
        self.assertTrue(led.state)

    def test_set_led_state_pwmBoard(self):
        led = LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=12, on_value=800)

        p_on = led.set_led_state(True)
        p_off = led.set_led_state(False)

        self.assertEqual(p_on.hw_event, HWEvent.I2CCLED)
        self.assertEqual(p_on.target, 12)
        self.assertEqual(p_on.val, 800)
        self.assertEqual(p_off.val, 0)

    def test_set_led_state_explicitValueIsClamped(self):
        led = LEDCtrl(ledboard=PwmBoard.I2CCLED, pin=12, on_value=800)

        p = led.set_led_state(True, 5000)

        self.assertEqual(p.val, 800)

    def test_set_led_state_noPinRaises(self):
        led = LEDCtrl(ledboard=PwmBoard.NONE_, pin=NO_LED)

        self.assertRaises(LEDException, led.set_led_state, True)

    def test_clamp(self):
        self.assertEqual(LEDCtrl.clamp(5, 0, 10), 5)
        self.assertEqual(LEDCtrl.clamp(-5, 0, 10), 0)
        self.assertEqual(LEDCtrl.clamp(50, 0, 10), 10)

    def test_invert_int(self):
        self.assertEqual(LEDCtrl._invert_int(2, 0, 10), 8)
        self.assertEqual(LEDCtrl._invert_int(7, 0, 100), 93)
        self.assertEqual(LEDCtrl._invert_int(50, 0, 100), 50)
        self.assertEqual(LEDCtrl._invert_int(0, -10, 10), 0)
        self.assertEqual(LEDCtrl._invert_int(-11, -10, 10), 10)  # outside range
        self.assertEqual(LEDCtrl._invert_int(40, -20, 10), -20)  # outside range

        # roundTrip
        a = LEDCtrl._invert_int(2, 0, 10)
        b = LEDCtrl._invert_int(a, 0, 10)
        self.assertEqual(2, b)


class Test_Hwctrl(unittest.TestCase):
    def test_compare(self):
        # act
        a = Hwctrl(pin=2, state=SWITCH_ON, section="test")
        b = Hwctrl(pin=2, state=SWITCH_OFF, section="test")
        c = Hwctrl(pin=3, state=SWITCH_ON, section="test")

        # assert: equality is by pin only
        self.assertEqual(a, b)
        self.assertNotEqual(b, c)

    def test_state(self):
        # act
        a = Hwctrl(pin=2, state=SWITCH_ON, section="test")
        b = Hwctrl(pin=2, state=bool(0), section="test")
        c = Hwctrl(pin=2, state=SWITCH_OFF, section="test")
        c.set_state(44)

        # assert
        self.assertEqual(a.state, True)
        self.assertEqual(b.state, False)
        self.assertEqual(c.state, True, "c case")

    def test_setState(self):
        # act
        a = Hwctrl(pin=2, state=SWITCH_ON, section="test")
        a.set_state(False)
        b = Hwctrl(pin=2, state=SWITCH_OFF, section="test")
        b.set_state(True)
        c = Hwctrl(pin=2, state=SWITCH_OFF, section="test")
        c.set_state(44)

        # assert
        self.assertEqual(a.state, False, "a case")
        self.assertEqual(b.state, True, "b case")
        self.assertEqual(c.state, True, "c case")

    def test_setState_invert(self):
        a = Hwctrl(pin=2, section="test", invert=True)

        a.set_state(True)

        self.assertFalse(a.state)

    def test_setState_reportPacket(self):
        a = Hwctrl(pin=45, section="test", hw_type=HWEvent.RELAY)

        packets = a.set_state(True, report=True)

        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].hw_event, HWEvent.RELAY)
        self.assertEqual(packets[0].target, 45)
        self.assertEqual(packets[0].val, 1)

    def test_setState_onlyIndicatorLedsFollow(self):
        a = Hwctrl(pin=2, section="test")
        a.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=50, is_indicator=True))
        a.leds.append(LEDCtrl(ledboard=PwmBoard.NONE_, pin=51, is_indicator=False))

        packets = a.set_state(True)

        self.assertEqual([p.target for p in packets], [50])

    def test_setState_slaveFollowsParent(self):
        parent = Hwctrl(pin=2, section="test")
        follower = Hwctrl(pin=3, section="test", follow_parent=True)
        loner = Hwctrl(pin=4, section="test", follow_parent=False)
        parent.add_slave(follower)
        parent.add_slave(loner)

        packets = parent.set_state(True)

        self.assertTrue(follower.state)
        self.assertFalse(loner.state)
        # the following slave reports its own state
        self.assertEqual([p.target for p in packets], [3])


class TestAnalogCtrl(unittest.TestCase):
    def test_setState(self):
        # act
        a = Analogctrl(pin=2, state=222, section="test")
        a.set_state(3001)
        b = Analogctrl(pin=3, state=SWITCH_ON, section="test")
        b.set_state(0)

        # assert
        self.assertEqual(a.state, 3001)
        self.assertEqual(b.state, 0)

    def test_setState_outOfRangeRaises(self):
        a = Analogctrl(pin=2, section="test")

        self.assertRaises(ValueError, a.set_state, 65534)
        self.assertRaises(ValueError, a.set_state, -1)


class TestHwCtrls(unittest.TestCase):
    def test_FindCtrl(self):
        # arrange
        a = HwCtrls()

        # act
        ctrl = a.get_ctrl(40)  # top-level aux flip switch
        sctrl = a.get_slavectrl(45)  # bed lamp relay, nested two levels down

        # assert
        self.assertTrue(len(a.ctrls) > 3)
        self.assertEqual(ctrl.pin, 40)
        self.assertEqual(sctrl.pin, 45)
        self.assertEqual(sctrl.hw_type, HWEvent.RELAY)

    def test_FindCtrl_byName(self):
        a = HwCtrls()

        ctrl = a.get_ctrl_by_name("auxFlipBedlamp")

        self.assertEqual(ctrl.pin, 38)

    def test_FindCtrl_wrongPinThrowsException(self):
        # arrange
        a = HwCtrls()

        # act & assert
        self.assertRaises(CtrlNotFoundException, a.get_ctrl, 999)
        self.assertRaises(CtrlNotFoundException, a.get_slavectrl, 999)
        self.assertRaises(CtrlNotFoundException, a.get_ctrl_by_name, "nope")

    def test_set_allLeds(self):
        # arrange
        a = HwCtrls()

        # act
        ps = a.set_all_leds(False)

        # assert
        self.assertTrue(len(ps) > 20)
        self.assertTrue(all(p.val == 0 for p in ps))

    def test_set_allLeds_section(self):
        a = HwCtrls()

        ps_all = a.set_all_leds(True)
        ps_aux = a.set_all_leds(True, section="aux")

        self.assertGreater(len(ps_aux), 0)
        self.assertLess(len(ps_aux), len(ps_all))

    def test_reset_restoresState(self):
        a = HwCtrls()
        a.get_ctrl(40).set_state(True)

        a.reset()

        self.assertFalse(a.get_ctrl(40).state)

    def test_AssertUniquePins(self):
        """Every Mega pin and every PWM-board channel may only be used once."""
        # arrange & act
        a = HwCtrls()
        ctrls = a._get_all_ctrls_flat()

        # assert
        used = {}
        for ctrl in ctrls:
            # Check ctrl pins
            if ctrl.pin != NO_PIN:
                key = f"mega pin={ctrl.pin}"
                self.assertNotIn(
                    key, used, f"{key} used by {used.get(key)} and {ctrl.name}"
                )
                used[key] = ctrl.name

            for led in ctrl.leds:
                if led.pin == NO_LED:
                    continue
                # check LED pins on ArduinoMega
                if led.ledboard == PwmBoard.NONE_:
                    key = f"mega pin={led.pin}"
                # check LED pins on PWMBoards
                else:
                    key = f"{led.ledboard.name} pin={led.pin}"
                self.assertNotIn(
                    key, used, f"{key} used by {used.get(key)} and {ctrl.name}"
                )
                used[key] = f"led of {ctrl.name}"


if __name__ == "__main__":
    unittest.main()
