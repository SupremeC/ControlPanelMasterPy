<h1 align="center">
  <br />PUT LOGO HERE
</h1>

<h4 align="center">Custom-built Daemon and Client for retro-inspired ControlPanel</h4>

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
    <img src="https://img.shields.io/badge/Language-Python-blue" alt="Python" />
</p>
      
<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#updating">Updating</a> •
  <a href="#features">Features</a> •
  <a href="#symbols">Symbols</a> •
  <a href="#binds">Binds</a> •
  <a href="#wiki">Wiki</a> •
  <a href="#license">License</a>
</p>

## Installation

##### Downloading and installing steps:
1. **[Download](https://github.com/SupremeC/ControlPanelMasterPy/archive/master.zip)** the latest version of ControlPanelMasterPy.
2.  Open the _archive_ and **extract** the contents into a folder you choose.
3.  Install all of the dependencies using `PIP3 install xyz`
4. **Launch** the daemon `python3 controlPanelDaemon.py start`
> [!IMPORTANT]  
> Arduino needs to be connected via USB and powered up before starting the ControlPaneldaemon.

> [!NOTE]  
> Client allows you to monitor and interact with the Daemon. Its optional and not required to run.


#### Daemon commands:
```console
python3 controlPanelDaemon.py start
python3 controlPanelDaemon.py stop
python3 controlPanelDaemon.py restart
```

# ControlPanel - Raspberry
## - Daemon
## - Client



### TODO Global!
___
- Move one ledstrip to ceiling lamp?  (esp32 over Wifi)
- Bedlamp - How to wire up?
- How to restore (btn)state when either Mega or Mastery reboots?


### TODO MasterPY!
___
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
___
- ButtonClass jled  and jled-pca9685-hal
- analog btn handler & conversion
- analog "+100" ID support
  - not really need right? Since analog pins are not duplicate of digital pins


### TODO Electronics!
___

## License

[![License: CC0-1.0](https://img.shields.io/badge/License-CC0%201.0-lightgrey.svg)](https://tldrlegal.com/license/creative-commons-cc0-1.0-universal)
