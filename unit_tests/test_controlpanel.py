"""unittest"""
import unittest  # noqa
from datetime import datetime, timedelta
from daemon.controlpanel_class import ControlPanel




class TestTimeToSendHello(unittest.TestCase):
    """test"""
    def test_firsteverhello_true(self):
        """test_None_true"""
        # arrange
        cp = ControlPanel()
        cp._last_sent_hello = None

        # act
        actual = cp.time_to_send_hello()

        # assert (default values)
        self.assertTrue(actual)

    def test_recent_false(self):
        """test_recent_false"""
        # arrange
        cp = ControlPanel()
        cp._last_sent_hello = datetime.now() - timedelta(seconds=10)

        # act
        actual = cp.time_to_send_hello()

        # assert (default values)
        self.assertFalse(actual)

    def test_2minut_true(self):
        """test_2minut_true"""
        # arrange
        cp = ControlPanel()
        cp._last_sent_hello = datetime.now() - timedelta(seconds=120)

        # act
        actual = cp.time_to_send_hello()

        # assert (default values)
        self.assertTrue(actual)

if __name__ == '__main__':
    unittest.main()
