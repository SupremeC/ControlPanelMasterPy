#!/usr/bin/env python
"""Plays the alarm and the chimes on the real speaker. Run on the Pi from
the repo root, with the daemon stopped (it owns the audio mixer):

    sudo systemctl stop service_cp
    bin/python tools/alarm_demo.py                     # 10 -> 70 % in 10 s, 30 s
    bin/python tools/alarm_demo.py --level 70 --ramp 90 --seconds 120
    bin/python tools/alarm_demo.py --chime off         # or: speak
    sudo systemctl start service_cp

The alarm ends with the "alarm off" chime, as on a real morning. Levels
are percent of full software volume and ignore the volume pot and the
sound switch, as on a real morning.
"""

import argparse
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daemon.audio_ctrl import AudioCtrl, SysAudioEvent  # noqa: E402
from daemon.config import Config  # noqa: E402
from daemon.morning import alarm_ramp_level  # noqa: E402

CHIMES = {"off": SysAudioEvent.CHIME_OFF, "speak": SysAudioEvent.CHIME_SPEAK}


def ring(audio: AudioCtrl, start: int, level: int, ramp: float, seconds: float) -> None:
    audio.alarm_start(start)
    began = time.monotonic()
    shown = None
    while (elapsed := time.monotonic() - began) < seconds:
        current = alarm_ramp_level(elapsed, ramp, start, level)
        audio.alarm_set_level(current)
        if current != shown:
            print(f"{elapsed:5.1f} s  level {current:3d} %", flush=True)
            shown = current
        time.sleep(0.25)
    audio.alarm_stop()
    time.sleep(0.6)  # the fade-out


def daemon_running() -> bool:
    result = subprocess.run(["systemctl", "is-active", "--quiet", "service_cp"])
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--level", type=int, default=Config.alarm_volume)
    parser.add_argument("--start", type=int, default=Config.alarm_start_volume)
    parser.add_argument("--ramp", type=float, default=10, help="seconds")
    parser.add_argument("--seconds", type=float, default=30, help="alarm length")
    parser.add_argument("--chime", choices=CHIMES, help="play only this chime")
    args = parser.parse_args()

    if daemon_running():
        print("service_cp is running and owns the audio mixer. Stop it first:")
        print("  sudo systemctl stop service_cp")
        return 1

    audio = AudioCtrl(lambda _playing: None)
    audio.start()
    audio.volume_override(True, args.level)
    try:
        if args.chime is None:
            ring(audio, args.start, args.level, args.ramp, args.seconds)
            print("chime: off")
            audio.sysaudio_play(SysAudioEvent.CHIME_OFF, block=True)
        else:
            audio.sysaudio_play(CHIMES[args.chime], block=True)
    except KeyboardInterrupt:
        pass
    finally:
        audio.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
