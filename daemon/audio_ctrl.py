"""AudioCtrl"""
from pathlib import Path
from typing import Callable
import os
import shortuuid
import logging
import threading
from daemon.audio_rec import AudioRec
from daemon.audio_effects import AudioEffect, EffectType
import pygame


logger = logging.getLogger('daemon.audioCtrl')


class AudioCtrl:
    """AudioCtrl"""
    __rootdir: Path
    __tempdir: Path
    __storagedir: Path
    effects_running: bool
    current_filepath: str
    max_rectime_seconds: int
    rec_ctrl: AudioRec
    effect_ctrl: AudioEffect

    def __init__(self):
        self.effects_running: bool = False
        self.__rootdir = Path(os.path.realpath(__file__)).parent
        self.__tempdir = self.__rootdir / "tmp_rec"
        self.__storagedir = self.__rootdir / "sounds"
        self.current_filepath = None

        AudioCtrl.__create_dir(self.__tempdir)
        AudioCtrl.__create_dir(self.__storagedir)
        self.rec_ctrl = AudioRec(folder = self.__tempdir)
        self.effect_ctrl = AudioEffect()
        # init() channels refers to mono vs stereo, not playback Channel object
        pygame.mixer.init(size = -16, channels = 1, buffer = 2**12)
        pygame.mixer.set_num_channels(8)
        pygame.mixer.set_reserved(1)
        self.channelClip =  pygame.mixer.Channel(0)

    def bckgrnd_play(self) -> None:
        chnl = pygame.mixer.findChannel()
        chnl.play(mySound, loops=0)
        pass

    def clip_play(self) -> int:
        self.channelClip.play(mySound, loops=0)
        pass

    def clip_stop(self) -> None:
        self.channelClip.stop()
        pass

    def stop_all_audio_play(self) -> None:
        pygame.mixer.stop()

    def start_recording(self) -> bool:
        '''Returns immediately. Recording is done in a new thread.
        Records until StopRecording is called or 30(DEFAULT) seconds has passed.
        
        :Return: bool: True if recording started, False otherwise
        '''
        self.current_filepath = None
        AudioCtrl.__remove_files_in_dir(self.__tempdir)
        return self.rec_ctrl.rec()

    def is_recording(self) -> bool:
        """Are we currently recording"""
        return self.rec_ctrl.recording

    def stop_recording(self) -> None:
        '''Signals 'Stop' and blocks until recording has stopped.
        The resulting .wave-file can be found at <AudioCtrl.current_filepath>'''
        self.rec_ctrl.stop()
        self.current_filepath = self.rec_ctrl.rec_filename

    def apply_effect(self, p_effect: EffectType, p_callback: Callable[[str], None] = None) -> bool:
        '''Returns immediately. Effect processing is done in a new thread.
        :Return: bool: True if effectProcessing started, False otherwise
        '''
        if self.effects_running:
            logger.warning("An effect is already being applied. NOOP")
            return False
        if self.current_filepath is None:
            logger.error("Could not apply effect to audio because sound not defined")
            return False
        effectthread = threading.Thread(
            target=self.__wrapped_apply_effect,
            kwargs=dict(
                infile=self.current_filepath,
                effect=p_effect,
                callback=p_callback
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
                "Could not assign audio to Btn because soundfile path empty")
        destfile = self.__storagedir / f"btn_{switch}.wave"
        if self.current_filepath == destfile:
            return self.current_filepath
        if self.file_exist(destfile):
            AudioCtrl.__remove_file(destfile)
        f = Path(self.current_filepath)
        self.current_filepath = f.rename(self.__storagedir / f.name)
        return self.current_filepath

    def __wrapped_apply_effect(self, infile,effect,
                               callback: Callable[[str], None] = None) -> None:
        self.effects_running = True
        outfile = str(self.__build_tmp_filename(prefix="tmp_effect"))
        self.current_filepath = self.effect_ctrl.do_effect(infile, effect, outfile)
        self.__effect_on_done()
        if callback is not None:
            callback(self.current_filepath)

    def __effect_on_done(self) -> None:
        self.effects_running = False


    def __build_tmp_filename(self, prefix):
        return Path(self.__tempdir, f"{prefix}_{shortuuid.uuid()}.wav")

    @staticmethod
    def file_exist(filepath: str) -> bool:
        """Does file exist?"""
        return Path(filepath).exists()

    @staticmethod
    def __create_dir(dir_name: Path) -> None:
        dir_name.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def __remove_file(p: str) -> None:
        '''Deletes a single file. If the file does not
        exist no error is thrown.'''
        if Path(p).exists():
            p.unlink(missing_ok=True)

    @staticmethod
    def __remove_files_in_dir(folder: Path) -> None:
        [f.unlink() for f in folder.glob("*") if f.is_file()]


class AudioFilePathEmptyException(Exception):
    """
    Raised when an unknown or unsupported EffectType
    is used.
    """