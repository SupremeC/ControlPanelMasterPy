# from pedalboard import Pedalboard
import pedalboard
from pedalboard import Pedalboard, Chorus, Delay
from pedalboard import Plugin, Reverb, Compressor, Gain
from pedalboard import Phaser, LadderFilter
from pedalboard.io import AudioFile
import wave


import wave
import numpy as np


input_filename = "/home/pi/Source/ControlPanelMasterPy/ControlPanelMasterPy/playground/maleVoice_28s.wav"
output_filename = "/home/pi/Source/ControlPanelMasterPy/ControlPanelMasterPy/playground/output.wav"

def reverse_wave(input_filename, output_filename):
    with wave.open(input_filename, "rb") as input_wave:
        # Read the wave file
        samples = np.frombuffer(input_wave.readframes(input_wave.getnframes()), dtype=np.int16)
        sample_rate = input_wave.getframerate()

        # Reverse the samples
        reversed_samples = samples[::-1].tobytes()

        # Write the reversed samples to a new wave file
        with wave.open(output_filename, "wb") as output_wave:
            output_wave.setnchannels(input_wave.getnchannels())
            output_wave.setsampwidth(input_wave.getsampwidth())
            output_wave.setframerate(sample_rate)
            output_wave.writeframes(reversed_samples)

reverse_wave(input_filename, output_filename)
exit(0)

# Make a Pedalboard object, containing multiple audio plugins:
""" board = Pedalboard([
    Compressor(threshold_db=-50, ratio=25),
    Gain(gain_db=30),
    Chorus(),
    LadderFilter(mode=LadderFilter.Mode.HPF12, cutoff_hz=300),
    Phaser(),
    Reverb(room_size=0.25), 
])
"""

# Chorus - digital, raspi effect with slight echo
# Reverb - heavy echo
# Phaser -  slightly mushy, dragged out 
# LadderFilter(mode=LadderFilter.Mode.HPF12, cutoff_hz=300)  - light thin speech
# board = Pedalboard([Chorus(), Reverb(room_size=0.25)])
board = Pedalboard([Phaser(feedback=0, depth=.8, rate_hz=1.2, mix=.7)])
# board = Pedalboard([LadderFilter(mode=LadderFilter.Mode.HPF24, cutoff_hz=600)])

try:
    # Open an audio file for reading, just like a regular file:
    with AudioFile('/home/pi/Source/ControlPanelMasterPy/ControlPanelMasterPy/playground/maleVoice_28s.wav') as f:
    # with AudioFile('/home/pi/Source/ControlPanelMasterPy/ControlPanelMasterPy/playground/music.wav') as f:

        # Open an audio file to write to:
        with AudioFile('/home/pi/Source/ControlPanelMasterPy/ControlPanelMasterPy/playground/output.wav', 'w', f.samplerate, f.num_channels) as o:

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
    print(str(e))