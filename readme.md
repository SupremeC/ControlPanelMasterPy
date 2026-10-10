<h1 align="center">
  <br />PUT LOGO HERE
</h1>

<h4 align="center">Custom-built Daemon for retro-inspired ControlPanel</h4>

<p align="center">
    <a href="https://github.com/SupremeC/ControlPanelMasterPy/commits/master">
    <img src="https://img.shields.io/github/last-commit/SupremeC/ControlPanelMasterPy.svg?style=flat-square&logo=github&logoColor=white"
         alt="GitHub last commit" /></a>
    <a href="https://github.com/SupremeC/ControlPanelMasterPy/issues">
    <img src="https://img.shields.io/github/issues-raw/SupremeC/ControlPanelMasterPy.svg?style=flat-square&logo=github&logoColor=white"
         alt="GitHub issues" /></a>
    <a href="https://github.com/SupremeC/ControlPanelMasterPy/pulls">
    <img src="https://img.shields.io/github/issues-pr-raw/SupremeC/ControlPanelMasterPy.svg?style=flat-square&logo=github&logoColor=white"
         alt="GitHub pull requests" /></a>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Language-Python-blue" alt="Python" /></a>
   <a href="https://www.tldrlegal.com/license/gnu-general-public-license-v3-gpl-3"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="GPLv3" /></a>
</p>
      
<p align="center">
  <a href="#description">Description</a> •
  <a href="#features">Features</a> •
  <a href="#overview">Overview</a> •
  <a href="#installation">Installation</a> •
  <a href="#poi">POI</a> •
  <a href="#dependencies">Dependencies</a> •
  <a href="#related-repos">Related Repos</a> •
  <a href="#license">License</a>
</p>

## Description
TODO - write text here...  Also link to other repo with final "showcase" product.

## Features

## Overview
![alt text](https://github.com/SupremeC/ControlPanelMasterPy/raw/master/.github/images/daemon_sketch.png "Logo Title Text 1")

## Installation

##### Downloading and installing steps:
1. **[Download](https://github.com/SupremeC/ControlPanelMasterPy/archive/master.zip)** the latest version of ControlPanelMasterPy.
2.  Open the _archive_ and **extract** the contents into a folder you choose.
3.  Create a virtualenv in the folder and install the dependencies: `python3 -m venv . && bin/pip install -r requirements.txt`
4. **Launch** the daemon `python3 control_panel_daemon.py` (runs in the foreground; stop with Ctrl+C)
> [!IMPORTANT]  
> Arduino needs to be connected via USB and powered up before starting the ControlPaneldaemon.


#### Daemon commands:
On the Raspberry Pi the daemon runs as the systemd service `service_cp`.
```console
foo@bar$ sudo systemctl start service_cp
foo@bar$ sudo systemctl stop service_cp
foo@bar$ sudo systemctl restart service_cp
foo@bar$ journalctl -u service_cp -f
foo@bar$ sudo systemctl kill -s USR1 service_cp   # morning routine compressed, alarm in 2 min
foo@bar$ sudo systemctl kill -s USR2 service_cp   # night-off now: lights off, strips low red
```
At 22:30 the panel goes dark for the night (`daemon/night.py`): the
backlight, every LED and the drawer socket go off and the LED strips go
to a dim red night light, silently. Until 05:00 a restart does it again
and a status resync does not re-light anything; the flips and buttons
keep working. The bed lamp and the bed socket are left alone. The times
and the light are settings in `daemon/config.py`.

#### Sound files:
System sounds are WAV files in `daemon/systemsounds/`, named after the
`SysAudioEvent` they belong to (e.g. `failed.wav`). They are not in git.
The morning routine's `alarm_soft.wav`, `chime_off.wav` and
`chime_speak.wav` are made with `bin/python tools/make_sounds.py`; replace
any of them with your own WAV (48 kHz mono, the alarm loopable) and
restart the daemon.

#### Tools:
Run on the Pi from the repo root with the daemon stopped (they use the
LED strips or the speaker themselves):
+ `tools/sunrise_demo.py`: plays or holds the sunrise on the LED strips
+ `tools/alarm_demo.py`: plays the alarm ramp and the chimes


## POI
If you want to fork this repo and customize it, pay special attention to these two code files
+ [ctrls.py](https://github.com/SupremeC/ControlPanelMasterPy/blob/master/daemon/ctrls.py)
+ [daemon/controlpanel_class.py](https://github.com/SupremeC/ControlPanelMasterPy/blob/5aa683eba5b9cbf9b319cd330a82109abc30e227/daemon/controlpanel_class.py#L108)

## Dependencies
+ [COBS](https://pypi.org/project/cobs/ "Consistent Overhead Byte Stuffing") (COBS encoding and decoding)
+ [numpy](https://numpy.org/) (manipulate & store audio data)
+ [spotify/pedalboard](https://github.com/spotify/pedalboard) (audio effects)
+ [pydub](https://github.com/jiaaro/pydub) (audio effects)
+ [pyrubberband](https://github.com/bmcfee/pyrubberband) (audio effects)
+ [soundfile](https://github.com/bastibe/python-soundfile/) (audio effects)

## Related Repos
+ [SupremeC/ControlPanelAxel](https://github.com/SupremeC/ControlPanelAxel) showcase final product
+ [SupremeC/ControlPanelMega](https://github.com/SupremeC/ControlPanelMega) Arduino code [c++]

---

### TODO Global!
- How to restore (btn)state when either Mega or Mastery reboots?


### TODO MasterPY!
- Cache and play Sound
- Stop playback of clip when new Clip plays
  - Stop Playback of clip when recording
  - Stop temp-playback when applying effect
  - Stop temp-playback when existing clip starts to play
- Play "click on HwSwitch event?"`
- Play "workingOnIt" when Applying effect?
- Control LED Strip(s) via Serial or over WiFi
- Add timestrech from pedalboard (replaces other library)
- Build more UnitTests


### TODO MEGA!
 - Such empty!


### TODO Electronics!
 - Replace pwr cable to front LED strip

## License

![License: GPL-3.0 license](https://img.shields.io/badge/License-GPLv3-blue.svg)
