"""Sunrise and sunset. Pure: no I/O, no clock.

The sun's position comes from the Astronomical Almanac's low-precision
formulas (good to about 0.01° until 2050), evaluated at the event itself:
a first pass at noon, then again at the estimate. Within a minute of
published tables at Stockholm's latitude, which is plenty for "it is dark
when you leave".
"""

import datetime
import math

# The sun's centre 0.833° below the horizon: refraction plus its radius.
ZENITH = math.radians(90.833)
J2000 = datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc)
SUNRISE, SUNSET = 1, -1


def sun_times(
    day: datetime.date, lat: float, lon: float
) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    """(sunrise, sunset) in UTC for the local `day` at lat/lon (east
    positive). Both None when the sun does not rise or does not set."""
    rise = _event(day, lat, lon, SUNRISE)
    sets = _event(day, lat, lon, SUNSET)
    if rise is None or sets is None:
        return None, None
    return rise, sets


def _event(
    day: datetime.date, lat: float, lon: float, which: int
) -> datetime.datetime | None:
    midnight = datetime.datetime.combine(day, datetime.time(), datetime.timezone.utc)
    # Local solar noon, roughly; the passes below correct it.
    t = midnight + datetime.timedelta(minutes=720 - 4 * lon)
    for _ in range(2):
        eqtime, decl = _solar(t)
        phi = math.radians(lat)
        cos_ha = (math.cos(ZENITH) - math.sin(phi) * math.sin(decl)) / (
            math.cos(phi) * math.cos(decl)
        )
        if not -1 <= cos_ha <= 1:
            return None
        ha = math.degrees(math.acos(cos_ha))
        t = midnight + datetime.timedelta(minutes=720 - 4 * (lon + which * ha) - eqtime)
    return t


def _solar(t: datetime.datetime) -> tuple[float, float]:
    """Equation of time (minutes) and declination (radians) at t."""
    n = (t - J2000).total_seconds() / 86400
    mean_lon = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(mean_lon + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    decl = math.asin(math.sin(eps) * math.sin(lam))
    eqtime = 4 * ((mean_lon - ra + 180) % 360 - 180)
    return eqtime, decl
