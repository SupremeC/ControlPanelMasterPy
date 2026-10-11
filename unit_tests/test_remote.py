"""Unit tests for daemon.remote: the commands the web API runs on the
main thread.

A real ControlPanel (the constructor opens nothing) with its audio and
WLED parts replaced by mocks; the packets it would send are read from
the send queue. Only the WLED job lane is started, in the one test that
needs a snapshot. Never call ControlPanel.start() here.
"""

import datetime
from pathlib import Path
from queue import Empty
import shutil
import tempfile
import time
import unittest
import unittest.mock as mock

from daemon import remote as remote_module
from daemon.audio_ctrl import SysAudioEvent as aevent
from daemon.config import Config
from daemon.controlpanel_class import ControlPanel
from daemon.packet import HWEvent
from daemon.presets import PresetError
from daemon.wled import SegmentState, WledStateSnapshot


def snapshot(on0=True, bri0=100, on1=False, bri1=0, fx0=0) -> WledStateSnapshot:
    return WledStateSnapshot(
        True,
        2,
        [
            SegmentState(0, on0, bri0, 120, 0, 120, fx0),
            SegmentState(1, on1, bri1, 82, 120, 202, 0),
        ],
        datetime.datetime.now(),
    )


class RemoteTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = Config(
            web_enabled=False,
            preset_sounds_dir=self.root / "sounds",
            preset_defaults_dir=self.root / "systemsounds",
            preset_upload_dir=self.root / "tmp_upload",
            presets_file=self.root / "presets.json",
        )
        for d in (self.cfg.preset_sounds_dir, self.cfg.preset_defaults_dir, self.cfg.preset_upload_dir):
            d.mkdir()
        cp = ControlPanel(self.cfg)
        cp._audioctrl = mock.Mock()
        cp._audioctrl.master_volume = 70
        cp._audioctrl.get_volume.return_value = 0.7
        cp._audioctrl.is_recording.return_value = False
        cp._audioctrl.systemsounds = {"failed": object(), "demomode": object()}
        cp.wled_instance = mock.Mock()
        cp.wled_instance.read_state.return_value = snapshot()
        self.cp = cp
        self.remote = cp.remote

    def panel_on(self):
        self.cp._ctrls.get_ctrl_by_name("masterSw").state = True
        self.cp._ctrls.get_ctrl_by_name("InputsSw").state = True

    def sent(self) -> list:
        packets = []
        while True:
            try:
                packets.append(self.cp._packet_sendqueue.get_nowait())
            except Empty:
                return packets

    def process_until(self, predicate, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.cp.process(max_wait=0.02)
            if predicate():
                return True
        return predicate()

    @staticmethod
    def relays(packets) -> dict:
        return {p.target: p.val for p in packets if p.hw_event == HWEvent.RELAY}


class TestCommandLookup(RemoteTestCase):
    def test_knownCommand_returnsCallable(self):
        self.assertTrue(callable(self.remote.command("state")))

    def test_unknownCommand_keyError(self):
        with self.assertRaises(KeyError):
            self.remote.command("_send")
        with self.assertRaises(KeyError):
            self.remote.command("nope")


class TestSockets(RemoteTestCase):
    def test_on_sendsRelayLowAndLeds(self):
        # arrange
        self.panel_on()

        # act
        result = self.remote.set_socket("bed", True)
        packets = self.sent()

        # assert
        self.assertEqual({47: 0}, self.relays(packets))  # active-low
        self.assertTrue(any(p.hw_event == HWEvent.LED for p in packets))
        self.assertTrue(result["on"])
        self.assertEqual("På", result["text"])
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.BTN_CLICKED)

    def test_off_sendsRelayHigh(self):
        # arrange
        self.panel_on()
        self.remote.set_socket("drawer", True)
        self.sent()

        # act
        result = self.remote.set_socket("drawer", False)

        # assert
        self.assertEqual({46: 1}, self.relays(self.sent()))
        self.assertFalse(result["on"])

    def test_masterOff_sendsRelayOnly(self):
        # act
        self.remote.set_socket("bed", True)
        packets = self.sent()

        # assert
        self.assertEqual(1, len(packets))
        self.assertEqual(HWEvent.RELAY, packets[0].hw_event)

    def test_unknownSocket_valueError(self):
        with self.assertRaises(ValueError):
            self.remote.set_socket("garage", True)

    def test_toggle_flips(self):
        # act
        first = self.remote.toggle_socket("bed")
        second = self.remote.toggle_socket("bed")

        # assert
        self.assertTrue(first["on"])
        self.assertFalse(second["on"])

    def test_state_reportsSafetyFlip(self):
        # arrange
        self.cp._ctrls.get_ctrl(41).state = True

        # act
        state = self.remote.state()

        # assert
        self.assertTrue(state["sockets"]["bed"]["safety"])
        self.assertFalse(state["sockets"]["drawer"]["safety"])


