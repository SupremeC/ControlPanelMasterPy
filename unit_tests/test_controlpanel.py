"""Unit tests for daemon.controlpanel_class.

These tests bypass the constructor and only exercise the pure logic.
Lifecycle tests live in test_lifecycle.py.
"""

import unittest
from datetime import datetime, timedelta

from daemon.controlpanel_class import ControlPanel, SEND_HELLO_INTERVALL


def _bare_controlpanel() -> ControlPanel:
    """Create a ControlPanel instance without running __init__."""
    cp = ControlPanel.__new__(ControlPanel)
    cp._last_sent_hello = None
    return cp


class TestTimeToSendHello(unittest.TestCase):
    def test_firsteverhello_true(self):
        # arrange
        cp = _bare_controlpanel()

        # act
        actual = cp.time_to_send_hello()

        # assert
        self.assertTrue(actual)

    def test_recent_false(self):
        # arrange
        cp = _bare_controlpanel()
        cp._last_sent_hello = datetime.now() - timedelta(seconds=10)

        # act
        actual = cp.time_to_send_hello()

        # assert
        self.assertFalse(actual)

    def test_pastInterval_true(self):
        # arrange
        cp = _bare_controlpanel()
        cp._last_sent_hello = datetime.now() - timedelta(
            seconds=SEND_HELLO_INTERVALL + 1
        )

        # act
        actual = cp.time_to_send_hello()

        # assert
        self.assertTrue(actual)


if __name__ == "__main__":
    unittest.main()
