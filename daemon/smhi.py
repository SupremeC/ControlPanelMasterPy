"""SMHI point forecast, model SNOW (snow1g). No authentication.

Docs: https://opendata.smhi.se/metfcst/snow1gv1/ (rendered with JavaScript;
the parameter table and the code tables are on the "Parameters" page).

The response has a `timeSeries` list. Each item has a valid `time` (UTC)
and a flat `data` dict. All values are instantaneous at `time` except
precipitation, which covers `intervalParametersStartTime`..`time` and is
always in mm/h. The steps are hourly for about 2.5 days, then 3, 6 and
12 hours, up to about 10 days ahead.

This module only fetches and parses. Turning steps into words is
daemon/weather.py.
"""

from dataclasses import dataclass
import datetime
from enum import IntEnum
import logging
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("daemon.smhi")

FORECAST_URL = (
    "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
    "/geotype/point/lon/{lon}/lat/{lat}/data.json"
)
TIMEZONE = ZoneInfo("Europe/Stockholm")
MISSING = 9999
NO_PRECIPITATION = -9  # precipitation_frozen_part when it is dry


class SmhiError(Exception):
    """The forecast could not be fetched or its format has changed."""


class PrecipType(IntEnum):
    """predominant_precipitation_type_at_surface (ECMWF ptype)."""

    NONE = 0
    RAIN = 1
    THUNDERSTORM = 2
    FREEZING_RAIN = 3
    MIXED_ICE = 4
    SNOW = 5
    WET_SNOW = 6
    RAIN_AND_SNOW = 7
    ICE_PELLETS = 8
    GRAUPEL = 9
    HAIL = 10
    DRIZZLE = 11
    FREEZING_DRIZZLE = 12


@dataclass(frozen=True)
class Step:
    """One forecast time step. A value SMHI marks as missing is None.

    Times are UTC. Python compares and subtracts datetimes that share a
    tzinfo by wall clock, so in local time the two 02:00 of the October DST
    change would be equal; use local_start/local_end only for display and
    for picking the day and hour."""

    start: datetime.datetime
    """Start of the precipitation interval (the previous step), UTC."""
    end: datetime.datetime
    """Valid time of every value except precipitation, UTC."""
    temp: float | None
    """Air temperature, °C."""
    wind: float | None
    """Mean wind, m/s."""
    gust: float | None
    """Wind gust, m/s."""
    wind_dir: int | None
    """Wind from direction, degrees."""
    humidity: int | None
    """Relative humidity, %."""
    visibility: float | None
    """Visibility, km."""
    cloud: int | None
    """Total cloud cover, oktas 0-8."""
    precip: float | None
    """Mean precipitation over the interval, mm/h."""
    precip_max: float | None
    """Largest precipitation among the ensemble members that have any, mm/h."""
    precip_prob: int | None
    """Probability of at least 0.1 mm, %."""
    precip_type: PrecipType | None
    frozen_part: int | None
    """Frozen part of the precipitation, %. None when dry."""
    thunder_prob: int | None
    """Thunderstorm probability, %."""
    symbol: int | None
    """Weather symbol (Wsymb2) 1-27, SMHI's own summary of the step."""

    @property
    def hours(self) -> float:
        """Length of the precipitation interval."""
        return (self.end - self.start).total_seconds() / 3600

    @property
    def local_start(self) -> datetime.datetime:
        return self.start.astimezone(TIMEZONE)

    @property
    def local_end(self) -> datetime.datetime:
        return self.end.astimezone(TIMEZONE)


@dataclass(frozen=True)
class Forecast:
    created: datetime.datetime
    """When SMHI made the forecast, UTC."""
    steps: tuple[Step, ...]


def forecast_url(lat: float, lon: float) -> str:
    return FORECAST_URL.format(lat=lat, lon=lon)


def fetch_forecast_json(lat: float, lon: float, timeout: float) -> dict:
    """The raw forecast for the point. Blocking; raises SmhiError."""
    url = forecast_url(lat, lon)
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        # HTTPError, Timeout, ConnectionError and (requests >= 2.27)
        # a body that is not JSON all derive from RequestException.
        raise SmhiError(f"SMHI forecast {url}: {e}") from e
    except ValueError as e:
        raise SmhiError(f"SMHI forecast {url} is not JSON: {e}") from e


def fetch_forecast(lat: float, lon: float, timeout: float) -> Forecast:
    return parse_forecast(fetch_forecast_json(lat, lon, timeout))


def parse_forecast(raw: dict) -> Forecast:
    """Pure. Raises SmhiError when the layout is not what this code
    knows, so a format change shows up as such and not as a KeyError."""
    try:
        created = _utc_time(raw["createdTime"])
        series = raw["timeSeries"]
        steps: list[Step] = []
        for item in series:
            end = _utc_time(item["time"])
            interval_start = item.get("intervalParametersStartTime")
            if interval_start:
                start = _utc_time(interval_start)
            elif steps:
                start = steps[-1].end
            else:
                start = end - datetime.timedelta(hours=1)
            steps.append(_step(start, end, item["data"]))
    except (KeyError, TypeError, ValueError) as e:
        raise SmhiError(f"SMHI forecast format has changed: {e!r}") from e
    if not steps:
        raise SmhiError("SMHI forecast has no time steps")
    if all(s.temp is None for s in steps):
        raise SmhiError("SMHI forecast has no air_temperature (format changed?)")
    return Forecast(created=created, steps=tuple(steps))


def _step(start: datetime.datetime, end: datetime.datetime, data: dict) -> Step:
    def value(name: str):
        v = data.get(name)
        return None if v is None or v == MISSING else v

    def whole(name: str) -> int | None:
        v = value(name)
        return None if v is None else int(round(v))

    frozen = whole("precipitation_frozen_part")
    return Step(
        start=start,
        end=end,
        temp=value("air_temperature"),
        wind=value("wind_speed"),
        gust=value("wind_speed_of_gust"),
        wind_dir=whole("wind_from_direction"),
        humidity=whole("relative_humidity"),
        visibility=value("visibility_in_air"),
        cloud=whole("cloud_area_fraction"),
        precip=value("precipitation_amount_mean"),
        precip_max=value("precipitation_amount_max"),
        precip_prob=whole("probability_of_precipitation"),
        precip_type=_precip_type(whole("predominant_precipitation_type_at_surface")),
        frozen_part=None if frozen == NO_PRECIPITATION else frozen,
        thunder_prob=whole("thunderstorm_probability"),
        symbol=whole("symbol_code"),
    )


def _precip_type(code: int | None) -> PrecipType | None:
    if code is None:
        return None
    try:
        return PrecipType(code)
    except ValueError:
        logger.warning("Unknown SMHI precipitation type %d", code)
        return None


def _utc_time(text: str) -> datetime.datetime:
    """'2026-10-10T12:00:00Z' -> aware UTC datetime."""
    t = datetime.datetime.fromisoformat(text)
    if t.tzinfo is None:
        raise ValueError(f"time without zone: {text}")
    return t.astimezone(datetime.timezone.utc)