class TestLamps(RemoteTestCase):
    def test_bedLamp_pulsesRelay(self):
        # act
        self.remote.bed_lamp_toggle()
        pressed = self.relays(self.sent())
        # Past the pulse (the tick also queues a HELLO packet meanwhile).
        self.process_until(lambda: False, timeout=remote_module.BED_LAMP_PULSE * 3)
        released = self.relays(self.sent())

        # assert
        self.assertEqual({45: 0}, pressed)
        self.assertEqual({45: 1}, released)

    def test_backlightOff_relayHighAndSound(self):
        # arrange
        relay = self.cp._ctrls.get_ctrl_by_name("BacklightRelay")
        relay.state = True

        # act
        result = self.remote.set_backlight(False)

        # assert
        self.assertEqual({44: 1}, self.relays(self.sent()))
        self.assertFalse(relay.state)
        self.assertFalse(result["on"])
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.BG_LIGHT_OFF)

    def test_backlightOn_masterOn_sendsIndicatorToo(self):
        # arrange
        self.panel_on()

        # act
        self.remote.set_backlight(True)
        packets = self.sent()

        # assert
        self.assertEqual({44: 0}, self.relays(packets))
        self.assertTrue(any(p.hw_event != HWEvent.RELAY for p in packets))

    def test_toggleBacklight_flips(self):
        self.assertTrue(self.remote.toggle_backlight()["on"])
        self.assertFalse(self.remote.toggle_backlight()["on"])

    def test_buttonLeds_sentEvenWithMasterOff(self):
        # act
        result = self.remote.set_button_leds(True)

        # assert
        self.assertTrue(result["on"])
        self.assertTrue(self.cp.btnLeds)
        self.assertGreater(len(self.sent()), 10)


class TestDemo(RemoteTestCase):
    def test_masterOff_refused(self):
        with self.assertRaises(ValueError):
            self.remote.set_demo(True)
        self.assertFalse(self.cp.demo_on)

    def test_on_startsDemo(self):
        # arrange
        self.panel_on()

        # act
        result = self.remote.set_demo(True)

        # assert
        self.assertTrue(result["on"])
        self.assertTrue(self.cp.demo_on)
        self.assertTrue(self.cp._demo_leds)
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.DEMOMODE)

    def test_off_alwaysAllowed(self):
        # arrange
        self.cp.demo_on = True

        # act
        result = self.remote.set_demo(False)

        # assert
        self.assertFalse(result["on"])
        self.assertFalse(self.cp.demo_on)


