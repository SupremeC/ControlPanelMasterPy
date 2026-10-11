"""Preset clips: the ten audio buttons (pins 2-11).

Each button plays its active clip, daemon/sounds/btn_<pin>.wav: a
recording saved on the button (long press 1.5 s) or the default,
daemon/systemsounds/btn_<pin>.wav, which a 4.5 s long press restores.
AudioCtrl owns the same two directories; Config.preset_sounds_dir and
preset_defaults_dir must point at them.

This module replaces a default from a file uploaded through the web
API (any format, converted with ffmpeg to 48 kHz mono WAV), restores
it, names the buttons (daemon/presets.json, gitignored) and describes
the clips for the page. Blocking work (ffprobe, ffmpeg, copying) runs
on the audio lane; the metadata is read and written on the main thread.
Files are replaced with os.replace() next to the target, so a button
pressed meanwhile still plays a whole file.
"""

import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

from daemon.config import Config
from daemon.gCalender import TIMEZONE

logger = logging.getLogger("daemon.presets")

PRESET_PINS = range(2, 12)
FFPROBE_TIMEOUT = 15  # seconds
NAME_MAX = 24


class PresetError(ValueError):
    """Refused, with a message for the page: not audio, too long, a
    bad name, a conversion that failed."""


def default_name(pin: int) -> str:
    return f"Knapp {pin}"


def wav_seconds(path: Path) -> float | None:
    """Length of a WAV file from its header, or None."""
    try:
        with wave.open(str(path), "rb") as clip:
            rate = clip.getframerate()
            return round(clip.getnframes() / rate, 2) if rate else None
    except (OSError, wave.Error, EOFError):
        return None


