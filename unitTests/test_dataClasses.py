#!/usr/bin/env python

"""
import sys
from pathlib import Path
sys.path[0] = str(Path(sys.path[0]).parent)
"""


from typing import List
from daemon.packet import Packet, HWEvent, ErrorType   # noqa
from daemon.auxClass import Analogctrl, Aux, AuxCtrls, Hwctrl, PwmBoard, swOff, swOn, NoLed
import unittest   # noqa


class Test_Hwctrl(unittest.TestCase):
    def test_compare(self):
        # act
        a = Hwctrl(pin=2, state= swOn)
        b = Hwctrl(pin=2, state= swOff)
        c = Hwctrl(pin=3, state= swOn)

        # assert
        self.assertEqual(a, b)
        self.assertNotEqual(b, c)

    def test_state(self):
        # act
        a = Hwctrl(pin=2, state= swOn)
        b = Hwctrl(pin=2, state= bool(0))
        c = Hwctrl(pin=2, state= swOff)
        c.set_state(44)

        # assert
        self.assertEqual(a.state, True)
        self.assertEqual(b.state, False)
        self.assertEqual(c.state, True, "c case")

    def test_setState(self):
        # act
        a = Hwctrl(pin=2, state= swOn, ledboard=PwmBoard.I2CALED, ledPin=8)
        aPackets = a.set_state(False)
        b = Hwctrl(pin=2, state= swOff)
        bPackets = b.set_state(True)
        c = Hwctrl(pin=2, state= swOff)
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


class TestAux(unittest.TestCase):
    def test_setSlaveState(self):
        # act
        a = Aux(pin=2, state= swOn, ledboard=PwmBoard.I2CALED, ledPin=8, slave_ledboard=PwmBoard.I2CBLED, slave_ledPin=6)
        aPackets = a.set_Slstate(False)
        b = Aux(pin=2, state= swOn, ledboard=PwmBoard.I2CALED, ledPin=8)
        bPackets = b.set_Slstate(True)
        # assert
        self.assertEqual(a.slave_state, False)
        self.assertEqual(b.slave_state, True)

        # assert return value
        self.assertTrue(len(aPackets) > 0, "nr of packets was wrong")
        self.assertTrue(aPackets[0].hwEvent == HWEvent.I2CBLED, "HwEvent was wrong")
        self.assertTrue(aPackets[0].target == 6, "Target was wrong")
        self.assertTrue(len(bPackets) <= 0, "nr of packets should be 0")


class TestAnalogCtrl(unittest.TestCase):
    def test_setState(self):
        # act
        a = Analogctrl(pin=2, state=222, ledboard=PwmBoard.I2CCLED, ledPin=8)
        aPackets = a.set_state(3001)
        b = Analogctrl(pin=3, state= swOn, ledboard=PwmBoard.I2CCLED, ledPin=NoLed)
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
        a = AuxCtrls()

        # act
        ctrl = a.get_auxctrl(40)
        sctrl = a.get_slavectrl(30)
        
        # assert
        self.assertTrue(len(a.ctrls) > 3)
        self.assertIs(ctrl, sctrl)
        self.assertEqual(ctrl.pin, 40)
        self.assertEqual(sctrl.slave_pin, 30)

    def test_set_allLeds(self):
        # arrange
        a = AuxCtrls()

        # act
        ps = a.set_allLeds(False)
        
        # assert
        self.assertTrue(len(ps) == 4)

    def test_FindCtrl_wrongPinThrowsException(self):
        # arrange
        a = AuxCtrls()

        # act & assert
        self.assertRaises(Exception, a.get_auxctrl, 999)
        ss= 12


if __name__ == '__main__':
    unittest.main()
