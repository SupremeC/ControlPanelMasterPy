#!/usr/bin/env python

"""
import sys
from pathlib import Path
sys.path[0] = str(Path(sys.path[0]).parent)
"""

import time
import unittest  # noqa
from datetime import datetime, timedelta

from daemon.controlPanel_class import ControlPanel
from daemon.packet import ErrorType, HWEvent, Packet  # noqa


class Test_timeToSendHello(unittest.TestCase):
    def test_None_true(self):
        # arrange
        cp = ControlPanel()
        cp._lastSentHello = None

        # act
        actual = cp.time_to_send_hello()

        # assert (default values)
        self.assertTrue(actual)

    def test_recent_false(self):
        # arrange
        cp = ControlPanel()
        cp._lastSentHello = datetime.now() - timedelta(seconds=10)

        # act
        actual = cp.time_to_send_hello()

        # assert (default values)
        self.assertFalse(actual)

    def test_2minut_true(self):
        # arrange
        cp = ControlPanel()
        cp._lastSentHello = datetime.now() - timedelta(seconds=120)

        # act
        actual = cp.time_to_send_hello()

        # assert (default values)
        self.assertTrue(actual)

if __name__ == '__main__':
    unittest.main()
