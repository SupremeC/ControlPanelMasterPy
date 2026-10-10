"""AudioCtrl"""

import datetime
import logging
import random
import shutil
import string
import subprocess
import threading
import base64
from pathlib import Path
import time
from typing import Callable
from enum import unique, IntEnum
from pygame import mixer
from daemon.audio_rec import AudioRec
from daemon.audio_effects import AudioEffect, EffectType
from daemon.config import Config
import daemon.global_variables

logger = logging.getLogger("daemon.audioCtrl")

REC_CHANNEL = 0
ALARM_CHANNEL = 1  # reserved, so system sounds never cut the alarm off
ALARM_FADEOUT_MS = 500


@unique
class SysAudioEvent(IntEnum):
    """SysAudioEvent"""

    NONE_ = 0
    BTN_PRESSED = 1
    BTN_RELEASED = 2
    BTN_CLICKED = 3
    REC_STARTED = 30
    REC_STOPPED = 32
    REC_COULD_NOT_REC = 34
    EFFECT_APPLYING = 40
    EFFECT_APPLY_DONE = 42
    REC_SAVED = 43
    VOLUME_CHANGE = 50
    SYSTEM_OFF = 60
    SYSTEM_ON = 61
    CTRLS_ON = 62
    CTRLS_OFF = 63
    BG_LIGHT_ON = 64
    BG_LIGHT_OFF = 65
    AUDIO_ON = 66
    AUDIO_OFF = 67
    RELAY_ON = 70
    RELAY_OFF = 71
    FLIP_SWITCH = 90
    DEMOMODE = 100
    ALARM = 120
    ALARM_SOFT = 121
    CHIME_OFF = 122
    CHIME_SPEAK = 123
    FAILED = 200
    TICK = 254


