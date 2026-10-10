#!/usr/bin/env python
"""AudioCtrl's volume override, alarm channel and alarm ramp.

The pygame mixer and ffplay are mocked; start() is never called. The
channels and sound library that start() would create are set by hand.
"""

import unittest
import unittest.mock as mock

from daemon.audio_ctrl import AudioCtrl, SysAudioEvent
from daemon.morning import alarm_ramp_level


class AudioTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("daemon.audio_ctrl.mixer")
        self.mixer = patcher.start()
        self.addCleanup(patcher.stop)
        audio = AudioCtrl(lambda _playing: None)
        audio.alarm_channel = mock.Mock()
        audio.systemsounds = {
            "alarm": "alarm-sound",
            "alarm_soft": "soft-sound",
            "volume_change": "beep",
            "chime_off": "chime",
        }
        audio.set_volume(30)  # the pot
        self.mixer.reset_mock()
        self.audio = audio


class TestVolumeOverride(AudioTestCase):
    def test_off_followsPotAndSwitch(self):
        self.assertAlmostEqual(0.3, self.audio.get_volume())
        self.audio.enable_sound(False)
        self.assertEqual(0, self.audio.get_volume())

    def test_on_ignoresPotAndSwitch(self):
        # arrange
        self.audio.enable_sound(False)

        # act
        self.audio.volume_override(True, 70)

        # assert
        self.assertAlmostEqual(0.7, self.audio.get_volume())

    def test_off_restoresChangesMadeMeanwhile(self):
        # arrange
        self.audio.volume_override(True, 70)
        self.audio.set_volume(45)
        self.audio.enable_sound(False)

        # act
        self.audio.volume_override(False)

        # assert: switch off wins, the pot value is kept for later
        self.assertEqual(0, self.audio.get_volume())
        self.audio.enable_sound(True)
        self.assertAlmostEqual(0.45, self.audio.get_volume())

    def test_on_potChangeIsSilent(self):
        # arrange
        self.audio.volume_override(True, 70)

        # act
        self.audio.set_volume(80)

        # assert
        self.mixer.Sound.assert_not_called()

    def test_on_systemSoundPlaysDespiteSwitchOff(self):
        # arrange
        self.audio.enable_sound(False)
        self.audio.volume_override(True, 70)

        # act
        self.audio.sysaudio_play(SysAudioEvent.CHIME_OFF)

        # assert
        self.mixer.Sound.assert_called_once_with("chime")
        self.mixer.Sound.return_value.set_volume.assert_called_once_with(0.7)

    def test_switchOff_noOverride_systemSoundSilent(self):
        # arrange
        self.audio.enable_sound(False)

        # act
        self.audio.sysaudio_play(SysAudioEvent.CHIME_OFF)

        # assert
        self.mixer.Sound.assert_not_called()

    @mock.patch("daemon.audio_ctrl.subprocess.run")
    def test_playBytes_usesOverrideLevel(self, mock_run):
        # act
        self.audio.play_bytes(b"mp3")
        self.audio.volume_override(True, 70)
        self.audio.play_bytes(b"mp3")

        # assert: full volume without override, as before
        without, with_override = (c.args[0] for c in mock_run.call_args_list)
        self.assertNotIn("-volume", without)
        i = with_override.index("-volume")
        self.assertEqual("70", with_override[i + 1])
        self.assertEqual(["-i", "pipe:0"], with_override[-2:])


class TestAlarmChannel(AudioTestCase):
    def test_start_loopsSoftAlarmThenSetsLevel(self):
        # act
        self.audio.alarm_start(10)

        # assert: the level comes after play(), which resets it
        self.mixer.Sound.assert_called_once_with("soft-sound")
        self.assertEqual(
            [
                mock.call.play(self.mixer.Sound.return_value, loops=-1),
                mock.call.set_volume(0.1),
            ],
            self.audio.alarm_channel.mock_calls,
        )

    def test_start_ignoresPotSwitchAndOverride(self):
        # arrange
        self.audio.enable_sound(False)
        self.audio.volume_override(True, 70)

        # act
        self.audio.alarm_start(10)

        # assert
        self.audio.alarm_channel.set_volume.assert_called_once_with(0.1)

    def test_start_noSoftAlarm_usesOldOne(self):
        # arrange
        del self.audio.systemsounds["alarm_soft"]

        # act
        with self.assertLogs("daemon.audioCtrl", "WARNING"):
            self.audio.alarm_start(10)

        # assert
        self.mixer.Sound.assert_called_once_with("alarm-sound")

    def test_start_noAlarmSound_logsError(self):
        # arrange
        self.audio.systemsounds = {}

        # act
        with self.assertLogs("daemon.audioCtrl", "ERROR"):
            self.audio.alarm_start(10)

        # assert
        self.audio.alarm_channel.play.assert_not_called()

    def test_setLevelAndStop(self):
        # act
        self.audio.alarm_set_level(150)
        self.audio.alarm_stop()

        # assert
        self.audio.alarm_channel.set_volume.assert_called_once_with(1.0)
        self.audio.alarm_channel.fadeout.assert_called_once()

    def test_beforeStart_setLevelAndStopAreSafe(self):
        # arrange
        self.audio.alarm_channel = None

        # act / assert (no exception)
        self.audio.alarm_set_level(50)
        self.audio.alarm_stop()
        self.assertFalse(self.audio.alarm_playing())


class TestAlarmRamp(unittest.TestCase):
    def test_table(self):
        table = [(-1, 10), (0, 10), (45, 26), (90, 70), (200, 70)]
        for elapsed, level in table:
            with self.subTest(elapsed=elapsed):
                self.assertEqual(level, alarm_ramp_level(elapsed, 90, 10, 70))

    def test_neverDrops(self):
        levels = [alarm_ramp_level(t / 10, 90, 10, 70) for t in range(901)]
        self.assertEqual(sorted(levels), levels)

    def test_zeroLength_isEndLevel(self):
        self.assertEqual(70, alarm_ramp_level(0, 0, 10, 70))


if __name__ == "__main__":
    unittest.main()
