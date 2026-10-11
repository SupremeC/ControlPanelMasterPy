"""Unit tests for daemon.presets: the preset clips' files, metadata,
ffprobe/ffmpeg wrappers (subprocess mocked) and the atomic replace.
Everything happens in temporary directories."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock as mock
import wave

from daemon import presets as presets_module
from daemon.config import Config
from daemon.presets import (
    PresetError,
    Presets,
    convert,
    probe_seconds,
    replace_file,
    wav_seconds,
)


def write_wav(path: Path, seconds: float = 0.5, rate: int = 48000, fill: bytes = b"\0\0") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(fill * int(rate * seconds))
    return path


class PresetsTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = Config(
            preset_sounds_dir=self.root / "sounds",
            preset_defaults_dir=self.root / "systemsounds",
            preset_upload_dir=self.root / "tmp_upload",
            presets_file=self.root / "presets.json",
            preset_max_seconds=10,
            ffmpeg_timeout=5,
        )
        for d in (self.cfg.preset_sounds_dir, self.cfg.preset_defaults_dir):
            d.mkdir()
        self.store = Presets(self.cfg)


class TestWav(PresetsTestCase):
    def test_seconds_fromHeader(self):
        path = write_wav(self.root / "a.wav", seconds=1.25)
        self.assertEqual(1.25, wav_seconds(path))

    def test_notWav_none(self):
        path = self.root / "x.wav"
        path.write_bytes(b"not a wav")
        self.assertIsNone(wav_seconds(path))
        self.assertIsNone(wav_seconds(self.root / "missing.wav"))


class TestStatus(PresetsTestCase):
    def test_missing_default_recording(self):
        # arrange: 2 has nothing, 3 plays its default, 4 plays a recording,
        # 5 has a recording and no default
        write_wav(self.store.default_path(3), 1)
        shutil.copyfile(self.store.default_path(3), self.store.active_path(3))
        write_wav(self.store.default_path(4), 1)
        write_wav(self.store.active_path(4), 2, fill=b"\1\0")
        write_wav(self.store.active_path(5), 0.5)

        # act
        by_pin = {p["pin"]: p for p in self.store.status()}

        # assert
        self.assertEqual(list(range(2, 12)), sorted(by_pin))
        self.assertEqual(("missing", False, None), (by_pin[2]["active"], by_pin[2]["has_default"], by_pin[2]["active_seconds"]))
        self.assertEqual(("default", True, 1.0, 1.0), (by_pin[3]["active"], by_pin[3]["has_default"], by_pin[3]["active_seconds"], by_pin[3]["default_seconds"]))
        self.assertEqual(("recording", True, 2.0), (by_pin[4]["active"], by_pin[4]["has_default"], by_pin[4]["active_seconds"]))
        self.assertEqual(("recording", False), (by_pin[5]["active"], by_pin[5]["has_default"]))
        self.assertEqual("Knapp 3", by_pin[3]["name"])
        self.assertEqual("btn_3", by_pin[3]["id"])

    def test_sameFile_hashCachedByMtime(self):
        # arrange
        write_wav(self.store.default_path(3), 1)
        shutil.copyfile(self.store.default_path(3), self.store.active_path(3))

        # act
        with mock.patch.object(presets_module.hashlib, "sha1", wraps=presets_module.hashlib.sha1) as sha1:
            self.store.status_of(3)
            self.store.status_of(3)

        # assert: two files hashed once each
        self.assertEqual(2, sha1.call_count)


class TestMetadata(PresetsTestCase):
    def test_rename_persistsAndReloads(self):
        # act
        self.store.set_name(5, "  Skratt   igen ")
        again = Presets(self.cfg)

        # assert
        self.assertEqual("Skratt igen", again.name(5))
        self.assertEqual("Knapp 6", again.name(6))

    def test_badName_refused(self):
        with self.assertRaises(PresetError):
            self.store.set_name(5, "   ")
        with self.assertRaises(PresetError):
            self.store.set_name(5, "x" * 25)
        self.assertFalse(self.cfg.presets_file.exists())

    def test_noteDefault_recordsSourceAndTime(self):
        # act
        self.store.note_default(7, "Röstmemo 3.m4a")

        # assert
        status = Presets(self.cfg).status_of(7)
        self.assertEqual("Röstmemo 3.m4a", status["default_source"])
        self.assertTrue(status["default_set"].startswith("20"))

    def test_corruptFile_startsEmpty(self):
        # arrange
        self.cfg.presets_file.write_text("{not json", encoding="utf-8")

        # act / assert
        with self.assertLogs("daemon.presets", "ERROR"):
            self.assertEqual("Knapp 2", self.store.name(2))


class TestReplaceFile(PresetsTestCase):
    def test_copiesViaTempInSameDirThenReplaces(self):
        # arrange
        src = self.root / "src.wav"
        src.write_bytes(b"new")
        dst = self.root / "dir" / "btn_4.wav"
        dst.parent.mkdir()
        dst.write_bytes(b"old")

        # act
        with mock.patch.object(presets_module.os, "replace", wraps=presets_module.os.replace) as replace:
            replace_file(src, dst)

        # assert
        self.assertEqual(b"new", dst.read_bytes())
        tmp, target = replace.call_args.args
        self.assertEqual(dst.parent, Path(tmp).parent)
        self.assertEqual(dst, Path(target))
        self.assertEqual(["btn_4.wav"], [p.name for p in dst.parent.iterdir()])  # no temp left

    def test_copyFails_noTempLeft(self):
        dst = self.root / "dir" / "btn_4.wav"
        with self.assertRaises(FileNotFoundError):
            replace_file(self.root / "missing", dst)
        self.assertEqual([], list(dst.parent.iterdir()))


class TestFfmpeg(PresetsTestCase):
    def test_probe_parsesStreamAndDuration(self):
        # arrange
        done = subprocess.CompletedProcess([], 0, stdout="audio\n8.005488\n", stderr="")

        # act
        with mock.patch.object(presets_module.subprocess, "run", return_value=done) as run:
            seconds = probe_seconds(Path("/x/a.m4a"), timeout=7)

        # assert
        self.assertAlmostEqual(8.005488, seconds)
        cmd = run.call_args.args[0]
        self.assertEqual("ffprobe", cmd[0])
        self.assertIn("/x/a.m4a", cmd)
        self.assertEqual(7, run.call_args.kwargs["timeout"])

    def test_probe_noAudio_refused(self):
        done = subprocess.CompletedProcess([], 0, stdout="12.0\n", stderr="")  # a video without audio
        with mock.patch.object(presets_module.subprocess, "run", return_value=done):
            with self.assertRaises(PresetError):
                probe_seconds(Path("/x/a.mp4"))

    def test_probe_failsOrHangs_refused(self):
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="Invalid data")
        with mock.patch.object(presets_module.subprocess, "run", return_value=failed):
            with self.assertRaises(PresetError):
                probe_seconds(Path("/x/a.txt"))
        with mock.patch.object(
            presets_module.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffprobe", 1)
        ):
            with self.assertRaises(PresetError):
                probe_seconds(Path("/x/a.txt"))

    def test_convert_commandAndTimeout(self):
        # arrange
        dst = self.root / "out.wav"

        def fake_run(cmd, **kwargs):
            dst.write_bytes(b"RIFF")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        # act
        with mock.patch.object(presets_module.subprocess, "run", side_effect=fake_run) as run:
            convert(Path("/x/in.m4a"), dst, max_seconds=60, timeout=30)

        # assert
        cmd = run.call_args.args[0]
        self.assertEqual("ffmpeg", cmd[0])
        for flag, value in (("-ac", "1"), ("-ar", "48000"), ("-sample_fmt", "s16"), ("-t", "60")):
            self.assertEqual(value, cmd[cmd.index(flag) + 1])
        self.assertEqual(30, run.call_args.kwargs["timeout"])

    def test_convert_failure_refused(self):
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock.patch.object(presets_module.subprocess, "run", return_value=failed):
            with self.assertLogs("daemon.presets", "ERROR"):
                with self.assertRaises(PresetError):
                    convert(Path("/x/in.m4a"), self.root / "out.wav", 60, 30)


class TestInstall(PresetsTestCase):
    def _upload(self) -> Path:
        self.cfg.preset_upload_dir.mkdir()
        upload = self.cfg.preset_upload_dir / "upload-abc.m4a"
        upload.write_bytes(b"m4a")
        return upload

    def test_replacesDefaultAndActive_removesUpload(self):
        # arrange
        upload = self._upload()
        write_wav(self.store.active_path(5), 3, fill=b"\2\0")  # a recording

        def fake_convert(src, dst, max_seconds, timeout):
            write_wav(dst, 1.5)

        # act
        with mock.patch.object(presets_module, "probe_seconds", return_value=1.5):
            with mock.patch.object(presets_module, "convert", side_effect=fake_convert):
                result = self.store.install(5, upload, activate=True)

        # assert
        self.assertEqual({"pin": 5, "seconds": 1.5, "activate": True}, result)
        self.assertEqual("default", self.store.status_of(5)["active"])
        self.assertEqual(1.5, wav_seconds(self.store.default_path(5)))
        self.assertFalse(upload.exists())
        self.assertEqual([], list(self.cfg.preset_upload_dir.iterdir()))  # converted wav gone too

    def test_keepRecording_replacesDefaultOnly(self):
        # arrange
        upload = self._upload()
        write_wav(self.store.active_path(5), 3, fill=b"\2\0")

        def fake_convert(src, dst, max_seconds, timeout):
            write_wav(dst, 1.5)

        # act
        with mock.patch.object(presets_module, "probe_seconds", return_value=1.5):
            with mock.patch.object(presets_module, "convert", side_effect=fake_convert):
                self.store.install(5, upload, activate=False)

        # assert
        self.assertEqual("recording", self.store.status_of(5)["active"])
        self.assertEqual(3.0, wav_seconds(self.store.active_path(5)))
        self.assertEqual(1.5, wav_seconds(self.store.default_path(5)))

    def test_tooLong_refused_uploadRemoved(self):
        # arrange
        upload = self._upload()

        # act / assert
        with mock.patch.object(presets_module, "probe_seconds", return_value=61):
            with mock.patch.object(presets_module, "convert") as convert_mock:
                with self.assertRaises(PresetError):
                    self.store.install(5, upload, activate=True)
        convert_mock.assert_not_called()
        self.assertFalse(upload.exists())
        self.assertFalse(self.store.default_path(5).exists())

    def test_restore(self):
        # arrange
        write_wav(self.store.default_path(6), 1)
        write_wav(self.store.active_path(6), 2, fill=b"\3\0")

        # act
        self.store.restore(6)

        # assert
        self.assertEqual("default", self.store.status_of(6)["active"])
        with self.assertRaises(KeyError):
            self.store.restore(7)


if __name__ == "__main__":
    unittest.main()
