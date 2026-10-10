"""What the SMHI forecast means for the listener's day. Pure: no I/O, no
clock (`now` is passed in).

periods(now) picks what to describe: the rest of today, or from the
evening on, the rest of the evening and tomorrow. summarize() turns the
forecast steps of one period into a DayWeather: per part of the day
(morning, late morning, afternoon, evening) the temperature, how cold it
feels, sky, precipitation, wind, thunder and fog, plus when precipitation
starts or stops, slippery roads, sunrise/sunset and the change from a
reference day. The Swedish text is made from a DayWeather elsewhere.

Precipitation, its kind and intensity come mostly from SMHI's weather
symbol, which already folds cloud cover, type, intensity and showers into
one code. The precipitation type parameter only refines it (freezing rain,
drizzle, hail): it is set even in dry steps, so it never decides on its own
that something falls.
"""

from dataclasses import dataclass
import datetime
from enum import Enum, IntEnum
from statistics import mean
from typing import Iterable, Mapping

from daemon import sun
from daemon.config import Config
from daemon.smhi import TIMEZONE, Forecast, PrecipType, Step

# A step has precipitation when it is at least this likely (%) ...
POSSIBLE_PERCENT = 30
# ... and is stated as a fact, not a risk, above this.
LIKELY_PERCENT = 60
MIN_MM_H = 0.1
THUNDER_PERCENT = 30
FOG_KM = 1.0  # visibility below this is fog
FEELS_LIKE_GAP = 3  # degrees colder than the thermometer before it is said
GUST_MENTION = 12  # m/s
SLIPPERY_TEMP = 1.0  # precipitation at or below this freezes on the ground
TEMP_CHANGE_MENTION = 3  # degrees between the day and the reference day
COMPARE_HOURS = range(7, 19)  # local hours compared with the reference day
COMPARE_MIN_HOURS = 4


class Sky(Enum):
    CLEAR = "klart"
    NEARLY_CLEAR = "nästan klart"
    HALFCLEAR = "halvklart"
    VARIABLE = "växlande molnighet"
    CLOUDY = "molnigt"
    OVERCAST = "mulet"


class PrecipKind(Enum):
    RAIN = "regn"
    DRIZZLE = "duggregn"
    SLEET = "snöblandat regn"
    SNOW = "snö"
    WET_SNOW = "blötsnö"
    FREEZING_RAIN = "underkylt regn"
    FREEZING_DRIZZLE = "underkylt duggregn"
    HAIL = "hagel"
    GRAUPEL = "snöhagel"
    ICE_PELLETS = "iskorn"


class Intensity(IntEnum):
    LIGHT = 1
    MODERATE = 2
    HEAVY = 3


class Wind(IntEnum):
    """SMHI's Swedish wind scale, by mean wind in m/s."""

    CALM = 0  # < 0.3
    LIGHT = 1  # svag, < 3.4
    MODERATE = 2  # måttlig, < 8
    FRESH = 3  # frisk, < 13.9
    STRONG = 4  # hård, < 24.5
    STORM = 5  # < 32.7
    HURRICANE = 6  # orkan

    @staticmethod
    def of(speed: float) -> "Wind":
        for limit, wind in (
            (0.3, Wind.CALM),
            (3.4, Wind.LIGHT),
            (8.0, Wind.MODERATE),
            (13.9, Wind.FRESH),
            (24.5, Wind.STRONG),
            (32.7, Wind.STORM),
        ):
            if speed < limit:
                return wind
        return Wind.HURRICANE


# Weather symbols (Wsymb2) with precipitation: kind, intensity, showers.
_P = PrecipKind
_SYMBOL_PRECIP: dict[int, tuple[PrecipKind, Intensity, bool]] = {
    8: (_P.RAIN, Intensity.LIGHT, True),
    9: (_P.RAIN, Intensity.MODERATE, True),
    10: (_P.RAIN, Intensity.HEAVY, True),
    11: (_P.RAIN, Intensity.MODERATE, True),  # thunderstorm
    12: (_P.SLEET, Intensity.LIGHT, True),
    13: (_P.SLEET, Intensity.MODERATE, True),
    14: (_P.SLEET, Intensity.HEAVY, True),
    15: (_P.SNOW, Intensity.LIGHT, True),
    16: (_P.SNOW, Intensity.MODERATE, True),
    17: (_P.SNOW, Intensity.HEAVY, True),
    18: (_P.RAIN, Intensity.LIGHT, False),
    19: (_P.RAIN, Intensity.MODERATE, False),
    20: (_P.RAIN, Intensity.HEAVY, False),
    21: (_P.RAIN, Intensity.MODERATE, False),  # thunder
    22: (_P.SLEET, Intensity.LIGHT, False),
    23: (_P.SLEET, Intensity.MODERATE, False),
    24: (_P.SLEET, Intensity.HEAVY, False),
    25: (_P.SNOW, Intensity.LIGHT, False),
    26: (_P.SNOW, Intensity.MODERATE, False),
    27: (_P.SNOW, Intensity.HEAVY, False),
}
THUNDER_SYMBOLS = {11, 21}
FOG_SYMBOL = 7

