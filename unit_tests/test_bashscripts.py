"""UnitTest of BashScripts"""

import unittest   # noqa
from typing import List
from client.bashscripts import BashScripts



class TestBashScript(unittest.TestCase):
    """Dependent on that logfile exists. This is sucky, I know"""
    def test_tail(self):
        """read text file and assert output"""
        # act
        actual = BashScripts.tail(
            "/home/david/source/cpPy/ControlPanelMasterPy/logs.log",
            20, 0)

        # assert
        self.assertIsInstance(actual, List)
        self.assertGreater(len(actual),  0)
