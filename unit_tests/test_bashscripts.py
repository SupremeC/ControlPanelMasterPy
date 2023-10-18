"""UnitTest of BashScripts"""

import unittest  # noqa
from typing import List
import pathlib
from client.bashscripts import BashScripts
import daemon.global_variables


class TestBashScript(unittest.TestCase):
    """Dependent on that logfile exists. This is sucky, I know"""

    def test_tail(self):
        """read text file and assert output"""
        # arrange
        logfile = pathlib.Path(daemon.global_variables.root_path)
        logfile = logfile.joinpath("logs.log")

        self.assertIsNotNone(logfile)
        if not logfile.exists():
            self.skipTest("Logfile not found, so we cannot test TAIL function")

        # act
        actual = BashScripts.tail(logfile, 20, 0)

        # assert
        self.assertIsInstance(actual, List)
        self.assertGreater(len(actual), 0)
