from enum import IntEnum
import logging
import wave
import pedalboard
from pedalboard import Pedalboard, Chorus, Delay, Bitcrush
from pedalboard import Plugin, Reverb, Compressor, Gain
from pedalboard import Phaser, LadderFilter, Distortion
from pedalboard.io import AudioFile
import numpy as np
from pydub import AudioSegment
import pyrubberband as pyrb
import soundfile as sf


class EffectType (IntEnum):
    NONE_ = 0,
    REVERB = 1
    PHASER = 2
    REVERSE = 3
    BITCRUSH = 4
    PITCHLOWER = 5
    PITCHHIGHER = 6
    TIMECOMPRESS = 7
    TIMESTRETCH = 8



class AudioEffect:
    def __init__(self) -> None:
        self.logger = logging.getLogger('daemon.AudioEffect')

    def do_effect(self, infile: str, effect: EffectType, outfile: str) -> str:
        if effect == EffectType.NONE_:
            return infile
        elif effect == EffectType.REVERB:
            return self.reverb(infile, outfile)
        elif effect == EffectType.REVERSE:
            return self.reverse(infile, outfile)
        elif effect == EffectType.TIMECOMPRESS:
            return self.time_stretch(infile, outfile, 0.5)
        elif effect == EffectType.TIMESTRETCH:
            return self.time_stretch(infile, outfile, 1.5)
        elif effect == EffectType.PITCHHIGHER:
            return self.pitch(infile, outfile, 3)
        elif effect == EffectType.PITCHLOWER:
            return self.pitch(infile, outfile, -3)
        elif effect == EffectType.PHASER:
            return self.phaser(infile, outfile)
        elif effect == EffectType.BITCRUSH:
            return self.bitcrush(infile, outfile)
        else:
            self.logger.error(f"EffectType not supported. Type == {effect}")
            raise Exception(f"EffectType not supported. Type == {effect}")

    def time_stretch(self, infile: str, outfile: str, stretch: float) -> str:
        y, sr = sf.read(infile)
        yw = pyrb.time_stretch(y, sr, stretch)
        sf.write(outfile, yw, sr, format='wav')
        return outfile

    def pitch(self, infile: str, outfile: str, pitch: float) -> str:
        y, sr = sf.read(infile)
        yw = pyrb.pitch_shift(y, sr, pitch)
        sf.write(outfile, yw, sr, format='wav')
        return outfile

    def reverb(self, infile: str, outfile: str) -> str:
        board = Pedalboard([Chorus(), Reverb(room_size=0.25)])
        self._applyBoard(board, infile, outfile)
        return outfile
    
    def phaser(self, infile: str, outfile: str) -> str:
        board = Pedalboard([Phaser(feedback=0, depth=.8, rate_hz=1.2, mix=.7)])
        self._applyBoard(board, infile, outfile)
        return outfile

    def reverse(infile, outfile) -> str:
        with wave.open(infile, "rb") as input_wave:
            # Read the wave file
            samples = np.frombuffer(input_wave.readframes(input_wave.getnframes()), dtype=np.int16)
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
        board = Pedalboard([
            LadderFilter(mode=LadderFilter.Mode.HPF24, cutoff_hz=500,  resonance=0.75), 
            Gain(gain_db=10),
            Bitcrush(5),
            Distortion(26), Gain(gain_db=-22)
            ])
        self._applyBoard(board, infile, outfile)
        return outfile
    
    def _applyBoard(self, board, infile, outfile) -> None:
        try:
            # Open an audio file for reading, just like a regular file:
            with AudioFile(infile) as f:
            # with AudioFile('/home/pi/Source/ControlPanelMasterPy/ControlPanelMasterPy/playground/music.wav') as f:

                # Open an audio file to write to:
                with AudioFile(outfile, 'w', f.samplerate, f.num_channels) as o:

                    # Read one second of audio at a time, until the file is empty:
                    while f.tell() < f.frames:
                        chunk = f.read(int(f.samplerate))

                        # Run the audio through our pedalboard:
                        effected = board(chunk, f.samplerate, reset=False)

                        # Write the output to our output file:
                        o.write(effected)
                        o.flush()
            a = 434
        except Exception as e:
            self.logger.error(e)
