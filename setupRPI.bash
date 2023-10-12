sudo apt-get update
sudo apt-get upgrade

git config --global user.email "thedeepermeaningofliff@gmail.com"
git config --global user.name "David Berglund"

#Create SSH keys so that I don't need to enter the password every time from VSC
# -> ssh-keygen
# -> rename the public Key to"authorized_keys" and place it in home/pi/.ssh/
# -> get the private key file to ClientComputer and place it in c:\users\david\.ssh\keys
# -> Create a textfile called "config" with this text:
# Host 192.168.150.43
#              HostName 192.168.150.43
#              User pi
#              PreferredAuthentications publickey
#              IdentityFile "/Users/david/.ssh/keys/AxelControlPanel_rsa"


sudo apt-get install -y rubberband-cli

# Audio effects
pip install pedalboard
pip install AudioSegment
pip install PYRubberBand

# Audio playback and mic recording
python3 -m pip install sounddevice
pip install soundfile
pip install shortuuid
pip install librosa
sudo apt-get install python3-numpy
sudo apt-get install libportaudio2
pip install scipy
amixer set Master 95%
amixer set Capture 100%

# reconnect wifi on lost connection (beware of win chars)
# https://gist.github.com/carry0987/372b9fefdd8041d0374f4e08fbf052b1
# dos2unix wifi-reconnect.sh

# setserial to check and use serial ports from bash
sudo apt install setserial

#Console "GUI"
pip install "textual"

#communication between Client and Daemon
pip install Pyro5

#SERIAL (with COBS encoding)
pip install pyserial
pip install cobs

#NOT WORKING: Set audio output to 3.5mm jack
sudo amixer cset numid=3 1

#List audio devices
arecord --list-devices

#list mics
 python3 -m sounddevice