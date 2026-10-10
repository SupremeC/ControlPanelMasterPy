#!/usr/bin/env python
"""Lifecycle tests: constructors open nothing, start()/stop() work and
stop() is safe before start() and when called twice.

Serial ports, the pygame mixer and the OpenAI client are mocked. Never
call start() on a real AudioCtrl or ControlPanel here.
"""

import json
import logging
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path

import serial
from google.auth.exceptions import RefreshError

from daemon.audio_ctrl import AudioCtrl
from daemon.controlpanel_class import ControlPanel
from daemon.gCalender import Calender
from daemon.openaiWrapper import OpenAiWrapper
from daemon.setup_logger import QUIET_LOGGERS, configure_logging
from daemon.wled import WLED


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@mock.patch("daemon.wled.serial.Serial")
class TestWledLifecycle(unittest.TestCase):
    def _make(self) -> WLED:
        wled = WLED()
        wled.RECONNECT_INTERVAL = 0
        self.addCleanup(wled.stop)
        return wled

    def test_constructor_opensNothing(self, mock_serial):
        # act
        wled = self._make()

        # assert
        mock_serial.assert_not_called()
        self.assertIsNone(wled.sending_thread)

    def test_stop_beforeStartIsNoop(self, mock_serial):
        # arrange
        wled = self._make()

        # act
        wled.stop()

        # assert
        mock_serial.return_value.close.assert_not_called()

    def test_start_sendsQueuedCommandsAsJsonLines(self, mock_serial):
        # arrange
        fake_port = mock_serial.return_value
        wled = self._make()

        # act
        wled.start()
        wled.set_brightness(100, 1)

        # assert
        mock_serial.assert_called_once_with("/dev/serial0", 460800, timeout=2)
        self.assertTrue(_wait_until(lambda: fake_port.write.called), "nothing written")
        line = fake_port.write.call_args.args[0]
        self.assertEqual({"seg": [{"id": 1, "bri": 100}]}, json.loads(line))

    def test_stop_twiceClosesPortOnce(self, mock_serial):
        # arrange
        fake_port = mock_serial.return_value
        wled = self._make()
        wled.start()
        thread = wled.sending_thread

        # act
        wled.stop()
        wled.stop()

        # assert
        fake_port.close.assert_called_once()
        self.assertFalse(thread.is_alive())

    def test_start_portMissing_opensOnNextCommand(self, mock_serial):
        # arrange
        fake_port = mock.MagicMock()
        mock_serial.side_effect = [serial.SerialException("no port"), fake_port]
        wled = self._make()

        # act
        wled.start()
        wled.set_brightness(10, 0)

        # assert
        self.assertTrue(_wait_until(lambda: fake_port.write.called), "never reopened")
        self.assertEqual(2, mock_serial.call_count)

    def test_writeFails_portIsReopened(self, mock_serial):
        # arrange
        broken_port, good_port = mock.MagicMock(), mock.MagicMock()
        broken_port.write.side_effect = serial.SerialException("gone")
        mock_serial.side_effect = [broken_port, good_port]
        wled = self._make()
        wled.start()

        # act
        wled.set_brightness(10, 0)
        self.assertTrue(_wait_until(lambda: broken_port.close.called), "not closed")
        wled.set_brightness(20, 0)

        # assert
        self.assertTrue(_wait_until(lambda: good_port.write.called), "never reopened")


class TestCalendarLifecycle(unittest.TestCase):
    def test_constructor_startsNoThread(self):
        # act
        cal = Calender(None, None)

        # assert
        self.assertIsNone(cal.cal_updater_thread)

    def test_stop_beforeStartIsNoop(self):
        # arrange
        cal = Calender(None, None)

        # act / assert (no exception)
        cal.stop()
        cal.stop()

    @mock.patch.object(Calender, "fetch", return_value=False)
    def test_stop_wakesThreadDuringUpdateInterval(self, _get_events):
        # arrange
        cal = Calender(None, None)
        cal.start()
        thread = cal.cal_updater_thread
        self.assertTrue(_wait_until(lambda: _get_events.called))

        # act
        started = time.monotonic()
        cal.stop()

        # assert
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(cal.cal_updater_thread)


