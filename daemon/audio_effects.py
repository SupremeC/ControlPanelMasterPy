"""Audio Effect"""

from enum import IntEnum
import logging
import wave
import pedalboard
from pedalboard import Pedalboard, Chorus, Delay, Bitcrush
from pedalboard import Plugin, Reverb, Compressor, Gain
from pedalboard import Phaser, LadderFilter, Distortion, time_stretch
from pedalboard.io import AudioFile
import numpy as np
import pyrubberband as pyrb
import soundfile as sf


class EffectType(IntEnum):
    """EffectType. Can be applied to sound clip
    using AudioEffect class"""

    NONE_ = 0
    REVERB = 1
    PHASER = 2
    REVERSE = 3
    BITCRUSH = 4
    PITCHLOWER = 5
    PITCHHIGHER = 6
    TIMECOMPRESS = 7
    TIMESTRETCH = 8


class AudioEffect:
    """AudioEffect. Can apply audio effects to audio files"""

    def __init__(self) -> None:
        self.logger = logging.getLogger("daemon.AudioEffect")

    def do_effect(self, infile: str, effect: EffectType, outfile: str) -> str:
        """Applies an effect to an audio file

        Args:
            infile (str): path to audio file.
            effect (EffectType): the ffect to apply. See enum.
            outfile (str): Path to new audio file with effect applied.

        Raises:
            AudioEffectTypeException: if unknown or unsupported.

        Returns:
            str: Path to new audio file with effect applied.
        """
        if effect == EffectType.NONE_:
            return infile
        elif effect == EffectType.REVERB:
            return self.reverb(infile, outfile)
        elif effect == EffectType.REVERSE:
            return self.reverse(infile, outfile)
        elif effect == EffectType.TIMECOMPRESS:
            return self.time_stretchf(infile, outfile, 0.5)
        elif effect == EffectType.TIMESTRETCH:
            return self.time_stretchf(infile, outfile, 1.5)
        elif effect == EffectType.PITCHHIGHER:
            return self.pitch(infile, outfile, 3)
        elif effect == EffectType.PITCHLOWER:
            return self.pitch(infile, outfile, -3)
        elif effect == EffectType.PHASER:
            return self.phaser(infile, outfile)
        elif effect == EffectType.BITCRUSH:
            return self.bitcrush(infile, outfile)
        else:
            self.logger.error("EffectType not supported. Type == %s", effect)
            raise AudioEffectTypeException(
                f"EffectType not supported. Type == {effect}"
            )

    # TODO - function has same name as pedalboard function 'time_stretch'
    # rename!
    def time_stretchf(self, infile: str, outfile: str, stretch: float) -> str:
        """TODO: Pedalboard have implemented timestrech but cannot make it work
        #  - Time_stretch is a function instead of class (expected)
        # board = Pedalboard([time_stretch(stretch_factor=stretch)])
        # self._applyBoard(board, infile, outfile)
        # return outfile"""
        y, sr = sf.read(infile)
        yw = pyrb.time_stretch(y, sr, stretch)
        sf.write(outfile, yw, sr, format="wav")
        return outfile

    def pitch(self, infile: str, outfile: str, pitch: float) -> str:
        """Pitch effect"""
        y, sr = sf.read(infile)
        yw = pyrb.pitch_shift(y, sr, pitch)
        sf.write(outfile, yw, sr, format="wav")
        return outfile

    def reverb(self, infile: str, outfile: str) -> str:
        """Reverb effect"""
        board = Pedalboard(
            [
                Chorus(),
                Reverb(room_size=0.25),
                Gain(gain_db=10),
            ]
        )
        self._apply_board(board, infile, outfile)
        return outfile

    def phaser(self, infile: str, outfile: str) -> str:
        """Phaser effect"""
        board = Pedalboard(
            [Phaser(feedback=0, depth=0.8, rate_hz=1.2, mix=0.7), Gain(gain_db=10)]
        )
        self._apply_board(board, infile, outfile)
        return outfile

    def reverse(self, infile, outfile) -> str:
        """Reverse effect"""
        with wave.open(infile, "rb") as input_wave:
            # Read the wave file
            samples = np.frombuffer(
                input_wave.readframes(input_wave.getnframes()), dtype=np.int16
            )
            sample_rate = input_wave.getframerate()

            # Reverse the samples
            reversed_samples = samples[::-1].tobytes()

            # Write the reversed samples to a new wave file
            with wave.open(outfile, "wb") as output_wave:
                output_wave.setnchannels(input_wave.getnchannels())
                output_wave.setsampwidth(input_wave.getsampwidth())
                output_wave.setframerate(sample_rate)
                output_wave.writeframes(reversed_samples)
        return outfile

    def bitcrush(self, infile, outfile) -> str:
        """Bitcrush effect"""
        board = Pedalboard(
            [
                LadderFilter(
                    mode=LadderFilter.Mode.HPF24, cutoff_hz=500, resonance=0.75
                ),
                Gain(gain_db=10),
                Bitcrush(5),
                Distortion(26),
                Gain(gain_db=-22),
            ]
        )
        self._apply_board(board, infile, outfile)
        return outfile

    def _apply_board(self, board, infile, outfile) -> None:
        """Applies Pedalboard effect and writes new audio to file"""
        try:
            # Open an audio file for reading, just like a regular file:
            with AudioFile(infile) as f:
                # Open an audio file to write to:
                with AudioFile(outfile, "w", f.samplerate, f.num_channels) as o:
                    # Read one second of audio at a time, until the file is empty:
                    while f.tell() < f.frames:
                        chunk = f.read(int(f.samplerate))

                        # Run the audio through our pedalboard:
                        effected = board(chunk, f.samplerate, reset=False)

                        # Write the output to our output file:
                        o.write(effected)
                        o.flush()
        except Exception as e:
            self.logger.error(e)


class AudioEffectTypeException(Exception):
    """
    Raised when an unknown or unsupported EffectType
    is used.
    """
