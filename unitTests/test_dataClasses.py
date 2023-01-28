#!/usr/bin/env python

"""
import sys
from pathlib import Path
sys.path[0] = str(Path(sys.path[0]).parent)
"""


from typing import List
from daemon.packet import Packet, HWEvent, ErrorType   # noqa
from daemon.ctrlsClass import Analogctrl, HwCtrls,Hwctrl, PwmBoard, swOff, swOn, NoLed
import unittest   # noqa


class Test_Hwctrl(unittest.TestCase):
    def test_compare(self):
        # act
        a = Hwctrl(pin=2, state= swOn, section="test")
        b = Hwctrl(pin=2, state= swOff, section="test")
        c = Hwctrl(pin=3, state= swOn, section="test")

        # assert
        self.assertEqual(a, b)
        self.assertNotEqual(b, c)

    def test_state(self):
        # act
        a = Hwctrl(pin=2, state= swOn, section="test")
        b = Hwctrl(pin=2, state= bool(0), section="test")
        c = Hwctrl(pin=2, state= swOff, section="test")
        c.set_state(44)

        # assert
        self.assertEqual(a.state, True)
        self.assertEqual(b.state, False)
        self.assertEqual(c.state, True, "c case")

    def test_setState(self):
        # act
        a = Hwctrl(pin=2, state= swOn, ledboard=PwmBoard.I2CALED, ledPin=8, section="test")
        aPackets = a.set_state(False)
        b = Hwctrl(pin=2, state= swOff, section="test")
        bPackets = b.set_state(True)
        c = Hwctrl(pin=2, state= swOff, section="test")
        cPackets = c.set_state(44)

        # assert
        self.assertEqual(a.state, False, "a case")
        self.assertEqual(b.state, True, "b case")
        self.assertEqual(c.state, True, "c case")

        # assert return value
        self.assertTrue(len(aPackets) > 0, "nr of packets was wrong")
        self.assertTrue(aPackets[0].hwEvent == HWEvent.I2CALED, "HwEvent was wrong")
        self.assertTrue(aPackets[0].target == 8, "Target was wrong")
        self.assertTrue(len(bPackets) <= 0, "nr of packets should be 0")

    def test_invertInt(self):
        self.assertEqual(Hwctrl._invert_int(2, 0, 10), 8)
        self.assertEqual(Hwctrl._invert_int(7, 0, 100), 93)
        self.assertEqual(Hwctrl._invert_int(50, 0, 100), 50)
        self.assertEqual(Hwctrl._invert_int(0, -10, 10), 0)
        self.assertEqual(Hwctrl._invert_int(-11, -10, 10), 10) # outside range
        self.assertEqual(Hwctrl._invert_int(40, -20, 10), -20) # outside range

        # roundTrip
        a = Hwctrl._invert_int(2, 0, 10)
        b = Hwctrl._invert_int(a, 0, 10)
        self.assertEqual(2, b)
        pass


class TestAnalogCtrl(unittest.TestCase):
    def test_setState(self):
        # act
        a = Analogctrl(pin=2, state=222, ledboard=PwmBoard.I2CCLED, ledPin=8, section="test")
        aPackets = a.set_state(3001)
        b = Analogctrl(pin=3, state= swOn, ledboard=PwmBoard.I2CCLED, ledPin=NoLed, section="test")
        bPackets = b.set_state(0)
        # assert
        self.assertEqual(a.state, 3001)
        self.assertEqual(b.state, 0)

        # assert return value
        self.assertTrue(len(aPackets) > 0, "nr of packets was wrong")
        self.assertTrue(aPackets[0].hwEvent == HWEvent.I2CCLED, "HwEvent was wrong")
        self.assertTrue(aPackets[0].target == 8, "Target was wrong")
        self.assertTrue(len(bPackets) == 0, "nr of packets should be 0")


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
        ctrls_flatList = a._getAllCtrls_flat()

        # act
        ps = a.set_allLeds(False)
        
        # assert
        self.assertTrue(len(ps) > 20)

    def test_AssertUniquePins(self):
        # arrange & act
        a = HwCtrls()
        ctrls = a._getAllCtrls_flat()

        # assert by adding into Dict. Duplicate values will throw exception
        d = dict()
        for ctrl in ctrls:
            if ctrl.pin != -1:
                dictKey = "pin="+str(ctrl.pin)
                if dictKey in d:
                    raise Exception("Pin already exists")
                d[dictKey] = "pin"

            if ctrl.ledboard == PwmBoard.NONE_ and ctrl.ledPin != NoLed:
                dictKey = "pin="+str(ctrl.ledPin)
                if dictKey in d:
                    raise Exception("LPin already exists")
                d[dictKey] = "ledPin"
            elif ctrl.ledboard != PwmBoard.NONE_ and ctrl.ledPin != NoLed:
                dictKey = "board="+str(ctrl.ledboard)+", pin="+str(ctrl.ledPin)
                if dictKey in d:
                    raise Exception("Pwm.LedPin already exists.\rExisting->" + str(d[dictKey]) +"\rNew->" + str(ctrl))
                d[dictKey] = ctrl
        pass


    def test_FindCtrl_wrongPinThrowsException(self):
        # arrange
        a = HwCtrls()

        # act & assert
        self.assertRaises(Exception, a.get_ctrl, 999)
        ss= 12

    def helper_filterCtrls():
        pass


if __name__ == '__main__':
    unittest.main()