class TestCalendarTokens(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.token = Path(tmp.name) / "token.json"

    def _creds(self, valid=False, expired=True, refresh_error=None):
        creds = mock.Mock(valid=valid, expired=expired, refresh_token="r")
        creds.to_json.return_value = '{"refreshed": true}'
        if refresh_error is not None:
            creds.refresh.side_effect = refresh_error
        return creds

    @mock.patch("daemon.gCalender.build")
    def test_noTokenFile_logsAndSkips(self, mock_build):
        # arrange
        cal = Calender(None, None, token_file=self.token)

        # act
        with self.assertLogs("daemon.gCalender", "ERROR"):
            ok = cal.fetch()

        # assert: no browser login, no API call
        self.assertFalse(ok)
        self.assertEqual([], cal.todays_events())
        mock_build.assert_not_called()

    @mock.patch("daemon.gCalender.Credentials.from_authorized_user_file")
    def test_refreshFails_logsAndSkips(self, mock_load):
        # arrange
        self.token.write_text("{}")
        mock_load.return_value = self._creds(refresh_error=RefreshError("revoked"))
        cal = Calender(None, None, token_file=self.token)

        # act
        with self.assertLogs("daemon.gCalender", "ERROR"):
            ok = cal.refresh_tokens()

        # assert
        self.assertFalse(ok)

    @mock.patch("daemon.gCalender.Credentials.from_authorized_user_file")
    def test_expiredToken_isRefreshedAndSaved(self, mock_load):
        # arrange
        self.token.write_text("{}")
        mock_load.return_value = self._creds()
        cal = Calender(None, None, token_file=self.token)

        # act
        ok = cal.refresh_tokens()

        # assert
        self.assertTrue(ok)
        self.assertEqual('{"refreshed": true}', self.token.read_text())

    @mock.patch("daemon.gCalender.Credentials.from_authorized_user_file")
    def test_validToken_isUsedAsIs(self, mock_load):
        # arrange
        self.token.write_text("{}")
        mock_load.return_value = self._creds(valid=True, expired=False)
        cal = Calender(None, None, token_file=self.token)

        # act / assert
        self.assertTrue(cal.refresh_tokens())
        mock_load.return_value.refresh.assert_not_called()


class TestOpenAiLifecycle(unittest.TestCase):
    def test_constructor_doesNotReadKey(self):
        # act / assert (missing key file is fine until first use)
        OpenAiWrapper(key_path=Path("/nonexistent/key"))

    @mock.patch("daemon.openaiWrapper.OpenAI")
    def test_client_readsKeyOnFirstUseOnly(self, mock_openai):
        # arrange
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key"
            key.write_text("sk-test\n")
            ai = OpenAiWrapper(key_path=key)
            mock_openai.assert_not_called()

            # act
            first = ai.client
            second = ai.client

        # assert
        mock_openai.assert_called_once_with(api_key="sk-test")
        self.assertIs(first, second)


@mock.patch("daemon.audio_ctrl.mixer")
class TestAudioLifecycle(unittest.TestCase):
    def test_constructor_doesNotOpenMixer(self, mock_mixer):
        # act
        audio = AudioCtrl(lambda _on: None)

        # assert
        mock_mixer.init.assert_not_called()
        self.assertIsNone(audio._thread)

    def test_stop_beforeStartIsNoop(self, mock_mixer):
        # arrange
        audio = AudioCtrl(lambda _on: None)

        # act
        audio.stop()

        # assert
        mock_mixer.quit.assert_not_called()

    @mock.patch("daemon.audio_ctrl.subprocess.run")
    def test_playBytes_pipesMp3ToQuietFfplay(self, mock_run, _mock_mixer):
        # arrange
        audio = AudioCtrl(lambda _on: None)

        # act
        audio.play_bytes(b"mp3-data")

        # assert
        args, kwargs = mock_run.call_args
        self.assertEqual("ffplay", args[0][0])
        self.assertIn("-loglevel", args[0])
        self.assertEqual(b"mp3-data", kwargs["input"])
        self.assertTrue(kwargs["check"])


class TestLoggingSetup(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger()
        saved = (root.handlers[:], root.level)
        quiet = {n: logging.getLogger(n).level for n in QUIET_LOGGERS}

        def restore():
            root.handlers[:], root.level = saved
            for name, level in quiet.items():
                logging.getLogger(name).setLevel(level)

        self.addCleanup(restore)

    def test_thirdPartyDebugIsSilenced(self):
        # act
        configure_logging()

        # assert
        self.assertEqual(1, len(logging.getLogger().handlers))
        self.assertFalse(logging.getLogger("openai").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("httpcore").isEnabledFor(logging.INFO))
        self.assertTrue(logging.getLogger("daemon.ctrlPanel").isEnabledFor(logging.DEBUG))


@mock.patch("daemon.audio_ctrl.mixer")
@mock.patch("serial.tools.list_ports.comports", return_value=[])
@mock.patch("serial.Serial")
class TestControlPanelLifecycle(unittest.TestCase):
    def _make_with_fake_components(self):
        cp = ControlPanel()
        calls = []
        for attr, name in (
            ("_pserial", "serial"),
            ("wled_instance", "wled"),
            ("_audioctrl", "audio"),
            ("cal", "calendar"),
        ):
            fake = mock.Mock()
            fake.start.side_effect = lambda n=name: calls.append(f"{n}.start")
            fake.stop.side_effect = lambda n=name: calls.append(f"{n}.stop")
            setattr(cp, attr, fake)
        return cp, calls

    def test_constructor_opensNothing(self, mock_serial, mock_comports, mock_mixer):
        # arrange
        threads_before = threading.active_count()

        # act
        ControlPanel()

        # assert
        mock_serial.assert_not_called()
        mock_comports.assert_not_called()
        mock_mixer.init.assert_not_called()
        self.assertEqual(threads_before, threading.active_count())

    def test_startThenStop_reverseOrder(self, *_mocks):
        # arrange
        cp, calls = self._make_with_fake_components()

        # act
        cp.start()
        cp.stop()
        cp.stop()

        # assert
        self.assertEqual(
            [
                "serial.start",
                "wled.start",
                "audio.start",
                "calendar.start",
                "calendar.stop",
                "audio.stop",
                "wled.stop",
                "serial.stop",
            ],
            calls,
        )

    def test_startFails_startedComponentsAreStopped(self, *_mocks):
        # arrange
        cp, calls = self._make_with_fake_components()
        cp._audioctrl.start.side_effect = RuntimeError("no audio device")

        # act
        with self.assertRaises(RuntimeError):
            cp.start()
        cp.stop()

        # assert
        self.assertEqual(
            ["serial.start", "wled.start", "wled.stop", "serial.stop"], calls
        )

    def test_stopFailure_otherComponentsStillStop(self, *_mocks):
        # arrange
        cp, calls = self._make_with_fake_components()
        cp.start()
        cp.wled_instance.stop.side_effect = RuntimeError("uart stuck")

        # act
        with self.assertLogs("daemon.ctrlPanel", "ERROR"):
            cp.stop()

        # assert
        self.assertIn("serial.stop", calls)


if __name__ == "__main__":
    unittest.main()
