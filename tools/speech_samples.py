#!/usr/bin/env python
"""Makes sample wake lines in every humour style and a few voices, for a
listening test with Axel (GH #14). Uses OpenAI and SMHI for real. Safe
while the daemon runs: no hardware, and the weather state is a copy.
Run on the Pi from the repo root:

    bin/python tools/speech_samples.py                       # all styles, 3 voices
    bin/python tools/speech_samples.py --styles torr absurd --voices marin
    bin/python tools/speech_samples.py --count 3 --play       # play on the panel speaker
    bin/python tools/speech_samples.py --overview             # also overview + countdown

The MP3 files and index.txt (file -> text) go to --out (default
/tmp/speech_samples). --play reads each one aloud through ffplay, with
its name printed first. Pick a style and a voice, then set humour_style
and voice in daemon/config.py.
"""

import argparse
import dataclasses
import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daemon.cevent import CEvent  # noqa: E402
from daemon.config import Config  # noqa: E402
from daemon.openaiWrapper import OpenAiWrapper  # noqa: E402
from daemon.smhi import TIMEZONE  # noqa: E402
from daemon.speech import STYLES, Speech, countdown_text  # noqa: E402
from daemon.weather_service import WeatherService  # noqa: E402

# Voices that exist for both gpt-4o-mini-tts and gpt-audio.
VOICES = ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--styles", nargs="+", choices=sorted(STYLES), default=sorted(STYLES))
    parser.add_argument("--voices", nargs="+", choices=VOICES, default=["alloy", "marin", "cedar"])
    parser.add_argument("--count", type=int, default=2, help="jokes per style")
    parser.add_argument("--at", default="06:45", help="time of day HH:MM (today)")
    parser.add_argument("--overview", action="store_true", help="also an overview and the countdown")
    parser.add_argument("--play", action="store_true", help="play every file through ffplay")
    parser.add_argument("--text-only", action="store_true", help="print the texts, no speech")
    parser.add_argument("--out", default="/tmp/speech_samples")
    parser.add_argument(
        "--secrets", default=str(Config.openai_key_file.parent),
        help="directory with the OpenAI key, personal.json and weather_state.json",
    )
    args = parser.parse_args()

    secrets = Path(args.secrets)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    clock = datetime.datetime.strptime(args.at, "%H:%M").time()
    now = datetime.datetime.now(TIMEZONE).replace(
        hour=clock.hour, minute=clock.minute, second=0, microsecond=0
    )

    tmp = Path(tempfile.mkdtemp())
    state = secrets / "weather_state.json"
    if state.exists():
        shutil.copy(state, tmp / "weather_state.json")
    base = Config(
        openai_key_file=secrets / Config.openai_key_file.name,
        personal_file=secrets / "personal.json",
        weather_state_file=tmp / "weather_state.json",
        speech_cache_dir=tmp / "cache",
    )
    report = WeatherService(base).report(now)
    facts = report.facts if report else ""
    print(f"Weather facts:\n{facts or '(none)'}\n")

    index = []

    def save(name: str, text: str, make_audio) -> None:
        if args.text_only:
            print(f"{name}: {text}")
            return
        audio = make_audio()
        path = out / f"{name}.mp3"
        path.write_bytes(audio)
        index.append(f"{path.name}\t{text}")
        print(f"{path.name}: {text}")

    # One set of texts per style, read by every voice: the voice test
    # compares the same words.
    for style_name in args.styles:
        cfg = dataclasses.replace(base, humour_style=style_name)
        speech = Speech(OpenAiWrapper(cfg.openai_key_file, cfg.personal_file, cfg), cfg)
        for n in range(1, args.count + 1):
            text = speech.wake_text(now, facts, school_day=True)
            for voice in args.voices[:1] if args.text_only else args.voices:
                vcfg = dataclasses.replace(cfg, voice=voice)
                vspeech = Speech(OpenAiWrapper(vcfg.openai_key_file, vcfg.personal_file, vcfg), vcfg)
                save(
                    f"wake_{style_name}_{n}_{voice}", text,
                    lambda: vspeech.say(text, vspeech.wake_voice()),
                )

    if args.overview:
        school = CEvent(
            start=now.replace(hour=9, minute=10), summary="Skola", descr="", location=None,
            is_alarm=False, has_time=True, end=now.replace(hour=15, minute=0),
        )
        scout = CEvent(
            start=now.replace(hour=18, minute=0), summary="Scoutmöte", descr="", location=None,
            is_alarm=False, has_time=True, end=now.replace(hour=19, minute=30),
        )
        leave = school.start - datetime.timedelta(minutes=base.school_travel_minutes)
        at = leave - datetime.timedelta(minutes=base.checkin_minutes[0])
        speech = Speech(OpenAiWrapper(base.openai_key_file, base.personal_file, base), base)
        text = speech.overview_text(
            at, [school, scout], school.start, base.checkin_minutes[0],
            facts, report.sentence if report else "",
        )
        for voice in args.voices:
            vcfg = dataclasses.replace(base, voice=voice)
            vspeech = Speech(OpenAiWrapper(vcfg.openai_key_file, vcfg.personal_file, vcfg), vcfg)
            save(f"overview_{voice}", text, lambda: vspeech.say(text))
            for minutes in base.checkin_minutes[1:]:
                text_m = countdown_text(minutes)
                save(f"countdown_{minutes}_{voice}", text_m, lambda: vspeech.say(text_m))

    if args.text_only:
        return 0
    (out / "index.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(index)} files in {out}")

    if args.play:
        for line in index:
            name, text = line.split("\t", 1)
            input(f"\n[Enter] {name}: {text}")
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(out / name)],
                check=False,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