class TestSounds(RemoteTestCase):
    def setUp(self):
        super().setUp()
        (self.cfg.preset_sounds_dir / "btn_3.wav").write_bytes(b"RIFF")

    def test_list_presetsThenSystemSounds(self):
        # act
        sounds = self.remote.list_sounds()

        # assert
        self.assertEqual(
            [
                {"id": "btn_3", "label": "Knapp 3"},
                {"id": "demomode", "label": "Demo"},
                {"id": "failed", "label": "Fel"},
            ],
            sounds,
        )

    def test_muted_refused(self):
        # arrange
        self.cp._audioctrl.get_volume.return_value = 0

        # act / assert
        with self.assertRaises(ValueError):
            self.remote.play_sound("failed")
        self.cp._audioctrl.sysaudio_play.assert_not_called()

    def test_preset_playsAndBlinks(self):
        # arrange
        self.panel_on()

        # act
        self.remote.play_sound("btn_3")

        # assert
        self.cp._audioctrl.recsaved_play.assert_called_once_with(3)
        self.assertTrue(
            any(p.hw_event == HWEvent.BLINK3ENDHIGH for p in self.sent())
        )

    def test_presetWithoutFile_keyError(self):
        with self.assertRaises(KeyError):
            self.remote.play_sound("btn_4")

    def test_systemSound_plays(self):
        # act
        self.remote.play_sound("FAILED")

        # assert
        self.cp._audioctrl.sysaudio_play.assert_called_once_with(aevent.FAILED)

    def test_unknown_keyError(self):
        with self.assertRaises(KeyError):
            self.remote.play_sound("btn_pressed")  # an event without a file
        with self.assertRaises(KeyError):
            self.remote.play_sound("whatever")

    def test_stop(self):
        self.remote.stop_audio()
        self.cp._audioctrl.stop_all_audio.assert_called_once()


class TestVolume(RemoteTestCase):
    def test_set_goesThroughPanel(self):
        # act
        self.remote.set_volume(40)

        # assert
        self.cp._audioctrl.set_volume.assert_called_once_with(40)

    def test_set_outOfRange_valueError(self):
        with self.assertRaises(ValueError):
            self.remote.set_volume(101)
        with self.assertRaises(ValueError):
            self.remote.set_volume("hög")

    def test_step_isSilentAndClamped(self):
        # arrange
        self.cp._audioctrl.master_volume = 98

        # act
        self.remote.step_volume(5)

        # assert
        self.cp._audioctrl.set_volume.assert_called_once_with(100, sound=False)

    def test_muteUnmute_restoresLevel(self):
        # act
        self.remote.mute()
        self.cp._audioctrl.master_volume = 0
        self.remote.unmute()

        # assert
        self.assertEqual(
            [mock.call(0, sound=False), mock.call(70, sound=False)],
            self.cp._audioctrl.set_volume.call_args_list,
        )

    def test_unmute_withoutMute_default(self):
        # arrange
        self.cp._audioctrl.master_volume = 0

        # act
        self.remote.unmute()

        # assert
        self.cp._audioctrl.set_volume.assert_called_once_with(
            remote_module.UNMUTE_DEFAULT, sound=False
        )