# Precipitation types that say more than the symbol does. The symbol only
# knows rain, sleet and snow.
_TYPE_OVERRIDES: dict[PrecipType, tuple[PrecipKind, set[PrecipKind | None]]] = {
    # type: (kind, symbol kinds it replaces; None = no precipitation symbol)
    PrecipType.FREEZING_RAIN: (_P.FREEZING_RAIN, {_P.RAIN, _P.SLEET, _P.SNOW, None}),
    PrecipType.FREEZING_DRIZZLE: (
        _P.FREEZING_DRIZZLE,
        {_P.RAIN, _P.SLEET, _P.SNOW, None},
    ),
    PrecipType.HAIL: (_P.HAIL, {_P.RAIN, _P.SLEET, _P.SNOW, None}),
    PrecipType.GRAUPEL: (_P.GRAUPEL, {_P.RAIN, _P.SLEET, _P.SNOW, None}),
    PrecipType.ICE_PELLETS: (_P.ICE_PELLETS, {_P.RAIN, _P.SLEET, _P.SNOW, None}),
    PrecipType.DRIZZLE: (_P.DRIZZLE, {_P.RAIN, None}),
    PrecipType.WET_SNOW: (_P.WET_SNOW, {_P.SNOW, _P.SLEET, None}),
}
# Without a precipitation symbol the type names the kind directly.
_TYPE_KIND: dict[PrecipType, PrecipKind] = {
    PrecipType.RAIN: _P.RAIN,
    PrecipType.THUNDERSTORM: _P.RAIN,
    PrecipType.MIXED_ICE: _P.SLEET,
    PrecipType.SNOW: _P.SNOW,
    PrecipType.RAIN_AND_SNOW: _P.SLEET,
}
FREEZING = {_P.FREEZING_RAIN, _P.FREEZING_DRIZZLE}


@dataclass(frozen=True)
class Window:
    """A part of the day to describe; local times."""

    name: str
    start: datetime.datetime
    end: datetime.datetime


@dataclass(frozen=True)
class Period:
    """What to describe: 'idag', 'ikväll' or 'imorgon'."""

    label: str
    day: datetime.date
    windows: tuple[Window, ...]


@dataclass(frozen=True)
class Precipitation:
    kind: PrecipKind
    intensity: Intensity
    showers: bool
    likely: bool
    """False: only a risk (POSSIBLE_PERCENT..LIKELY_PERCENT)."""
    mm: float
    """Expected amount over the part (ensemble mean)."""


@dataclass(frozen=True)
class Part:
    name: str
    start: datetime.datetime
    """Local; the part's start, or the current hour if it has begun."""
    end: datetime.datetime
    temp_min: float
    temp_max: float
    feels_like: float | None
    """Lowest wind chill, only when FEELS_LIKE_GAP colder than temp_min."""
    sky: Sky | None
    fog: bool
    precip: Precipitation | None
    thunder: bool
    wind: Wind
    wind_max: float
    gust: float | None
    """Strongest gust, only when it reaches GUST_MENTION."""


@dataclass(frozen=True)
class DayWeather:
    label: str
    day: datetime.date
    parts: tuple[Part, ...]
    temp_min: float
    temp_max: float
    precip_from: datetime.datetime | None
    """Local; precipitation starts within the period (dry before)."""
    precip_until: datetime.datetime | None
    """Local; precipitation ends within the period (dry after)."""
    precip_mm: float
    slippery: bool
    temp_change: int | None
    """Degrees warmer (+) or colder (-) than the reference day, only when
    at least TEMP_CHANGE_MENTION."""
    sunrise: datetime.datetime | None
    """Local."""
    sunset: datetime.datetime | None


