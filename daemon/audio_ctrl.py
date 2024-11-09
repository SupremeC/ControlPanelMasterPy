"""AudioCtrl"""

import datetime
import logging
import random
import shutil
import string
import threading
import base64
from pathlib import Path
import time
from typing import Callable
from enum import unique, IntEnum
from pygame import mixer
from daemon.audio_rec import AudioRec
from daemon.audio_effects import AudioEffect, EffectType
import daemon.global_variables
from pydub import AudioSegment
from pydub.playback import play
import io

logger = logging.getLogger("daemon.audioCtrl")


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
    effects_running: bool = False
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
        self.alarm_sound: mixer.Sound | None = None

        # init() 'channels' refers to mono vs stereo, not playback Channel object
        mixer.init(48000, -16, channels=1, buffer=1024)
        mixer.set_num_channels(6)
        mixer.set_reserved(1)
        mixer.get_busy
        self.rec_channel = mixer.Channel(0)
        audioclipsfound = self.__load_sound_library(self.__systemsoundsdir)
        self.enable_sound(True)
        self.set_volume(50)  # 0-100

        print(f"Found {audioclipsfound} of audio clips")

        self._running = True  # Internal flag to control the thread's lifecycle
        self._thread = threading.Thread(target=self.__playback_monitor)
        self._thread.daemon = True
        self._thread.start()

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
        """Sets the volume for all sounds

        Args:
            volume (int): 0-100
        """
        volume = AudioCtrl.__clamp(volume, 0, 100)
        self.__master_volume = volume / 100
        self.sysaudio_play(SysAudioEvent.VOLUME_CHANGE)

    def get_volume(self) -> int:
        return self.__master_volume if self.__sound_on else 0

    def enable_sound(self, on: bool) -> None:
        self.__sound_on = on

    def recsaved_play(self, pin: int = None) -> None:
        if not self.__sound_on:
            return
        """Plays sound linked to pinNr"""
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

    def play_bytes(self, p_bytes) -> None:
        """Blocking"""
        audio_data = AudioSegment.from_file(io.BytesIO(p_bytes), format="mp3")
        play(audio_data)

    def stop_alarm(self) -> None:
        if self.alarm_sound is not None:
            self.alarm_sound.stop()
            self.alarm_sound = None

    def sysaudio_play(
        self,
        event: SysAudioEvent = SysAudioEvent.NONE_,
        block: bool = False,
        repeat: int = 0,
    ) -> None:
        """PLays built-in sound. See folder 'systemsounds'"""
        if not self.__sound_on:
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
        if event == SysAudioEvent.ALARM:
            self.alarm_sound = sound
        if block:
            while mixer.get_busy():
                time.sleep(0.1)

    def stop_all_audio(self) -> None:
        """Stops all audio playback."""
        mixer.stop()

    def start_recording(self) -> bool:
        """Returns immediately. Recording is done in a new thread.
        Records until StopRecording is called or
        30(DEFAULT) seconds has passed.

        :Return: bool: True if recording started, False otherwise
        """
        self.current_filepath = None
        self.rec_time = None
        self.rec_channel.stop()  # Stop playing audio
        AudioCtrl.__remove_files_in_dir(self.__tempdir)
        if not self.rec_ctrl.rec():
            self.sysaudio_play(SysAudioEvent.REC_COULD_NOT_REC)
            return False
        return True

    def is_recording(self) -> bool:
        """Are we currently recording?"""
        return self.rec_ctrl.recording

    def stop_recording(self) -> None:
        """Signals 'Stop' and blocks until recording has stopped.
        The resulting .wave-file can be found at <AudioCtrl.current_filepath>"""
        self.rec_ctrl.stop()
        self.current_filepath = self.rec_ctrl.rec_filename
        self.rec_time = datetime.datetime.now()

    def apply_effect(
        self, p_effect: EffectType, p_callback: Callable[[str], None] = None
    ) -> bool:
        """Apply effect to current audio file.
        Returns immediately. Effect processing is done in a new thread.
        :Return: bool: True if effectProcessing started, False otherwise
        """
        if self.effects_running:
            logger.warning("An effect is already being applied. NOOP")
            return False
        if self.current_filepath is None:
            logger.error("Could not apply effect to audio because sound not defined")
            self.sysaudio_play(SysAudioEvent.FAILED)
            return False
        effectthread = threading.Thread(
            target=self.__wrapped_apply_effect,
            kwargs=dict(
                infile=self.current_filepath, effect=p_effect, callback=p_callback
            ),
        )
        effectthread.start()
        self.effects_running = True
        return self.effects_running

    def save_rec_to_hwswitch(self, switch: int) -> str:
        """Moves audio file to storage.
        This effectively links audio file to HwCtrl button."""
        if (
            self.rec_time is not None
            and datetime.now() >= self.rec_time + datetime.timedelta(minutes=1)
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

    def __wrapped_apply_effect(
        self, infile, effect, callback: Callable[[str], None] = None
    ) -> None:
        if self.current_filepath is None:
            self.sysaudio_play(SysAudioEvent.FAILED)
            return
        self.effects_running = True
        outfile = self.__build_tmp_filename(suffix="effect.tmp.wav")
        outfile = str(self.__tempdir.joinpath(outfile).resolve())
        self.current_filepath = self.effect_ctrl.do_effect(str(infile), effect, outfile)
        self.__effect_on_done()
        if callback is not None:
            callback(self.current_filepath)

    def __effect_on_done(self) -> None:
        self.rec_time = datetime.datetime.now()
        self._play_tmp_rec()

    def _play_tmp_rec(self) -> None:
        if self.current_filepath is None:
            self.sysaudio_play(SysAudioEvent.FAILED)
            return
        self.rec_channel.stop()
        sound = mixer.Sound(self.current_filepath)
        self.effects_running = False
        sound.set_volume(self.get_volume())
        self.rec_channel.play(sound, loops=0)

    def __playback_monitor(self) -> None:
        while self._running:
            if mixer.get_busy() and not self.playing:
                self.playing = True
                self.on_play_change(True)
            elif not mixer.get_busy() and self.playing:
                self.playing = False
                self.on_play_change(False)
            time.sleep(0.3)

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
