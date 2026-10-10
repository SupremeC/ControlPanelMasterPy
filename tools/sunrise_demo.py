#!/usr/bin/env python
"""Shows the sunrise on the real LED strips. Run on the Pi from the repo
root, with the daemon stopped (it owns the WLED port):

    sudo systemctl stop service_cp
    bin/python tools/sunrise_demo.py                 # whole curve in 60 s
    bin/python tools/sunrise_demo.py --seconds 180
    bin/python tools/sunrise_demo.py --at 1          # hold the end state
    bin/python tools/sunrise_demo.py --at 1 --end 255,120,20,255
    bin/python tools/sunrise_demo.py --tune          # type values live
    bin/python tools/sunrise_demo.py --info          # WLED's LED settings
    sudo systemctl start service_cp

--end/--end-brightness override the Config values for this run only.
Put the values you like into daemon/config.py.
"""

import argparse
import dataclasses
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daemon import sunrise  # noqa: E402
from daemon.config import Config  # noqa: E402
from daemon.wled import WLED  # noqa: E402

TUNE_HELP = """\
Enter one of:
  R G B W [BRI]   show this colour (0-255 each), brightness default 255
  p P             show the sunrise frame at progress P (0-1)
  q               quit (the strips keep the last frame)"""


def rgbw(text: str) -> tuple[int, int, int, int]:
    values = tuple(int(v) for v in text.replace(",", " ").split())
    if len(values) != 4 or not all(0 <= v <= 255 for v in values):
        raise argparse.ArgumentTypeError("need four values 0-255: R,G,B,W")
    return values


def show(wled: WLED, f: sunrise.Frame, transition: float = 0) -> None:
    print(f"brightness {f.brightness:3d}  rgbw {f.rgbw}", flush=True)
    wled.set_both(f.brightness, f.rgbw, transition=transition)


def run_curve(wled: WLED, cfg: Config, seconds: float, tick: float) -> None:
    started = time.monotonic()
    while True:
        progress = min((time.monotonic() - started) / seconds, 1.0)
        print(f"{progress:4.0%}  ", end="")
        show(wled, sunrise.frame(progress, cfg), transition=tick)
        if progress >= 1:
            return
        time.sleep(tick)


def tune(wled: WLED, cfg: Config) -> None:
    print(TUNE_HELP)
    for line in sys.stdin:
        line = line.strip()
        try:
            if line == "q":
                return
            if line.startswith("p"):
                show(wled, sunrise.frame(float(line[1:]), cfg), transition=0.5)
                continue
            values = [int(v) for v in line.replace(",", " ").split()]
            bri = values[4] if len(values) == 5 else 255
            show(wled, sunrise.Frame(bri, rgbw(" ".join(map(str, values[:4])))), 0.5)
        except (ValueError, IndexError, argparse.ArgumentTypeError) as e:
            print(f"? {e}\n{TUNE_HELP}")


def info(wled: WLED) -> None:
    wled._enqueue_command({"v": True})
    reply = wled._read_whole_json_message()
    if not reply:
        print("No reply from WLED")
        return
    print("info.leds:", json.dumps(reply.get("info", {}).get("leds"), indent=2))
    for seg in reply.get("state", {}).get("seg", []):
        print(f"segment {seg['id']}: on={seg['on']} bri={seg['bri']} col={seg['col']}")


def daemon_running() -> bool:
    result = subprocess.run(["systemctl", "is-active", "--quiet", "service_cp"])
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--seconds", type=float, default=60, help="curve length")
    mode.add_argument("--at", type=float, metavar="P", help="one frame, 0-1")
    mode.add_argument("--tune", action="store_true", help="type values live")
    mode.add_argument("--info", action="store_true", help="print WLED settings")
    parser.add_argument("--end", type=rgbw, help="end colour R,G,B,W")
    parser.add_argument("--end-brightness", type=int, help="0-255")
    parser.add_argument("--tick", type=float, default=Config.sunrise_tick_seconds)
    args = parser.parse_args()

    if daemon_running():
        print("service_cp is running and owns the WLED port. Stop it first:")
        print("  sudo systemctl stop service_cp")
        return 1

    overrides = {}
    if args.end is not None:
        overrides["sunrise_end_rgbw"] = args.end
    if args.end_brightness is not None:
        overrides["sunrise_end_brightness"] = args.end_brightness
    cfg = dataclasses.replace(Config(), **overrides)

    wled = WLED(cfg.wled_port, cfg.wled_baud)
    wled.start()
    try:
        if args.info:
            info(wled)
        elif args.tune:
            tune(wled, cfg)
        elif args.at is not None:
            show(wled, sunrise.frame(args.at, cfg))
        else:
            run_curve(wled, cfg, args.seconds, args.tick)
        while not wled.command_queue.empty():
            time.sleep(0.05)
        time.sleep(0.2)  # let the last command leave the UART
    except KeyboardInterrupt:
        pass
    finally:
        wled.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