def periods(now: datetime.datetime, config: Config | None = None) -> list[Period]:
    """Before weather_evening_from: the rest of today. From then on: the
    rest of this evening and tomorrow until weather_tomorrow_until."""
    cfg = config or Config()
    now = now.astimezone(TIMEZONE)
    today = now.date()
    if now.time() < cfg.weather_evening_from:
        return [_period("idag", today, cfg.weather_day_parts, now)]
    tomorrow = today + datetime.timedelta(days=1)
    parts = [p for p in cfg.weather_day_parts if p[2] <= cfg.weather_tomorrow_until]
    result = [
        _period("ikväll", today, cfg.weather_day_parts, now),
        _period("imorgon", tomorrow, parts, now),
    ]
    return [p for p in result if p.windows]


def _period(
    label: str,
    day: datetime.date,
    parts: Iterable[tuple[str, int, int]],
    now: datetime.datetime,
) -> Period:
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    windows = []
    for name, start_h, end_h in parts:
        start = datetime.datetime.combine(day, datetime.time(start_h), TIMEZONE)
        end = datetime.datetime.combine(day, datetime.time(end_h), TIMEZONE)
        if end > now:
            windows.append(Window(name, max(start, this_hour), end))
    return Period(label, day, tuple(windows))


def summarize(
    forecast: Forecast,
    period: Period,
    lat: float,
    lon: float,
    reference: Mapping[int, float] | None = None,
) -> DayWeather | None:
    """The period's weather, or None when the forecast does not cover it.
    `reference` is another day's temperature by local hour (yesterday for
    today, today for tomorrow), see hourly_temps()."""
    parts = []
    covered: list[Step] = []
    for w in period.windows:
        steps = _steps_in(forecast, w.start, w.end)
        part = _part(w, steps)
        if part:
            parts.append(part)
            covered.extend(steps)
    if not parts:
        return None
    wet = [i for i, s in enumerate(covered) if _is_wet(s)]
    sunrise, sunset = sun.sun_times(period.day, lat, lon)
    return DayWeather(
        label=period.label,
        day=period.day,
        parts=tuple(parts),
        temp_min=min(p.temp_min for p in parts),
        temp_max=max(p.temp_max for p in parts),
        precip_from=covered[wet[0]].local_start if wet and wet[0] > 0 else None,
        precip_until=(
            covered[wet[-1]].local_end if wet and wet[-1] < len(covered) - 1 else None
        ),
        precip_mm=round(sum(_mm(s) for s in covered), 1),
        slippery=any(_slippery(s) for s in covered),
        temp_change=temp_change(hourly_temps(forecast, period.day), reference),
        sunrise=sunrise.astimezone(TIMEZONE) if sunrise else None,
        sunset=sunset.astimezone(TIMEZONE) if sunset else None,
    )


def hourly_temps(forecast: Forecast, day: datetime.date) -> dict[int, float]:
    """Temperature by local hour on `day`, from the hourly steps."""
    return {
        s.local_end.hour: s.temp
        for s in forecast.steps
        if s.hours == 1 and s.temp is not None and s.local_end.date() == day
    }


def temp_change(
    day: Mapping[int, float], reference: Mapping[int, float] | None
) -> int | None:
    """Mean difference over the daytime hours both have, rounded; None
    when too few hours match or the difference is small."""
    if not reference:
        return None
    hours = [h for h in COMPARE_HOURS if h in day and h in reference]
    if len(hours) < COMPARE_MIN_HOURS:
        return None
    delta = mean(day[h] for h in hours) - mean(reference[h] for h in hours)
    return round(delta) if abs(delta) >= TEMP_CHANGE_MENTION else None


def feels_like(temp: float, wind: float | None) -> float:
    """Wind chill (JAG/TI, as used by SMHI) for temp <= 10 °C and wind
    >= 1.3 m/s; otherwise the temperature itself."""
    if wind is None or temp > 10 or wind < 1.3:
        return temp
    v = (wind * 3.6) ** 0.16
    return 13.12 + 0.6215 * temp - 11.37 * v + 0.3965 * temp * v


def _steps_in(
    forecast: Forecast, start: datetime.datetime, end: datetime.datetime
) -> list[Step]:
    # start/end are local and the steps UTC: different tzinfo, so Python
    # compares the actual instants.
    return [s for s in forecast.steps if start < s.end <= end]


