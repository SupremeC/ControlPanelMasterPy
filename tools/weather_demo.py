#!/usr/bin/env python
"""Prints the weather facts the AI gets, from the live SMHI APIs or from
saved files. Safe while the daemon runs: no hardware, and the daemon's
weather state file is only read (for "colder than yesterday"). Run on the
Pi from the repo root:

    bin/python tools/weather_demo.py                        # as of now
    bin/python tools/weather_demo.py --at 06:35 --at 17:30  # today at these times
    bin/python tools/weather_demo.py --at "2026-10-12 06:35" --steps
    bin/python tools/weather_demo.py --save unit_tests/data   # store fixtures
    bin/python tools/weather_demo.py --forecast f.json --warnings w.json --at 06:35
    bin/python tools/weather_demo.py --lat 57.7 --lon 11.97 --all-warnings

--steps lists the forecast steps behind each part of the day, for tuning
the thresholds in daemon/weather.py.
"""

import argparse
import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daemon.config import Config  # noqa: E402
from daemon.personal import Personal  # noqa: E402
from daemon.smhi import (  # noqa: E402
    TIMEZONE,
    Forecast,
    SmhiError,
    fetch_forecast_json,
    parse_forecast,
)
from daemon.smhi_warnings import (  # noqa: E402
    Level,
    fetch_warnings_json,
    parse_warnings,
    relevant,
)
from daemon.weather import Period, periods, summarize  # noqa: E402
from daemon.weather_text import facts_sv, sentence_sv  # noqa: E402


def parse_at(text: str) -> datetime.datetime:
    """'06:35' (today) or 'YYYY-MM-DD HH:MM', Stockholm time."""
    try:
        if len(text) <= 5:
            clock = datetime.datetime.strptime(text, "%H:%M").time()
            day = datetime.datetime.now(TIMEZONE).date()
            return datetime.datetime.combine(day, clock, TIMEZONE)
        naive = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=TIMEZONE)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not HH:MM or 'YYYY-MM-DD HH:MM': {text}")


def load_or_fetch(path: str | None, fetch, what: str):
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    print(f"Fetching {what} from SMHI...", file=sys.stderr)
    return fetch()


def reference_temps(state_file: Path) -> dict[str, dict[int, float]]:
    """Hourly temperatures from the daemon's state file, read only."""
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        return {
            day: {int(h): float(t) for h, t in hours.items()}
            for day, hours in state.get("temps", {}).items()
        }
    except (OSError, ValueError, AttributeError) as e:
        print(f"No temperature history ({state_file}: {e})", file=sys.stderr)
        return {}


def print_steps(forecast: Forecast, period: Period) -> None:
    print(f"  steps for {period.label}:")
    print("    end    temp  wind gust okt  mm/h  max  prob type sym thdr  vis")
    for w in period.windows:
        print(f"    {w.name}")
        for s in forecast.steps:
            if w.start < s.end <= w.end:
                ptype = s.precip_type.value if s.precip_type is not None else None
                print(
                    f"    {s.local_end:%H:%M} {fmt(s.temp, 5, 1)} {fmt(s.wind, 5, 1)}"
                    f" {fmt(s.gust, 4, 0)} {fmt(s.cloud, 3)} {fmt(s.precip, 5, 1)}"
                    f" {fmt(s.precip_max, 4, 1)} {fmt(s.precip_prob, 4)}%"
                    f" {fmt(ptype, 4)} {fmt(s.symbol, 3)} {fmt(s.thunder_prob, 3)}%"
                    f" {fmt(s.visibility, 4, 0)}"
                )


def fmt(value, width: int, decimals: int | None = None) -> str:
    if value is None:
        return "-".rjust(width)
    if decimals is not None:
        return f"{value:{width}.{decimals}f}"
    return f"{value:{width}}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--at", type=parse_at, action="append",
                        help="'HH:MM' today or 'YYYY-MM-DD HH:MM' (repeatable)")
    parser.add_argument("--lat", type=float, help="default: personal.json")
    parser.add_argument("--lon", type=float)
    parser.add_argument("--forecast", help="read the snow1g JSON from this file")
    parser.add_argument("--warnings", help="read the warnings JSON from this file")
    parser.add_argument("--save", metavar="DIR", help="store the raw responses here")
    parser.add_argument("--all-warnings", action="store_true",
                        help="also SMHI messages (level MESSAGE)")
    parser.add_argument("--steps", action="store_true", help="list the forecast steps")
    args = parser.parse_args()

    cfg = Config()
    if (args.lat is None) != (args.lon is None):
        parser.error("give both --lat and --lon")
    if args.lat is not None:
        lat, lon = args.lat, args.lon
    else:
        lat, lon = Personal.load(cfg.personal_file).location or cfg.weather_default_location
    print(f"Location {lat}, {lon}", file=sys.stderr)

    try:
        raw_forecast = load_or_fetch(
            args.forecast, lambda: fetch_forecast_json(lat, lon, cfg.smhi_timeout), "the forecast"
        )
        raw_warnings = load_or_fetch(
            args.warnings, lambda: fetch_warnings_json(cfg.smhi_timeout), "the warnings"
        )
        forecast = parse_forecast(raw_forecast)
        warnings = parse_warnings(raw_warnings)
    except SmhiError as e:
        print(e, file=sys.stderr)
        return 1

    if args.save:
        folder = Path(args.save)
        folder.mkdir(parents=True, exist_ok=True)
        day = f"{forecast.created.astimezone(TIMEZONE):%Y-%m-%d}"
        for name, raw in (("smhi_snow1g", raw_forecast), ("smhi_warnings", raw_warnings)):
            path = folder / f"{name}_{day}.json"
            path.write_text(
                json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            print(f"Saved {path}", file=sys.stderr)

    temps = reference_temps(cfg.weather_state_file)
    min_level = Level.MESSAGE if args.all_warnings else Level.YELLOW
    print(f"Forecast made {forecast.created.astimezone(TIMEZONE):%Y-%m-%d %H:%M}, "
          f"{len(forecast.steps)} steps, {len(warnings)} warning areas in Sweden\n")

    for now in args.at or [datetime.datetime.now(TIMEZONE)]:
        print(f"===== as at {now:%Y-%m-%d %H:%M} =====")
        first = forecast.steps[0].local_start
        if now < first:
            print(f"(the forecast starts {first:%Y-%m-%d %H:%M}: earlier hours are missing)")
        days = []
        for period in periods(now, cfg):
            before = (period.day - datetime.timedelta(days=1)).isoformat()
            day = summarize(forecast, period, lat, lon, temps.get(before))
            if day is None:
                print(f"(the forecast does not cover {period.label})")
                continue
            days.append(day)
            if args.steps:
                print_steps(forecast, period)
        if not days:
            continue
        start, end = days[0].parts[0].start, days[-1].parts[-1].end
        found = relevant(warnings, lat, lon, start, end, min_level)
        print(facts_sv(days, found))
        print(f"\nFallback: {sentence_sv(days[0], found)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
