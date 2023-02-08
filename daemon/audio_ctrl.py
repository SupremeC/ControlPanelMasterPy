from pathlib import Path
import shutil
import logging
import threading
from daemon.audio_rec import AudioRec
from daemon.audio_effects import AudioEffect, EffectType


logger = logging.getLogger('daemon.audioCtrl')


class AudioCtrl:
    __rootdir: Path
    __tempdir: Path
    __storagedir: Path
    __effects_running: bool
    current_filepath: str
    max_rectime_seconds: int
    rec_ctrl: AudioRec
    effect_ctrl: AudioEffect

    def __init__(self):
        self.__effects_running: bool = False
        self.__rootdir = Path.cwd()
        self.__tempdir = self.__rootdir / "tmp_rec"
        self.__storagedir = self.__rootdir / "sounds"
        self.current_filepath = None

        AudioCtrl.__create_dir(self.__tempdir)
        AudioCtrl.__create_dir(self.__storagedir)
        self.rec_ctrl = AudioRec(dir = self.__tempdir)
        self.effect_ctrl = AudioEffect()

    def start_recording(self) -> bool:
        '''Returns immediately. Recording is done in a new thread.
        Records until StopRecording is called or 30(DEFAULT) seconds has passed.'''
        self.current_filepath = None
        AudioCtrl.__remove_files_in_dir(self.__tempdir.absolute)
        return self.rec_ctrl.rec()
    
    def is_recording(self) -> bool:
            return self.rec_ctrl.recording

    def stop_recording(self) -> None:
        '''Signals 'Stop' and blocks until recording has stopped.
        The resulting .wave-file can be found at <AudioCtrl.current_filepath>'''
        self.rec_ctrl.stop()
        self.current_filepath = self.rec_ctrl.rec_filename

    def apply_effect(self, p_effect: EffectType) -> None:
        if self.__effects_running:
            logger.warn("An effect is already being applied. NOOP")
            return
        if self.current_filepath is None:
            logger.error("Could not apply effect to audio because sound not defined")
            return
        effectthread = threading.Thread(
            target=self.__wrapped_apply_effect,
            kwargs=dict(
                infile=self.current_filepath,
                effect=p_effect,
            ),
        )
        effectthread.start()

    def abort(self) -> None:
        if self.is_recording(): self.stop_recording()

    def save_to_hwSwitch(self, switch: int) -> str:
        if self.current_filepath is None or self.current_filepath == "":
            logger.error("Could not assign audio to Btn because soundfile not defined")
        destfile = self.__storagedir / f"btn_{switch}.wave"
        if( self.current_filepath == destfile):
            return
        if self.file_exist(destfile):
            AudioCtrl.__removeFile(destfile)
            f = Path(self.current_filepath)
            self.current_filepath = f.rename(self.__storagedir / f.name)
            return self.current_filepath
        else:
            logger.error("Could not assign audio to Btn because sound does not exist")

    def __wrapped_apply_effect(self, infile, effect) -> None:
        self.__effects_running = True
        self.current_filepath = self.effect_ctrl.do_effect(infile, effect)
        AudioCtrl.__effect_on_done()

    def __effect_on_done(self) -> None:
        self.__effects_running = False

    
    def file_exist(filepath: str) -> bool:
        return Path(filepath).exists()
    
    def __create_dir(dir_name: Path) -> None:
        dir_name.mkdir(parents=True, exist_ok=True)

    def __removeFile(p: str) -> None:
        '''Deletes a single file. If the file does not
        exist no error is thrown.'''
        if Path(p).exists(): p.unlink(missing_ok=True)

    def __remove_files_in_dir(dir: Path) -> None:
        [f.unlink() for f in dir.glob("*") if f.is_file()]

        