class TestStrips(RemoteTestCase):
    def test_setOn_writesWledAndPowerLed(self):
        # arrange
        self.panel_on()

        # act
        result = self.remote.set_strip(1, on=True)

        # assert
        self.cp.wled_instance.set_wled_state.assert_called_once_with(True, 1)
        self.assertTrue(result["on"])
        self.assertTrue(self.cp._ctrls.get_ctrl(35).state)
        self.assertTrue(self.sent())

    def test_setAll_validates(self):
        with self.assertRaises(ValueError):
            self.remote.set_strip(2, on=True)
        with self.assertRaises(ValueError):
            self.remote.set_strip(0, brightness=300)
        with self.assertRaises(ValueError):
            self.remote.set_strip(0, color=[1, 2])
        with self.assertRaises(ValueError):
            self.remote.set_strip(0, effect="random")
        self.cp.wled_instance.set_brightness.assert_not_called()

    def test_colorAndEffect(self):
        # act
        self.remote.set_strip(0, color=(255, 0, 10), effect="next")
        self.remote.set_strip(0, effect="off")

        # assert
        self.cp.wled_instance.set_color.assert_called_once_with([255, 0, 10], 0)
        self.cp.wled_instance.next_effect.assert_called_once_with(0)
        self.cp.wled_instance._change_effect.assert_called_once_with(0, 0)

    def test_toggle_unknownState_letsWledToggle(self):
        # act
        self.remote.toggle_strip(0)

        # assert
        self.cp.wled_instance.toggle_wled_state.assert_called_once_with(0)
        self.cp.wled_instance.set_wled_state.assert_not_called()

    def test_toggle_knownState_setsOpposite(self):
        # arrange
        self.remote.set_strip(0, on=True)

        # act
        result = self.remote.toggle_strip(0)

        # assert
        self.assertFalse(result["on"])
        self.cp.wled_instance.set_wled_state.assert_called_with(False, 0)

    def test_stepBrightness_coalesces(self):
        # act: ten ticks at once
        for _ in range(10):
            result = self.remote.step_brightness(0, 16)
        at_once = self.cp.wled_instance.set_brightness.call_args_list[:]
        self.process_until(
            lambda: len(self.cp.wled_instance.set_brightness.call_args_list) > 1,
            timeout=1,
        )
        after = self.cp.wled_instance.set_brightness.call_args_list

        # assert: one send at once (unknown level + 16), one with the final value
        self.assertEqual([mock.call(remote_module.BRIGHTNESS_DEFAULT + 16, 0)], at_once)
        self.assertEqual(2, len(after))
        self.assertEqual(mock.call(255, 0), after[-1])  # 128 + 160, clamped
        self.assertEqual(255, result["brightness"])
        self.assertEqual(255, self.remote.state()["strips"]["segments"][0]["brightness"])

    def test_state_usesSnapshotFromLane(self):
        # arrange
        self.cp._wled_jobs.start()
        self.addCleanup(self.cp._wled_jobs.stop)

        # act
        first = self.remote.state()["strips"]["segments"]
        self.process_until(lambda: self.cp.wled_snapshot() is not None)
        second = self.remote.state()["strips"]["segments"]

        # assert
        self.assertIsNone(first[0]["on"])
        self.assertEqual("?", self.remote.state()["text"]["strip_1"][:0] + "?")
        self.assertTrue(second[0]["on"])
        self.assertEqual(100, second[0]["brightness"])
        self.assertFalse(second[1]["on"])
        self.assertEqual("På 39 %", self.remote.state()["text"]["strip_0"])
        self.assertEqual("Av", self.remote.state()["text"]["strip_1"])
        self.cp.wled_instance.read_state.assert_called_once()


class TestState(RemoteTestCase):
    def test_hasEveryKey(self):
        # act
        state = self.remote.state()

        # assert
        self.assertEqual(
            {"daemon", "switches", "sockets", "button_leds", "demo", "audio",
             "strips", "morning", "text"},
            set(state),
        )
        self.assertEqual({"master", "inputs", "sound", "backlight"}, set(state["switches"]))
        self.assertEqual({"volume", "muted", "playing", "recording"}, set(state["audio"]))
        self.assertEqual(70, state["audio"]["volume"])
        self.assertEqual("70 %", state["text"]["volume"])
        self.assertEqual("IDLE", state["morning"]["state"])
        self.assertIsNone(state["morning"]["next_alarm"])
        self.assertEqual("–", state["text"]["next_alarm"])
        self.assertFalse(state["daemon"]["mega_connected"])

    def test_playingFollowsPlaybackEvents(self):
        # act
        self.cp.speakerLeds(True)

        # assert
        self.assertTrue(self.remote.state()["audio"]["playing"])