def probe_seconds(path: Path, timeout: float = FFPROBE_TIMEOUT) -> float:
    """The length of an audio file, via ffprobe. PresetError when the
    file has no audio stream or cannot be read."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type:format=duration",
        "-of", "csv=p=0", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PresetError("Kunde inte läsa filen (det tog för lång tid)") from None
    except FileNotFoundError:
        raise PresetError("ffprobe saknas på datorn") from None
    tokens = result.stdout.split()
    if result.returncode != 0 or "audio" not in tokens:
        logger.info("ffprobe refused %s: %s", path.name, result.stderr.strip())
        raise PresetError("Filen är inte en ljudfil")
    for token in tokens:
        try:
            return float(token)
        except ValueError:
            continue
    raise PresetError("Kunde inte läsa klippets längd")


def convert(src: Path, dst: Path, max_seconds: float, timeout: float) -> None:
    """src to 48 kHz mono 16-bit WAV at dst, cut at max_seconds."""
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn",
        "-ac", "1", "-ar", "48000", "-sample_fmt", "s16",
        "-t", str(max_seconds), str(dst),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PresetError("Konverteringen tog för lång tid") from None
    except FileNotFoundError:
        raise PresetError("ffmpeg saknas på datorn") from None
    if result.returncode != 0 or not dst.is_file():
        logger.error("ffmpeg failed on %s: %s", src.name, result.stderr.strip())
        raise PresetError("Kunde inte konvertera filen")


def replace_file(src: Path, dst: Path) -> None:
    """Copies src over dst atomically: a temp file next to dst, then
    os.replace, so a reader never sees a half-written dst."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dst.stem}-", suffix=".tmp", dir=dst.parent)
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o644)  # mkstemp makes it 0600; the other clips are readable
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class Presets:
    """The clips and their metadata. The constructor does no I/O."""

    def __init__(self, config: Config | None = None):
        cfg = config or Config()
        self._cfg = cfg
        self.sounds_dir: Path = cfg.preset_sounds_dir
        self.defaults_dir: Path = cfg.preset_defaults_dir
        self.upload_dir: Path = cfg.preset_upload_dir
        self._file: Path = cfg.presets_file
        self._meta: dict[str, dict] | None = None
        self._hashes: dict[Path, tuple[tuple[float, int], str]] = {}

    # ---- paths ------------------------------------------------------------

    def active_path(self, pin: int) -> Path:
        return self.sounds_dir / f"btn_{pin}.wav"

    def default_path(self, pin: int) -> Path:
        return self.defaults_dir / f"btn_{pin}.wav"

    # ---- metadata (main thread) -----------------------------------------------

    def _load(self) -> dict[str, dict]:
        if self._meta is None:
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                self._meta = data if isinstance(data, dict) else {}
            except FileNotFoundError:
                self._meta = {}
            except (OSError, ValueError):
                logger.exception("Could not read %s; starting empty", self._file)
                self._meta = {}
        return self._meta

    def _save(self) -> None:
        text = json.dumps(self._load(), ensure_ascii=False, indent=2)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self._file)

    def _entry(self, pin: int) -> dict:
        """For reading: an empty dict when nothing is stored."""
        return self._load().get(str(pin), {})

    def _entry_for_writing(self, pin: int) -> dict:
        return self._load().setdefault(str(pin), {})

    def name(self, pin: int) -> str:
        return self._entry(pin).get("name") or default_name(pin)

    def set_name(self, pin: int, name: str) -> str:
        name = " ".join(str(name).split())
        if not name or len(name) > NAME_MAX:
            raise PresetError(f"Namnet måste vara 1-{NAME_MAX} tecken")
        self._entry_for_writing(pin)["name"] = name
        self._save()
        return name

    def note_default(self, pin: int, source: str | None) -> None:
        """Remembers where a button's default came from and when."""
        entry = self._entry_for_writing(pin)
        entry["default_source"] = source
        entry["default_set"] = datetime.datetime.now(TIMEZONE).isoformat(timespec="seconds")
        self._save()

    # ---- status (main thread; file reads only) -------------------------------

    def _sha1(self, path: Path) -> str:
        stat = path.stat()
        key = (stat.st_mtime, stat.st_size)
        cached = self._hashes.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
        digest = hashlib.sha1()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                digest.update(chunk)
        self._hashes[path] = (key, digest.hexdigest())
        return self._hashes[path][1]

    def _same(self, a: Path, b: Path) -> bool:
        try:
            return a.stat().st_size == b.stat().st_size and self._sha1(a) == self._sha1(b)
        except OSError:
            return False

    def status_of(self, pin: int) -> dict:
        active = self.active_path(pin)
        default = self.default_path(pin)
        has_default = default.is_file()
        if not active.is_file():
            state = "missing"
        elif has_default and self._same(active, default):
            state = "default"
        else:
            state = "recording"
        entry = self._entry(pin)
        return {
            "pin": pin,
            "id": f"btn_{pin}",
            "name": self.name(pin),
            "has_default": has_default,
            "active": state,
            "active_seconds": wav_seconds(active) if state != "missing" else None,
            "default_seconds": wav_seconds(default) if has_default else None,
            "default_source": entry.get("default_source"),
            "default_set": entry.get("default_set"),
        }

    def status(self) -> list[dict]:
        return [self.status_of(pin) for pin in PRESET_PINS]

    # ---- changes ---------------------------------------------------------------

    def install(self, pin: int, upload: Path, activate: bool) -> dict:
        """Blocking (audio lane): checks and converts the upload, replaces
        the default and, with activate, the active clip. Removes the
        upload whatever happens. Returns pin, seconds and activate."""
        cfg = self._cfg
        try:
            seconds = probe_seconds(upload)
            if seconds > cfg.preset_max_seconds:
                raise PresetError(
                    f"Klippet är {seconds:.0f} s långt, max {cfg.preset_max_seconds:.0f} s"
                )
            wav = upload.with_name(upload.stem + ".converted.wav")
            try:
                convert(upload, wav, cfg.preset_max_seconds, cfg.ffmpeg_timeout)
                replace_file(wav, self.default_path(pin))
                if activate:
                    replace_file(wav, self.active_path(pin))
                return {
                    "pin": pin,
                    "seconds": wav_seconds(wav) or round(seconds, 2),
                    "activate": activate,
                }
            finally:
                wav.unlink(missing_ok=True)
        finally:
            upload.unlink(missing_ok=True)

    def restore(self, pin: int) -> None:
        """The default becomes the active clip again. KeyError without
        a default."""
        default = self.default_path(pin)
        if not default.is_file():
            raise KeyError(f"btn_{pin}")
        replace_file(default, self.active_path(pin))
