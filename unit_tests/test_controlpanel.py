"""Unit tests for daemon.controlpanel_class.

These tests bypass the constructor and only exercise the pure logic.
Lifecycle tests live in test_lifecycle.py.
"""

import time
import unittest
import unittest.mock as mock
from datetime import datetime, timedelta

from daemon.controlpanel_class import (
    ControlPanel,
    RESYNC_AFTER_CONNECT,
    SEND_HELLO_INTERVALL,
)
from daemon.packet import HWEvent, Packet


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


class TestResyncAfterConnect(unittest.TestCase):
    def _make(self, connected_ago: float | None) -> ControlPanel:
        cp = ControlPanel.__new__(ControlPanel)
        cp._synced_connection = None
        cp._pserial = mock.Mock()
        cp._pserial.connected_at = (
            None if connected_ago is None else time.monotonic() - connected_ago
        )
        cp.reset = mock.Mock()
        return cp

    def test_notConnected_noReset(self):
        # arrange
        cp = self._make(connected_ago=None)

        # act
        cp._resync_if_needed()

        # assert
        cp.reset.assert_not_called()

    def test_justConnected_waitsForBootMega(self):
        # arrange
        cp = self._make(connected_ago=1)

        # act
        cp._resync_if_needed()

        # assert
        cp.reset.assert_not_called()

    def test_noBootMegaAfterConnect_resetsOnce(self):
        # arrange
        cp = self._make(connected_ago=RESYNC_AFTER_CONNECT + 1)

        # act
        cp._resync_if_needed()
        cp._resync_if_needed()

        # assert
        cp.reset.assert_called_once()

    def test_bootMegaReceived_noExtraReset(self):
        # arrange
        cp = self._make(connected_ago=RESYNC_AFTER_CONNECT + 1)
        cp._ControlPanel__act(Packet(HWEvent.BOOTMEGA, 0, 1))
        cp.reset.reset_mock()

        # act
        cp._resync_if_needed()

        # assert
        cp.reset.assert_not_called()

    def test_reconnectAfterSync_resetsAgain(self):
        # arrange
        cp = self._make(connected_ago=RESYNC_AFTER_CONNECT + 1)
        cp._resync_if_needed()
        cp._pserial.connected_at = time.monotonic() - RESYNC_AFTER_CONNECT - 1

        # act
        cp._resync_if_needed()

        # assert
        self.assertEqual(2, cp.reset.call_count)


if __name__ == "__main__":
    unittest.main()
