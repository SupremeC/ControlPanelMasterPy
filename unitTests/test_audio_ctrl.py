import unittest   # noqa
from datetime import datetime, timedelta
import time
from daemon.audio_ctrl import AudioCtrl
from daemon.audio_rec import AudioRec
from daemon.audio_effects import AudioEffect, EffectType
import pathlib
from unittest.mock import Mock

class AnyStringWith(str):
    def __eq__(self, other):
        return self in other

class Test_AudioCtrl(unittest.TestCase):
    def test_init_correctDefaultValues(self):
        # arrange
        ac = AudioCtrl()

        # assert (default values)
        self.assertTrue(ac.current_filepath is None)
        self.assertFalse(ac.is_recording())
        self.assertFalse(ac.effects_running)
        self.assertIsInstance(ac.rec_ctrl, AudioRec)
        self.assertIsInstance(ac.effect_ctrl, AudioEffect)

    def test_rec_singleRec(self):
        # arrange
        ac = AudioCtrl()

        # act
        recstarted = ac.start_recording()
        time.sleep(.2)
        ac.stop_recording()

        # assert (default values)
        self.assertTrue(recstarted)
        self.assertTrue(ac.current_filepath is not None)
        self.assertTrue(pathlib.Path(ac.current_filepath).exists())
        self.assertTrue(pathlib.Path(ac.current_filepath).suffix == ".wav")

    def test_rec_doubleRec(self):
        # arrange
        ac = AudioCtrl()

        # act
        recstarted = ac.start_recording()
        time.sleep(.1)
        ac.stop_recording()

        recstarted2 = ac.start_recording()
        time.sleep(.1)
        ac.stop_recording()

        # assert (default values)
        self.assertTrue(recstarted)
        self.assertTrue(recstarted2)
        self.assertTrue(ac.current_filepath is not None)
        self.assertTrue(pathlib.Path(ac.current_filepath).exists())
        self.assertTrue(pathlib.Path(ac.current_filepath).suffix == ".wav")

    def test_effect_reverseEffect(self):
        # arrange
        ac = AudioCtrl()

        # act
        recstarted = ac.start_recording()
        time.sleep(2)
        ac.stop_recording()
        time.sleep(.1)
        ac.apply_effect(EffectType.REVERSE)
        while ac.effects_running:
            time.sleep(.001)
        
        # assert (default values)
        self.assertTrue(recstarted)
        self.assertTrue(ac.current_filepath is not None)
        self.assertTrue(pathlib.Path(ac.current_filepath).exists())
        self.assertTrue(pathlib.Path(ac.current_filepath).suffix == ".wav")
        a = 44

    def test_effect_callback(self):
        # arrange
        ac = AudioCtrl()
        fn_mock_PlaySound = Mock()

        # act
        recstarted = ac.start_recording()
        time.sleep(.1)
        ac.stop_recording()
        while(ac.is_recording()):
            time.sleep(.001)
        ac.apply_effect(EffectType.REVERSE, fn_mock_PlaySound)
        while ac.effects_running:
            time.sleep(.001)

        # assert (default values)
        fn_mock_PlaySound.assert_called_once_with(AnyStringWith(".wav"))