class TestPresets(RemoteTestCase):
    def setUp(self):
        super().setUp()
        self.cp._audio_jobs.start()
        self.addCleanup(self.cp._audio_jobs.stop)
        self.upload = self.cfg.preset_upload_dir / "upload-x.m4a"
        self.upload.write_bytes(b"m4a")

    def test_upload_runsOnAudioLane_thenPanelFeedback(self):
        # arrange
        self.panel_on()
        install = mock.Mock(return_value={"pin": 5, "seconds": 2.0, "activate": True})
        self.remote.store.install = install

        # act
        future = self.remote.set_preset_default(5, str(self.upload), True, "Röstmemo.m4a")
        self.assertTrue(self.process_until(
            lambda: future.done() and self.cp._audioctrl.sysaudio_play.called
        ))

        # assert
        install.assert_called_once_with(5, self.upload, True)
        self.assertEqual({"pin": 5, "seconds": 2.0, "activate": True}, future.result())
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.REC_SAVED)
        self.assertTrue(any(p.hw_event == HWEvent.BLINK3ENDHIGH for p in self.sent()))
        self.assertEqual("Röstmemo.m4a", self.remote.store.status_of(5)["default_source"])

    def test_upload_failure_playsFailed(self):
        # arrange
        self.remote.store.install = mock.Mock(side_effect=PresetError("för långt"))

        # act
        future = self.remote.set_preset_default(5, str(self.upload), True)
        self.process_until(lambda: future.done() and self.cp._audioctrl.sysaudio_play.called)

        # assert
        self.assertIsInstance(future.exception(), PresetError)
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.FAILED)

    def test_upload_outsideUploadDir_refused(self):
        elsewhere = self.root / "elsewhere.m4a"
        elsewhere.write_bytes(b"x")
        with self.assertRaises(ValueError):
            self.remote.set_preset_default(5, str(elsewhere), True)
        with self.assertRaises(ValueError):
            self.remote.set_preset_default(12, str(self.upload), True)
        self.assertTrue(elsewhere.exists())

    def test_restore_fromDefault(self):
        # arrange
        (self.cfg.preset_defaults_dir / "btn_6.wav").write_bytes(b"default")
        (self.cfg.preset_sounds_dir / "btn_6.wav").write_bytes(b"recording")

        # act
        result = self.remote.restore_preset(6)

        # assert
        self.assertEqual("default", result["active"])
        self.assertEqual(b"default", (self.cfg.preset_sounds_dir / "btn_6.wav").read_bytes())
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.REC_SAVED)
        with self.assertRaises(KeyError):
            self.remote.restore_preset(7)

    def test_rename_showsInSoundsList(self):
        # arrange
        (self.cfg.preset_sounds_dir / "btn_4.wav").write_bytes(b"RIFF")

        # act
        result = self.remote.rename_preset(4, " Skratt ")

        # assert
        self.assertEqual("Skratt", result["name"])
        self.assertIn({"id": "btn_4", "label": "Skratt"}, self.remote.list_sounds())
        with self.assertRaises(ValueError):
            self.remote.rename_preset(4, "")

    def test_presetsCommand_listsTen(self):
        rows = self.remote.command("presets")()
        self.assertEqual(list(range(2, 12)), [r["pin"] for r in rows])


class TestAllOff(RemoteTestCase):
    def test_everythingOff(self):
        # arrange
        self.panel_on()
        self.remote.set_socket("bed", True)
        self.remote.set_socket("drawer", True)
        self.cp._ctrls.get_ctrl_by_name("BacklightRelay").state = True
        self.cp.demo_on = True
        self.sent()

        # act
        state = self.remote.all_off()
        relays = self.relays(self.sent())

        # assert
        self.assertEqual({44: 1, 46: 1, 47: 1}, relays)
        self.assertFalse(state["sockets"]["bed"]["on"])
        self.assertFalse(state["switches"]["backlight"])
        self.assertFalse(state["demo"])
        self.assertEqual(
            [mock.call(False, 0), mock.call(False, 1)],
            self.cp.wled_instance.set_wled_state.call_args_list,
        )
        self.cp.wled_instance.set_both.assert_not_called()  # no night light
        self.cp._audioctrl.stop_all_audio.assert_called_once()
        self.assertFalse(state["strips"]["segments"][0]["on"])


if __name__ == "__main__":
    unittest.main()
