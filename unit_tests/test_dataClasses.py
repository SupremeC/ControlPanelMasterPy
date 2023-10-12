#!/usr/bin/env python


import sys
from pathlib import Path
sys.path[0] = str(Path(sys.path[0]).parent)



from typing import List
from daemon.packet import Packet, HWEvent, ErrorType   # noqa
from daemon.ctrls_class import Analogctrl, HwCtrls,Hwctrl, PwmBoard, SWITCH_OFF, SWITCH_ON, NO_LED, LEDCtrl
import unittest   # noqa


class Test_Hwctrl(unittest.TestCase):
    def test_compare(self):
        # act
        a = Hwctrl(pin=2, state= SWITCH_ON, section="test")
        b = Hwctrl(pin=2, state= SWITCH_OFF, section="test")
        c = Hwctrl(pin=3, state= SWITCH_ON, section="test")

        # assert
        self.assertEqual(a, b)
        self.assertNotEqual(b, c)

    def test_state(self):
        # act
        a = Hwctrl(pin=2, state= SWITCH_ON, section="test")
        b = Hwctrl(pin=2, state= bool(0), section="test")
        c = Hwctrl(pin=2, state= SWITCH_OFF, section="test")
        c.set_state(44)

        # assert
        self.assertEqual(a.state, True)
        self.assertEqual(b.state, False)
        self.assertEqual(c.state, True, "c case")

    def test_setState(self):
        # act
        a = Hwctrl(pin=2, state= SWITCH_ON, section="test")
        aPackets = a.set_state(False)
        b = Hwctrl(pin=2, state= SWITCH_OFF, section="test")
        bPackets = b.set_state(True)
        c = Hwctrl(pin=2, state= SWITCH_OFF, section="test")
        cPackets = c.set_state(44)

        # assert
        self.assertEqual(a.state, False, "a case")
        self.assertEqual(b.state, True, "b case")
        self.assertEqual(c.state, True, "c case")

    def test_invert_int(self):
        self.assertEqual(LEDCtrl._invert_int(2, 0, 10), 8)
        self.assertEqual(LEDCtrl._invert_int(7, 0, 100), 93)
        self.assertEqual(LEDCtrl._invert_int(50, 0, 100), 50)
        self.assertEqual(LEDCtrl._invert_int(0, -10, 10), 0)
        self.assertEqual(LEDCtrl._invert_int(-11, -10, 10), 10) # outside range
        self.assertEqual(LEDCtrl._invert_int(40, -20, 10), -20) # outside range

        # roundTrip
        a = LEDCtrl._invert_int(2, 0, 10)
        b = LEDCtrl._invert_int(a, 0, 10)
        self.assertEqual(2, b)
        pass


class TestAnalogCtrl(unittest.TestCase):
    def test_setState(self):
        # act
        a = Analogctrl(pin=2, state=222, section="test")
        aPackets = a.set_state(3001)
        b = Analogctrl(pin=3, state= SWITCH_ON, section="test")
        bPackets = b.set_state(0)
        # assert
        self.assertEqual(a.state, 3001)
        self.assertEqual(b.state, 0)


class TestAuxCtrls(unittest.TestCase):
    def test_FindCtrl(self):
        # arrange
        a = HwCtrls()

        # act
        ctrl = a.get_ctrl(40)
        sctrl = a.get_slavectrl(30)
        
        # assert
        self.assertTrue(len(a.ctrls) > 3)
        self.assertTrue(ctrl)
        self.assertTrue(sctrl)
        self.assertEqual(ctrl.pin, 40)
        self.assertEqual(sctrl.pin, 30)

    def test_set_allLeds(self):
        # arrange
        a = HwCtrls()
        ctrls_flatList = a._get_all_ctrls_flat()

        # act
        ps = a.set_all_leds(False)
        
        # assert
        self.assertTrue(len(ps) > 20)

    def test_AssertUniquePins(self):
        # arrange & act
        a = HwCtrls()
        ctrls = a._get_all_ctrls_flat()

        # assert by adding into Dict. Duplicate values will throw exception
        d = dict()
        for ctrl in ctrls:
            # Check ctrl pins
            if ctrl.pin != -1:
                dictkey = "pin="+str(ctrl.pin)
                if dictkey in d:
                    raise DuplicatePinException("Pin already exists")
                d[dictkey] = "ctrlpin"

            # check LED pins on ArduinoMega
            for led in ctrl.leds:
                if led.ledboard == PwmBoard.NONE_ and led.led_pin != NO_LED:
                    dictkey = "pin="+str(led.led_pin)
                    if dictkey in d:
                        raise DuplicatePinException("LPin already exists")
                    d[dictkey] = "led_pin"
                #  check LED pins on PWMBoards
                elif led.ledboard != PwmBoard.NONE_ and led.led_pin != NO_LED:
                    dictkey = "board="+str(led.ledboard)+", pin="+str(led.led_pin)
                    if dictkey in d:
                        raise DuplicatePinException(
                            "Pwm.led_pin already exists.\rExisting->" + 
                            str(d[dictkey]) +"\rNew->" + str(led))
                    d[dictkey] = "pwmboard.led_pin"


    def test_FindCtrl_wrongPinThrowsException(self):
        # arrange
        a = HwCtrls()

        # act & assert
        self.assertRaises(Exception, a.get_ctrl, 999)


class DuplicatePinException(Exception):
    """Duplicate pins found in UnitTest"""

class DuplicateLEDPinException(Exception):
    """Duplicate pins found in UnitTest"""

if __name__ == '__main__':
    unittest.main()
