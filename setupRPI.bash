sudo apt-get update
sudo apt-get upgrade

pip install pedalboard
pip install "textual[dev]"
pip install rich

#Set audio output to 3.5mm jack
amixer cset numid=3 1

#List audio devices
arecord --list-devices