class AudioCtrl:
    """AudioCtrl

    Supports:
    ---
     - Recording audio
     - Playing audio
     - Apply effects to audio files
    """

    systemsounds: dict = None
    _current_filepath: str
    max_rectime_seconds: int = 30
    rec_channel: mixer.Channel
    rec_ctrl: AudioRec
    effect_ctrl: AudioEffect
    rec_time: datetime.datetime
    __tempdir: Path = None
    __storagedir: Path = None
    __systemsoundsdir: Path = None
    __master_volume: int = 20
    __sound_on: bool = True

    def __init__(self, p_callback_onchange: Callable[[bool], None]):
        root = daemon.global_variables.root_path.resolve()
        self.__tempdir = root.joinpath("daemon/tmp_rec")
        self.__storagedir = root.joinpath("daemon/sounds")
        self.__systemsoundsdir = root.joinpath("daemon/systemsounds")
        self.__create_dir(self.__tempdir, self.__storagedir, self.__systemsoundsdir)
        self.rec_ctrl = AudioRec(folder=self.__tempdir)
        self.effect_ctrl = AudioEffect()
        self.playing: bool = False
        self.on_play_change: Callable = p_callback_onchange
        self.rec_time = None
        self._current_filepath = None
        self.alarm_channel: mixer.Channel | None = None
        # Set while the morning routine holds the volume (0.0-1.0).
        self._override_volume: float | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Opens the audio mixer, loads the system sounds and starts
        the playback monitor thread."""
        if self._thread is not None:
            return
        # init() 'channels' refers to mono vs stereo, not playback Channel object
        mixer.init(48000, -16, channels=1, buffer=1024)
        mixer.set_num_channels(6)
        mixer.set_reserved(2)
        self.rec_channel = mixer.Channel(REC_CHANNEL)
        self.alarm_channel = mixer.Channel(ALARM_CHANNEL)
        audioclipsfound = self.__load_sound_library(self.__systemsoundsdir)
        self.enable_sound(True)
        self.set_volume(50)  # 0-100

        logger.info("Found %d audio clips", audioclipsfound)

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.__playback_monitor, name="audio-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stops the playback monitor thread and closes the mixer.
        Safe to call more than once, and before start()."""
        self._stop_event.set()
        if self._thread is None:
            return
        if self._thread.is_alive():
            self._thread.join(1)
        self._thread = None
        mixer.quit()

    @property
    def current_filepath(self):
        """Getter for the current_filepath property."""
        if (
            self.rec_time is not None
            and datetime.datetime.now() >= self.rec_time + datetime.timedelta(minutes=1)
        ):
            self.rec_time = None
            self._current_filepath = None
        return self._current_filepath

    @current_filepath.setter
    def current_filepath(self, value):
        """Setter for the name property."""
        self._current_filepath = value
        self.rec_time = datetime.datetime.now()

    def set_volume(self, volume: int) -> None:
        """Sets the volume for all sounds (the volume pot). While the
        volume override is on, it is only stored for afterwards.

        Args:
            volume (int): 0-100
        """
        volume = AudioCtrl.__clamp(volume, 0, 100)
        self.__master_volume = volume / 100
        if self._override_volume is None:
            self.sysaudio_play(SysAudioEvent.VOLUME_CHANGE)

    def get_volume(self) -> float:
        """0.0-1.0. The pot level, 0 if the sound switch is off, or the
        override level while the override is on."""
        if self._override_volume is not None:
            return self._override_volume
        return self.__master_volume if self.__sound_on else 0

    def volume_override(self, on: bool, level: int = Config.alarm_volume) -> None:
        """On: every sound plays at level (percent), whatever the pot and
        the sound switch say. Off: the pot and switch apply again,
        including changes made while the override was on."""
        self._override_volume = AudioCtrl.__clamp(level, 0, 100) / 100 if on else None
        logger.info(
            "Volume override %s", f"on at {level} %" if on else "off"
        )

    def enable_sound(self, on: bool) -> None:
        self.__sound_on = on

    def recsaved_play(self, pin: int = None) -> None:
        """Plays sound linked to pinNr"""
        if self.get_volume() <= 0:
            return
        if pin is None:
            logger.warning("No pinNr provided to AudioCtrl.recsaved_play(). NOOP")
            return
        soundpath = self.__storagedir.joinpath(f"btn_{pin}.wav")
        if not soundpath.exists():
            self.sysaudio_play(SysAudioEvent.FAILED)
            return
        mysound = mixer.Sound(soundpath.resolve())
        mysound.set_volume(self.get_volume())
        self.rec_channel.play(mysound)

    def restore_original_audio(self, pin: int) -> None:
        """Copies the original wav-file to __storagedir
        folder, overwriting any existing file."""
        if pin is None:
            return
        try:
            src = self.__systemsoundsdir.joinpath(f"btn_{pin}.wav")
            dest = self.__storagedir.joinpath(f"btn_{pin}.wav")
            shutil.copy(src, dest)
        except OSError as e:
            logger.exception(e)

    def play_bytes(self, p_bytes: bytes) -> None:
        """Blocking: plays MP3 data with ffplay until it ends. ffplay is what
        pydub used here too, but pydub let it print its progress to the
        journal. Full volume, except at the override level while the
        override is on."""
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]
        if self._override_volume is not None:
            cmd += ["-volume", str(round(self._override_volume * 100))]
        subprocess.run(
            cmd + ["-i", "pipe:0"],
            input=p_bytes,
            stdout=subprocess.DEVNULL,
            check=True,
        )

    def alarm_start(self, level: int) -> None:
        """Loops the alarm sound on its own channel at level (percent),
        whatever the pot, the sound switch and the override say.
        Uses alarm.wav if alarm_soft.wav is missing."""
        name = next((n for n in ("alarm_soft", "alarm") if n in self.systemsounds), None)
        if name is None:
            logger.error("No alarm sound in %s", self.__systemsoundsdir)
            return
        if name != "alarm_soft":
            logger.warning("alarm_soft.wav missing, using %s.wav", name)
        sound = mixer.Sound(self.systemsounds[name])
        self.alarm_channel.play(sound, loops=-1)
        # play() resets the channel volume, so set it afterwards.
        self.alarm_channel.set_volume(AudioCtrl.__clamp(level, 0, 100) / 100)

    def alarm_set_level(self, level: int) -> None:
        """Changes the level (percent) of the playing alarm."""
        if self.alarm_channel is not None:
            self.alarm_channel.set_volume(AudioCtrl.__clamp(level, 0, 100) / 100)

    def alarm_stop(self) -> None:
        """Fades the alarm out. Safe when it is not playing."""
        if self.alarm_channel is not None:
            self.alarm_channel.fadeout(ALARM_FADEOUT_MS)

    def alarm_playing(self) -> bool:
        return self.alarm_channel is not None and bool(self.alarm_channel.get_busy())

    def sysaudio_play(
        self,
        event: SysAudioEvent = SysAudioEvent.NONE_,
        block: bool = False,
        repeat: int = 0,
    ) -> None:
        """PLays built-in sound. See folder 'systemsounds'"""
        if self.get_volume() <= 0:
            return
        if event is None or event == SysAudioEvent.NONE_:
            return
        key = event.name.lower()
        if key not in self.systemsounds:
            logger.warning(
                "key '%s' was not found in AudioCtrl.systemsounds. "
                "Make sure there is an audio file with that name "
                "in folder '%s'",
                key,
                self.__systemsoundsdir,
            )
            return
        sound = mixer.Sound(self.systemsounds[key])
        sound.set_volume(self.get_volume())
        mixer.find_channel(force=True).play(sound, loops=repeat)
        if block:
            while mixer.get_busy():
                time.sleep(0.1)

    def stop_all_audio(self) -> None:
        """Stops all audio playback."""
        mixer.stop()

    def prepare_recording(self) -> None:
        """Forgets the previous recording and stops its playback.
        Call on the main thread before start_recording()."""
        self.current_filepath = None
        self.rec_time = None
        self.rec_channel.stop()  # Stop playing audio

    def start_recording(self) -> bool:
        """Blocking: plays the REC_STARTED cue to the end (so it is not
        recorded), then starts recording in AudioRec's own thread. Records
        until stop_recording() is called or 30(DEFAULT) seconds have passed.
        Run it on a worker.

        :Return: bool: True if recording started, False otherwise
        """
        logger.debug("starting recording")
        self.sysaudio_play(SysAudioEvent.REC_STARTED, block=True)
        AudioCtrl.__remove_files_in_dir(self.__tempdir)
        return self.rec_ctrl.rec()

    def is_recording(self) -> bool:
        """Are we currently recording?"""
        return self.rec_ctrl.recording

    def stop_recording(self) -> str | None:
        """Blocking (up to 2 s): stops the recording. Run it on a worker.
        Returns the recorded file, or None if nothing was recording."""
        if not self.is_recording():
            return None
        logger.debug("stopping recording...")
        self.rec_ctrl.stop()
        logger.debug("recording stopped")
        return self.rec_ctrl.rec_filename

    def recording_stopped(self, filename: str | None) -> None:
        """Makes the stopped recording current. Call on the main thread
        with the result of stop_recording()."""
        if filename is None:
            return
        self.current_filepath = filename
        self.rec_time = datetime.datetime.now()

    def render_effect(self, infile: str, effect: EffectType) -> str:
        """Blocking: writes infile with the effect applied to a new temp
        file and returns its path. Run it on a worker."""
        outfile = self.__build_tmp_filename(suffix="effect.tmp.wav")
        outfile = str(self.__tempdir.joinpath(outfile).resolve())
        return self.effect_ctrl.do_effect(str(infile), effect, outfile)

    def effect_done(self, path: str | None) -> None:
        """Makes the rendered effect current and plays it. Call on the
        main thread with the result of render_effect()."""
        self.current_filepath = path
        self._play_tmp_rec()

    def save_rec_to_hwswitch(self, switch: int) -> str:
        """Moves audio file to storage.
        This effectively links audio file to HwCtrl button."""
        if (
            self.rec_time is not None
            and datetime.datetime.now() >= self.rec_time + datetime.timedelta(minutes=1)
        ):
            self.rec_time = None
            self.current_filepath = None
        if self.current_filepath is None or self.current_filepath == "":
            self.sysaudio_play(SysAudioEvent.FAILED)
            logger.error("Could not assign audio to Btn because soundfile path empty")
            raise AudioFilePathEmptyException(
                "Could not assign audio to Btn because soundfile path empty"
            )
        destfile = self.__storagedir / f"btn_{switch}.wav"
        if self.file_exist(destfile):
            AudioCtrl.__remove_file(destfile)
        f = Path(self.current_filepath)
        self.current_filepath = f.rename(self.__storagedir / destfile.name)
        self.current_filepath = None
        self.rec_time = None
        return True

    @staticmethod
    def _read_wav_file(filename: Path) -> str:
        """Reads the whole wav file and encodes the audio as base64.

        Args:
            filename (str): path to file
        returns:
            str: Base64 encoded audio data decoded as utf-8
        """
        with open(str(filename), "rb") as file:
            file_bytes = file.read()
            # Encode the raw bytes into Base64, and convert to string
            encoded_data = base64.b64encode(file_bytes).decode("utf-8")
            return encoded_data

    def _play_tmp_rec(self) -> None:
        if self.current_filepath is None:
            self.sysaudio_play(SysAudioEvent.FAILED)
            return
        if not AudioCtrl.file_exist(self.current_filepath):
            self.sysaudio_play(SysAudioEvent.FAILED)
            return
        self.rec_channel.stop()
        try:
            sound = mixer.Sound(self.current_filepath)
            sound.set_volume(self.get_volume())
            self.rec_channel.play(sound, loops=0)
        except Exception:
            logger.exception("Playing the recording failed")
            self.sysaudio_play(SysAudioEvent.FAILED)
            self.current_filepath = None
            self.rec_ctrl.recording = False
            self.rec_time = None
            self.rec_ctrl.stop()
            self.rec_ctrl.rec_filename = None

    def __playback_monitor(self) -> None:
        while not self._stop_event.is_set():
            if mixer.get_busy() and not self.playing:
                self.playing = True
                self.on_play_change(True)
            elif not mixer.get_busy() and self.playing:
                self.playing = False
                self.on_play_change(False)
            self._stop_event.wait(0.3)

    def __build_tmp_filename(self, suffix) -> str:
        prefix = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
        rndstr = "".join(random.choice(string.ascii_lowercase) for i in range(8))
        filename = "_".join([prefix, rndstr, suffix])
        return filename

    def __load_sound_library(self, directory: Path) -> int:
        """Scans the directory and loads all WAV files
        as a pygame.mixer.sound"""
        self.systemsounds = {}
        audio_count = 0
        for x in directory.iterdir():
            if x.is_file() and x.name.endswith(".wav"):
                self.systemsounds.update({x.stem.lower(): mixer.Sound(x.resolve())})
                audio_count += 1
        return audio_count

    @staticmethod
    def file_exist(filepath: str) -> bool:
        """Does file exist?"""
        return Path(filepath).exists()

    @staticmethod
    def __clamp(num: int, min_value: int, max_value: int) -> int:
        """Clamp function limits a value to a given range"""
        return max(min(num, max_value), min_value)

    @staticmethod
    def __create_dir(*args: Path) -> None:
        for x in args:
            if Path(x).is_dir():
                x.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def __remove_file(p: str) -> None:
        """Deletes a single file. If the file does not
        exist no error is thrown."""
        if Path(p).exists():
            p.unlink(missing_ok=True)

    @staticmethod
    def __remove_files_in_dir(folder: Path) -> None:
        try:
            [f.unlink(missing_ok=True) for f in folder.glob("*") if f.is_file()]
        except OSError as e:
            logger.exception(e)


class AudioFilePathEmptyException(Exception):
    """
    Raised during IO operations if self.current_filepath is None or empty
    """
