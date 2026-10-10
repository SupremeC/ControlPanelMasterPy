"""The weather for the AI: fetches SMHI's forecast and warnings, caches
them, keeps recent hourly temperatures and makes the Swedish facts.

Blocking (HTTP): call it from the AI job lane only. Not thread-safe; the
lane runs one job at a time.

State in weather_state_file (gitignored) survives restarts:
- the last forecast and when it was fetched, so a failing SMHI right after
  a restart still leaves a forecast up to weather_stale_hours old;
- hourly temperatures for the last days. SMHI has no past data and drops
  past hours from the forecast, so each fetch merges into this store
  (the latest forecast for an hour wins). Yesterday's hours are the
  reference for "colder than yesterday".
"""

from dataclasses import dataclass
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Callable

from daemon.config import Config
from daemon.personal import Personal
from daemon.smhi import TIMEZONE, Forecast, SmhiError, fetch_forecast_json, parse_forecast
from daemon.smhi_warnings import (
    WeatherWarning,
    fetch_warnings_json,
    parse_warnings,
    relevant,
)
from daemon.weather import DayWeather, hourly_temps, periods, summarize
from daemon.weather_text import facts_sv, sentence_sv

logger = logging.getLogger("daemon.weather")

STATE_VERSION = 1
KEEP_TEMP_DAYS = 3  # today and the two days before


@dataclass(frozen=True)
class WeatherReport:
    days: tuple[DayWeather, ...]
    warnings: tuple[WeatherWarning, ...]
    facts: str
    """For the AI prompt (weather_text.facts_sv)."""
    sentence: str
    """One sentence for the briefing made without the AI."""


class WeatherService:
    def __init__(
        self,
        config: Config | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ):
        """Stores settings only; the state file is read on first use."""
        self._cfg = config or Config()
        self._clock = clock or (lambda: datetime.datetime.now(TIMEZONE))
        self._loaded = False
        self._raw: dict | None = None
        self._forecast: Forecast | None = None
        self._fetched: datetime.datetime | None = None
        self._fetched_for: tuple[float, float] | None = None
        self._warnings: list[WeatherWarning] = []
        self._warnings_fetched: datetime.datetime | None = None
        self._temps: dict[str, dict[int, float]] = {}

    def location(self) -> tuple[float, float]:
        return (
            Personal.load(self._cfg.personal_file).location
            or self._cfg.weather_default_location
        )

    def refresh(self) -> None:
        """Keep-warm: fetches the forecast when it is no longer fresh, which
        also records the hourly temperatures. Never raises."""
        try:
            self._current_forecast(self.location())
        except Exception:
            logger.exception("Weather refresh failed")

    def report(self, now: datetime.datetime | None = None) -> WeatherReport | None:
        """The weather to tell at `now` (default: the clock), or None when
        there is no usable forecast. Never raises. `now` only picks what to
        describe: cache ages and the temperature history follow the clock."""
        try:
            return self._report(now or self._clock())
        except Exception:
            logger.exception("Weather report failed")
            return None

    def _report(self, now: datetime.datetime) -> WeatherReport | None:
        lat, lon = self.location()
        forecast = self._current_forecast((lat, lon))
        if forecast is None:
            return None
        days = []
        for period in periods(now, self._cfg):
            before = (period.day - datetime.timedelta(days=1)).isoformat()
            day = summarize(forecast, period, lat, lon, self._temps.get(before))
            if day:
                days.append(day)
        if not days:
            logger.warning("The forecast does not cover %s", now)
            return None
        start, end = days[0].parts[0].start, days[-1].parts[-1].end
        warnings = relevant(self._current_warnings(), lat, lon, start, end)
        return WeatherReport(
            days=tuple(days),
            warnings=tuple(warnings),
            facts=facts_sv(days, warnings),
            sentence=sentence_sv(days[0], warnings),
        )

    # ---- forecast cache ---------------------------------------------------

    def _age(self, since: datetime.datetime | None) -> datetime.timedelta | None:
        """None when unknown or in the future (clock jump, bad state file):
        such a forecast is neither fresh nor usable when SMHI fails."""
        if since is None:
            return None
        age = self._clock() - since
        return age if age >= datetime.timedelta(0) else None

    def _current_forecast(self, location: tuple[float, float]) -> Forecast | None:
        self._load_state()
        age = self._age(self._fetched) if self._fetched_for == location else None
        fresh = datetime.timedelta(minutes=self._cfg.weather_fresh_minutes)
        if self._forecast and age is not None and age < fresh:
            return self._forecast
        try:
            raw = fetch_forecast_json(*location, timeout=self._cfg.smhi_timeout)
            forecast = parse_forecast(raw)
        except SmhiError as e:
            stale = datetime.timedelta(hours=self._cfg.weather_stale_hours)
            if self._forecast and age is not None and age < stale:
                logger.warning(
                    "%s. Using the forecast fetched %s", e, f"{self._fetched:%H:%M}"
                )
                return self._forecast
            logger.warning("%s. No weather", e)
            return None
        now = self._clock()
        self._raw, self._forecast = raw, forecast
        self._fetched, self._fetched_for = now, location
        self._record_temps(forecast, now.date())
        self._save_state()
        return forecast

    def _current_warnings(self) -> list[WeatherWarning]:
        """Warnings fetched at most weather_fresh_minutes ago; on failure
        the last ones up to weather_stale_hours old, else none."""
        age = self._age(self._warnings_fetched)
        if age is not None and age < datetime.timedelta(
            minutes=self._cfg.weather_fresh_minutes
        ):
            return self._warnings
        try:
            self._warnings = parse_warnings(fetch_warnings_json(self._cfg.smhi_timeout))
            self._warnings_fetched = self._clock()
        except SmhiError as e:
            if age is None or age >= datetime.timedelta(hours=self._cfg.weather_stale_hours):
                self._warnings = []
            logger.warning("%s. Warnings left out", e)
        return self._warnings

    def _record_temps(self, forecast: Forecast, today: datetime.date) -> None:
        for offset in (0, 1):
            day = today + datetime.timedelta(days=offset)
            hours = hourly_temps(forecast, day)
            if hours:
                self._temps.setdefault(day.isoformat(), {}).update(hours)
        oldest = (today - datetime.timedelta(days=KEEP_TEMP_DAYS - 1)).isoformat()
        for key in [k for k in self._temps if k < oldest]:
            del self._temps[key]

    # ---- state file -------------------------------------------------------

    def _load_state(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path: Path = self._cfg.weather_state_file
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("version") != STATE_VERSION:
                raise ValueError(f"version {state.get('version')}")
            self._temps = {
                day: {int(h): float(t) for h, t in hours.items()}
                for day, hours in state.get("temps", {}).items()
            }
            saved = state.get("forecast")
            if saved:
                self._forecast = parse_forecast(saved["raw"])
                self._raw = saved["raw"]
                self._fetched = datetime.datetime.fromisoformat(saved["fetched"])
                self._fetched_for = tuple(saved["location"])
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, KeyError, AttributeError, SmhiError) as e:
            logger.warning("%s is not usable (%r): starting without it", path, e)
            self._forecast = self._raw = self._fetched = self._fetched_for = None
            self._temps = {}

    def _save_state(self) -> None:
        path: Path = self._cfg.weather_state_file
        state = {
            "version": STATE_VERSION,
            "forecast": {
                "fetched": self._fetched.isoformat(),
                "location": list(self._fetched_for),
                "raw": self._raw,
            },
            "temps": self._temps,
        }
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            logger.warning("Saving %s failed: %s", path, e)
