import sounddevice as sd
import soundfile as sf

# Play audio from command line
# aplay music.wav

# Set volume
# amixer set Master 100%
# amixer set Master mute
# amixer set Master unmute
# amixer sset Mic 100%
# amixer set Capture 100%


filename = (
    "/home/david/source/cpPy/ControlPanelMasterPy/daemon/systemsounds/2m10s_piano.wav"
)
# Extract data and sampling rate from file
data, fs = sf.read(filename, dtype="float32")
sd.play(data, fs)
status = sd.wait()  # Wait until file is done playing
