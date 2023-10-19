"""AudioCtrl"""

import datetime
from pathlib import Path
import random
import string
import threading
from typing import Callable
import logging
from pygame import mixer
from daemon.audio_rec import AudioRec
from daemon.audio_effects import AudioEffect, EffectType
import daemon.global_variables

logger = logging.getLogger("daemon.audioCtrl")


class AudioCtrl:
    """AudioCtrl

    Supports:
    ---
     - Recording audio
     - Playing audio
     - Apply effects to audio files
    """

    systemsounds: dict = None
    effects_running: bool
    current_filepath: str
    max_rectime_seconds: int = 30
    rec_ctrl: AudioRec
    effect_ctrl: AudioEffect
    __tempdir: Path = None
    __storagedir: Path = None
    __systemsoundsdir: Path = None
    __master_volume: int = 20

    def __init__(self):
        root = daemon.global_variables.root_path.resolve()
        self.__tempdir = root.joinpath("daemon/tmp_rec")
        self.__storagedir = root.joinpath("daemon/sounds")
        self.__systemsoundsdir = root.joinpath("daemon/systemsounds")
        self.__create_dir(self.__tempdir, self.__storagedir, self.__systemsoundsdir)

        # init() channels refers to mono vs stereo, not playback Channel object
        mixer.init(48000, -16, channels=1, buffer=1024)
        mixer.set_num_channels(8)
        mixer.set_reserved(1)
        self.set_volume(50)  # 0-100
        audioclipsfound = self.__load_sound_library(self.__systemsoundsdir)
        print(f"Found {audioclipsfound} of audio clips")

    def set_volume(self, volume: int) -> None:
        """Sets the volume for all sounds

        Args:
            volume (int): 0-100
        """
        volume = AudioCtrl.__clamp(volume, 0, 100)
        self.__master_volume = volume / 100

    def recsaved_play(self, pin: int = None) -> None:
        """PLays sound linked to pinNr"""
        if pin is None:
            logger.warning("No pinNr provided to AudioCtrl.recsaved_play(). NOOP")
            return
        sound = mixer.Sound(self.__storagedir.joinpath(f"{pin}.wav"))
        sound.set_volume(self.__master_volume)
        mixer.find_channel(force=True).play(sound, loops=0)

    def sysaudio_play(self, name: str = None) -> None:
        """PLays built-in sound. See folder 'systemsounds'"""
        if name is None:
            logger.warning(
                "No systemsound name provided to AudioCtrl.sys_audio_play(). NOOP"
            )
            return
        sound = mixer.Sound(self.systemsounds[name])
        sound.set_volume(self.__master_volume)
        mixer.find_channel(force=True).play(sound, loops=0)

    def stop_all_audio(self) -> None:
        """Stops all audio playback."""
        mixer.stop()

    def start_recording(self) -> bool:
        """Returns immediately. Recording is done in a new thread.
        Records until StopRecording is called or 30(DEFAULT) seconds has passed.

        :Return: bool: True if recording started, False otherwise
        """
        self.current_filepath = None
        AudioCtrl.__remove_files_in_dir(self.__tempdir)
        return self.rec_ctrl.rec()

    def is_recording(self) -> bool:
        """Are we currently recording"""
        return self.rec_ctrl.recording

    def stop_recording(self) -> None:
        """Signals 'Stop' and blocks until recording has stopped.
        The resulting .wave-file can be found at <AudioCtrl.current_filepath>"""
        self.rec_ctrl.stop()
        self.current_filepath = self.rec_ctrl.rec_filename

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

    def save_to_hwswitch(self, switch: int) -> str:
        """Moves audio file to storage.
        This effectivly links audio file to HwCtrl button."""
        if self.current_filepath is None or self.current_filepath == "":
            logger.error("Could not assign audio to Btn because soundfile path empty")
            raise AudioFilePathEmptyException(
                "Could not assign audio to Btn because soundfile path empty"
            )
        destfile = self.__storagedir / f"btn_{switch}.wave"
        if self.current_filepath == destfile:
            return self.current_filepath
        if self.file_exist(destfile):
            AudioCtrl.__remove_file(destfile)
        f = Path(self.current_filepath)
        self.current_filepath = f.rename(self.__storagedir / f.name)
        return self.current_filepath

    def __wrapped_apply_effect(
        self, infile, effect, callback: Callable[[str], None] = None
    ) -> None:
        self.effects_running = True
        outfile = str(self.__build_tmp_filename(suffix="effect.tmp"))
        self.current_filepath = self.effect_ctrl.do_effect(infile, effect, outfile)
        self.__effect_on_done()
        if callback is not None:
            callback(self.current_filepath)

    def __effect_on_done(self) -> None:
        self.effects_running = False

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
                self.systemsounds.update({x.name: mixer.Sound(x.resolve())})
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
        [f.unlink(missing_ok=True) for f in folder.glob("*") if f.is_file()]


class AudioFilePathEmptyException(Exception):
    """
    Raised during IO operations if self.current_filepath is None or empty
    """


if __name__ == "__main__":
    app = AudioCtrl()
    while True:
        answer = input("1. Play music\n2. stop\n3.Play 8bitcoin\n4. Exit")
        if answer == "1":
            app.sysaudio_play("2m10s_piano.wav")
        elif answer == "2":
            app.stop_all_audio()
        elif answer == "3":
            app.sysaudio_play("1s_8bitcoin.wav")
        elif answer in ["q", "Q", "4"]:
            exit()