def _part(w: Window, steps: list[Step]) -> Part | None:
    temps = [s.temp for s in steps if s.temp is not None]
    if not temps:
        return None
    feels = min(feels_like(s.temp, s.wind) for s in steps if s.temp is not None)
    winds = [s.wind for s in steps if s.wind is not None]
    gusts = [s.gust for s in steps if s.gust is not None]
    wind_max = max(winds, default=0.0)
    gust = max(gusts, default=0.0)
    return Part(
        name=w.name,
        start=w.start,
        end=w.end,
        temp_min=min(temps),
        temp_max=max(temps),
        feels_like=feels if min(temps) - feels >= FEELS_LIKE_GAP else None,
        sky=_sky([s.cloud for s in steps if s.cloud is not None]),
        fog=any(
            s.symbol == FOG_SYMBOL or (s.visibility is not None and s.visibility < FOG_KM)
            for s in steps
        ),
        precip=_precipitation(steps),
        thunder=any(_has_thunder(s) for s in steps),
        wind=Wind.of(wind_max),
        wind_max=wind_max,
        gust=gust if gust >= GUST_MENTION else None,
    )


def _sky(oktas: list[int]) -> Sky | None:
    if not oktas:
        return None
    if len(oktas) >= 3 and max(oktas) - min(oktas) >= 5:
        return Sky.VARIABLE
    m = round(mean(oktas))
    if m == 0:
        return Sky.CLEAR
    if m <= 2:
        return Sky.NEARLY_CLEAR
    if m <= 4:
        return Sky.HALFCLEAR
    if m <= 6:
        return Sky.CLOUDY
    return Sky.OVERCAST


def _precipitation(steps: list[Step]) -> Precipitation | None:
    wet = [s for s in steps if _is_wet(s)]
    if not wet:
        return None
    worst = max(wet, key=lambda s: (_intensity(s), s.precip_prob or 0))
    showers = [
        _SYMBOL_PRECIP[s.symbol][2] for s in wet if s.symbol in _SYMBOL_PRECIP
    ]
    probs = [s.precip_prob for s in wet if s.precip_prob is not None]
    return Precipitation(
        kind=_kind(worst),
        intensity=_intensity(worst),
        showers=bool(showers) and all(showers),
        likely=not probs or max(probs) > LIKELY_PERCENT,
        mm=round(sum(_mm(s) for s in steps), 1),
    )


def _is_wet(s: Step) -> bool:
    if s.precip_prob is None:
        return (s.precip or 0) >= MIN_MM_H
    amount = s.precip_max if s.precip_max is not None else s.precip
    return s.precip_prob >= POSSIBLE_PERCENT and (amount or 0) >= MIN_MM_H


def _intensity(s: Step) -> Intensity:
    if s.symbol in _SYMBOL_PRECIP:
        return _SYMBOL_PRECIP[s.symbol][1]
    # No precipitation symbol (only a risk): judge by the mean amount.
    amount = s.precip or 0
    if amount < 0.5:
        return Intensity.LIGHT
    if amount < 4:
        return Intensity.MODERATE
    return Intensity.HEAVY


def _kind(s: Step) -> PrecipKind:
    from_symbol = _SYMBOL_PRECIP[s.symbol][0] if s.symbol in _SYMBOL_PRECIP else None
    if s.precip_type in _TYPE_OVERRIDES:
        kind, replaces = _TYPE_OVERRIDES[s.precip_type]
        if from_symbol in replaces:
            return kind
    if from_symbol:
        return from_symbol
    if s.precip_type in _TYPE_KIND:
        return _TYPE_KIND[s.precip_type]
    if s.frozen_part is not None:
        if s.frozen_part >= 70:
            return PrecipKind.SNOW
        if s.frozen_part >= 30:
            return PrecipKind.SLEET
    return PrecipKind.RAIN


def _has_thunder(s: Step) -> bool:
    return s.symbol in THUNDER_SYMBOLS or (s.thunder_prob or 0) >= THUNDER_PERCENT


def _slippery(s: Step) -> bool:
    if not _is_wet(s):
        return False
    return _kind(s) in FREEZING or (s.temp is not None and s.temp <= SLIPPERY_TEMP)


def _mm(s: Step) -> float:
    return (s.precip or 0) * s.hours
