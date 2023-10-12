#!/usr/bin/env python

import unittest
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
    @classmethod
    def setUpClass(cls):
        # arrange
        cls.ac = AudioCtrl()

    def test_init_correctDefaultValues(self):
        # assert (default values)
        self.assertFalse(self.ac.is_recording())
        self.assertFalse(self.ac.effects_running)
        self.assertIsInstance(self.ac.rec_ctrl, AudioRec)
        self.assertIsInstance(self.ac.effect_ctrl, AudioEffect)

    def test_rec_singleRec(self):
        # act
        recstarted = self.ac.start_recording()
        time.sleep(.2)
        self.ac.stop_recording()

        # assert (default values)
        self.assertTrue(recstarted)
        self.assertTrue(self.ac.current_filepath is not None)
        self.assertTrue(pathlib.Path(self.ac.current_filepath).exists())
        self.assertTrue(pathlib.Path(self.ac.current_filepath).suffix == ".wav")
        self.assertFalse(self.ac.is_recording())

    def test_rec_doubleRec(self):
        # act
        recstarted = self.ac.start_recording()
        time.sleep(.1)
        self.ac.stop_recording()

        recstarted2 = self.ac.start_recording()
        time.sleep(.1)
        self.ac.stop_recording()

        # assert (default values)
        self.assertTrue(recstarted)
        self.assertTrue(recstarted2)
        self.assertTrue(self.ac.current_filepath is not None)
        self.assertTrue(pathlib.Path(self.ac.current_filepath).exists())
        self.assertTrue(pathlib.Path(self.ac.current_filepath).suffix == ".wav")

    def test_effect_reverseEffect(self):
        audiofile1 = ""
        audiofile2 = ""

        # act
        recstarted = self.ac.start_recording()
        time.sleep(2)
        self.ac.stop_recording()
        audiofile1 = self.ac.current_filepath
        time.sleep(.1)
        self.ac.apply_effect(EffectType.REVERSE)
        while self.ac.effects_running:
            time.sleep(.001)
        audiofile2 = self.ac.current_filepath
        
        # assert
        self.assertTrue(recstarted)
        self.assertTrue(self.ac.current_filepath is not None)
        self.assertTrue(pathlib.Path(self.ac.current_filepath).exists())
        self.assertTrue(pathlib.Path(self.ac.current_filepath).suffix == ".wav")
        self.assertNotEqual(audiofile1, audiofile2)

    def test_effect_time_stretch(self):
        # act
        self.ac.start_recording()
        time.sleep(2)
        self.ac.stop_recording()
        time.sleep(.1)
        self.ac.apply_effect(EffectType.TIMESTRETCH)
        while self.ac.effects_running:
            time.sleep(.001)
        
        # assert
        self.assertTrue(self.ac.current_filepath is not None)
        self.assertTrue(pathlib.Path(self.ac.current_filepath).exists())
        self.assertTrue(pathlib.Path(self.ac.current_filepath).suffix == ".wav")


    def test_effect_callback(self):
        fn_mock_PlaySound = Mock()

        # act
        recstarted = self.ac.start_recording()
        time.sleep(.1)
        self.ac.stop_recording()
        while(self.ac.is_recording()):
            time.sleep(.001)
        self.ac.apply_effect(EffectType.REVERSE, fn_mock_PlaySound)
        while self.ac.effects_running:
            time.sleep(.001)

        # assert (default values)
        fn_mock_PlaySound.assert_called_once_with(AnyStringWith(".wav"))

    @classmethod
    def tearDownClass(cls):
        pass

if __name__ == '__main__':
    unittest.main()