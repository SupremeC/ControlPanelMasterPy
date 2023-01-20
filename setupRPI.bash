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


# Audio effects
pip install pedalboard

# setserial to check and use serial ports from bash
sudo apt install setserial

#Console "GUI"
pip install "textual[dev]"
pip install rich

#SERIAL (with COBS encoding)
pip install pyserial
pip install cobs

#Set audio output to 3.5mm jack
amixer cset numid=3 1

#List audio devices
arecord --list-devices