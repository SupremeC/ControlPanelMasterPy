#!/usr/bin/env python
"""Interpreting the forecast (daemon/weather.py) and sunrise/sunset
(daemon/sun.py). Pure: synthetic steps, a saved SMHI response, no network.
"""

import dataclasses
import datetime
import json
from pathlib import Path
from typing import Iterable
import unittest

from daemon import sun
from daemon.smhi import TIMEZONE, Forecast, PrecipType, Step, parse_forecast
from daemon.weather import (
    Intensity,
    PrecipKind,
    Sky,
    Wind,
    feels_like,
    hourly_temps,
    periods,
    summarize,
    temp_change,
)

LAT, LON = 59.33, 18.07  # Stockholm, as on timeanddate.com
UTC = datetime.timezone.utc
SAMPLE = Path(__file__).resolve().parent / "data" / "smhi_snow1g_2026-10-10.json"

DRY = dict(
    temp=10.0,
    wind=2.0,
    gust=4.0,
    wind_dir=180,
    humidity=80,
    visibility=20.0,
    cloud=8,
    precip=0.0,
    precip_max=0.0,
    precip_prob=0,
    precip_type=PrecipType.NONE,
    frozen_part=None,
    thunder_prob=0,
    symbol=6,
)
RAIN = dict(
    symbol=19,
    precip=1.5,
    precip_max=2.0,
    precip_prob=90,
    precip_type=PrecipType.RAIN,
    frozen_part=0,
)


def local(text: str) -> datetime.datetime:
    """Stockholm time from 'YYYY-MM-DD HH:MM'."""
    naive = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=TIMEZONE)


def hourly(first_end: str = "2026-10-12 01:00", count: int = 47) -> list[Step]:
    """Dry hourly steps; by default all of 12 and 13 October."""
    end = local(first_end).astimezone(UTC)
    hour = datetime.timedelta(hours=1)
    return [
        Step(start=end + (i - 1) * hour, end=end + i * hour, **DRY) for i in range(count)
    ]


def change(
    steps: list[Step], hours: Iterable[int], day: int = 12, **values
) -> list[Step]:
    """Steps ending at these local hours on that October day get values."""
    hours = set(hours)
    return [
        dataclasses.replace(s, **values)
        if s.local_end.hour in hours and s.local_end.day == day
        else s
        for s in steps
    ]


def weather(steps: list[Step], now: str = "2026-10-12 06:35", reference=None, index=0):
    forecast = Forecast(created=steps[0].start, steps=tuple(steps))
    return summarize(forecast, periods(local(now))[index], LAT, LON, reference)


class TestPeriods(unittest.TestCase):
    def names(self, period) -> list[str]:
        return [w.name for w in period.windows]

    def test_morning_isAllOfToday(self):
        (p,) = periods(local("2026-10-12 06:35"))
        self.assertEqual(("idag", datetime.date(2026, 10, 12)), (p.label, p.day))
        self.assertEqual(["morgon", "förmiddag", "eftermiddag", "kväll"], self.names(p))
        self.assertEqual(local("2026-10-12 06:00"), p.windows[0].start)
        self.assertEqual(local("2026-10-12 22:00"), p.windows[-1].end)

    def test_beforeTheMorning_startsAtSix(self):
        (p,) = periods(local("2026-10-12 03:10"))
        self.assertEqual(local("2026-10-12 06:00"), p.windows[0].start)

    def test_afternoon_isTheRestOfToday(self):
        (p,) = periods(local("2026-10-12 14:20"))
        self.assertEqual(["eftermiddag", "kväll"], self.names(p))
        self.assertEqual(local("2026-10-12 14:00"), p.windows[0].start)

    def test_evening_isTonightAndTomorrow(self):
        tonight, tomorrow = periods(local("2026-10-12 17:30"))
        self.assertEqual("ikväll", tonight.label)
        self.assertEqual(["eftermiddag", "kväll"], self.names(tonight))
        self.assertEqual(("imorgon", datetime.date(2026, 10, 13)), (tomorrow.label, tomorrow.day))
        self.assertEqual(["morgon", "förmiddag", "eftermiddag"], self.names(tomorrow))

    def test_lateEvening_isOnlyTomorrow(self):
        (p,) = periods(local("2026-10-12 22:30"))
        self.assertEqual("imorgon", p.label)


class TestTemperature(unittest.TestCase):
    def test_rangeAndParts(self):
        steps = change(hourly(), range(7, 10), temp=4.0)
        steps = change(steps, range(13, 16), temp=12.5)
        w = weather(steps)
        self.assertEqual((4.0, 12.5), (w.temp_min, w.temp_max))
        morning = w.parts[0]
        self.assertEqual(("morgon", 4.0, 4.0), (morning.name, morning.temp_min, morning.temp_max))
        self.assertEqual(local("2026-10-12 06:00"), morning.start)

    def test_feelsLike_onlyWhenMuchColder(self):
        steps = change(hourly(), range(7, 10), temp=-5.0, wind=6.0)
        w = weather(steps)
        self.assertAlmostEqual(-11.8, w.parts[0].feels_like, delta=0.1)
        self.assertIsNone(w.parts[1].feels_like)  # 10 °C, light wind

    def test_windChill_matchesTheTable(self):
        self.assertAlmostEqual(-17.9, feels_like(-10, 20 / 3.6), delta=0.1)
        self.assertEqual(12.0, feels_like(12.0, 10))  # too warm
        self.assertEqual(-3.0, feels_like(-3.0, 1.0))  # too calm

    def test_change_againstReference(self):
        w = weather(hourly(), reference={h: 15.0 for h in range(24)})
        self.assertEqual(-5, w.temp_change)

    def test_change_smallOrUnknown_isNone(self):
        self.assertIsNone(weather(hourly(), reference={h: 11.5 for h in range(24)}).temp_change)
        self.assertIsNone(weather(hourly()).temp_change)
        self.assertIsNone(temp_change({h: 0.0 for h in range(24)}, {7: 9.0, 8: 9.0}))

    def test_hourlyTemps(self):
        steps = change(hourly(), [8], temp=3.0)
        forecast = Forecast(created=steps[0].start, steps=tuple(steps))
        temps = hourly_temps(forecast, datetime.date(2026, 10, 12))
        self.assertEqual(3.0, temps[8])
        self.assertEqual(23, len(temps))  # 01:00-23:00; midnight is the 13th


class TestPrecipitation(unittest.TestCase):
    def test_dryDay(self):
        w = weather(hourly())
        self.assertTrue(all(p.precip is None for p in w.parts))
        self.assertEqual((None, None, 0.0), (w.precip_from, w.precip_until, w.precip_mm))
        self.assertFalse(w.slippery)

    def test_rainyMorning_stopsAtNine(self):
        w = weather(change(hourly(), range(7, 10), **RAIN))
        p = w.parts[0].precip
        self.assertEqual(
            (PrecipKind.RAIN, Intensity.MODERATE, False, True, 4.5),
            (p.kind, p.intensity, p.showers, p.likely, p.mm),
        )
        self.assertIsNone(w.parts[1].precip)
        self.assertIsNone(w.precip_from)
        self.assertEqual(local("2026-10-12 09:00"), w.precip_until)
        self.assertEqual(4.5, w.precip_mm)

    def test_rainFromTheAfternoon(self):
        w = weather(change(hourly(), range(15, 24), **RAIN))
        self.assertEqual(local("2026-10-12 14:00"), w.precip_from)
        self.assertIsNone(w.precip_until)

    def test_onlyARisk(self):
        # no precipitation symbol, 40 % chance of a little
        steps = change(hourly(), [8], precip=0.2, precip_max=0.6, precip_prob=40,
                       precip_type=PrecipType.RAIN)
        p = weather(steps).parts[0].precip
        self.assertEqual((PrecipKind.RAIN, Intensity.LIGHT, False), (p.kind, p.intensity, p.likely))

    def test_typeWithoutAmount_isDry(self):
        # SMHI sets the type even when nothing falls
        steps = change(hourly(), range(7, 10), precip_type=PrecipType.RAIN, precip_prob=7)
        self.assertIsNone(weather(steps).parts[0].precip)

    def test_showers(self):
        steps = change(hourly(), [7], **{**RAIN, "symbol": 8})
        steps = change(steps, [8], **{**RAIN, "symbol": 9})
        p = weather(steps).parts[0].precip
        self.assertTrue(p.showers)
        self.assertEqual(Intensity.MODERATE, p.intensity)

    def test_snowAndSlippery(self):
        snow = dict(RAIN, symbol=26, precip_type=PrecipType.SNOW, frozen_part=100, temp=-2.0)
        w = weather(change(hourly(), range(7, 10), **snow))
        self.assertEqual(PrecipKind.SNOW, w.parts[0].precip.kind)
        self.assertTrue(w.slippery)

    def test_freezingRain_isSlipperyAboveZero(self):
        freezing = dict(RAIN, symbol=18, precip_type=PrecipType.FREEZING_RAIN, temp=2.0)
        w = weather(change(hourly(), range(7, 10), **freezing))
        self.assertEqual(PrecipKind.FREEZING_RAIN, w.parts[0].precip.kind)
        self.assertTrue(w.slippery)

    def test_rainAboveOneDegree_isNotSlippery(self):
        self.assertFalse(weather(change(hourly(), range(7, 10), **RAIN, temp=2.0)).slippery)

    def test_typeRefinesTheSymbol(self):
        cases = [
            (18, PrecipType.DRIZZLE, PrecipKind.DRIZZLE),
            (25, PrecipType.DRIZZLE, PrecipKind.SNOW),  # drizzle never replaces snow
            (25, PrecipType.WET_SNOW, PrecipKind.WET_SNOW),
            (9, PrecipType.HAIL, PrecipKind.HAIL),
            (22, PrecipType.RAIN_AND_SNOW, PrecipKind.SLEET),
            (6, PrecipType.SNOW, PrecipKind.SNOW),  # no precipitation symbol
        ]
        for symbol, ptype, kind in cases:
            with self.subTest(symbol=symbol, ptype=ptype):
                steps = change(hourly(), [8], **dict(RAIN, symbol=symbol, precip_type=ptype))
                self.assertEqual(kind, weather(steps).parts[0].precip.kind)

    def test_frozenPart_namesItWithoutTypeOrSymbol(self):
        steps = change(hourly(), [8], **dict(RAIN, symbol=6, precip_type=None, frozen_part=50))
        self.assertEqual(PrecipKind.SLEET, weather(steps).parts[0].precip.kind)


class TestSkyWindFlags(unittest.TestCase):
    def test_sky(self):
        cases = [([0, 0, 0], Sky.CLEAR), ([1, 2, 2], Sky.NEARLY_CLEAR),
                 ([4, 4, 3], Sky.HALFCLEAR), ([6, 5, 6], Sky.CLOUDY),
                 ([8, 8, 7], Sky.OVERCAST), ([0, 8, 1], Sky.VARIABLE)]
        for oktas, sky in cases:
            with self.subTest(oktas=oktas):
                steps = hourly()
                for hour, cloud in zip((7, 8, 9), oktas):
                    steps = change(steps, [hour], cloud=cloud)
                self.assertEqual(sky, weather(steps).parts[0].sky)

    def test_windScale(self):
        cases = [(0.2, Wind.CALM), (3.3, Wind.LIGHT), (3.4, Wind.MODERATE),
                 (8.0, Wind.FRESH), (14.0, Wind.STRONG), (25.0, Wind.STORM),
                 (33.0, Wind.HURRICANE)]
        for speed, wind in cases:
            with self.subTest(speed=speed):
                self.assertEqual(wind, Wind.of(speed))

    def test_windiestHourAndGusts(self):
        steps = change(hourly(), [8], wind=26.0, gust=35.0)
        steps = change(steps, [11], wind=6.0, gust=11.0)
        morning, late_morning = weather(steps).parts[:2]
        self.assertEqual((Wind.STORM, 26.0, 35.0), (morning.wind, morning.wind_max, morning.gust))
        self.assertEqual(Wind.MODERATE, late_morning.wind)
        self.assertIsNone(late_morning.gust)  # below GUST_MENTION

    def test_thunder(self):
        w = weather(change(hourly(), [14], thunder_prob=40))
        self.assertEqual([False, False, True, False], [p.thunder for p in w.parts])
        w = weather(change(hourly(), [8], **dict(RAIN, symbol=11)))
        self.assertTrue(w.parts[0].thunder)

    def test_fog(self):
        self.assertTrue(weather(change(hourly(), [7], symbol=7)).parts[0].fog)
        self.assertTrue(weather(change(hourly(), [8], visibility=0.4)).parts[0].fog)
        self.assertFalse(weather(hourly()).parts[0].fog)


class TestCoverage(unittest.TestCase):
    def test_partsWithoutSteps_areDropped(self):
        # the forecast starts at 13:00
        w = weather(hourly("2026-10-12 13:00", 20))
        self.assertEqual(["eftermiddag", "kväll"], [p.name for p in w.parts])

    def test_nothingCovered_isNone(self):
        self.assertIsNone(weather(hourly("2026-10-14 01:00", 10)))

    def test_eveningAndTomorrow(self):
        steps = change(hourly(), range(7, 10), day=13, **RAIN)
        tonight = weather(steps, now="2026-10-12 17:30", index=0)
        tomorrow = weather(steps, now="2026-10-12 17:30", index=1)
        self.assertEqual(["eftermiddag", "kväll"], [p.name for p in tonight.parts])
        self.assertIsNone(tonight.parts[0].precip)
        self.assertEqual("imorgon", tomorrow.label)
        self.assertEqual(PrecipKind.RAIN, tomorrow.parts[0].precip.kind)
        self.assertEqual(local("2026-10-13 09:00"), tomorrow.precip_until)


class TestRealSample(unittest.TestCase):
    def test_mondayMorningBriefing(self):
        forecast = parse_forecast(json.loads(SAMPLE.read_text(encoding="utf-8")))
        (period,) = periods(local("2026-10-12 06:35"))
        w = summarize(forecast, period, LAT, LON)
        self.assertEqual(["morgon", "förmiddag", "eftermiddag", "kväll"], [p.name for p in w.parts])
        self.assertTrue(all(-30 < p.temp_min <= p.temp_max < 40 for p in w.parts))
        self.assertLess(w.sunrise, w.sunset)
        self.assertEqual(datetime.date(2026, 10, 12), w.sunrise.date())


class TestSun(unittest.TestCase):
    # timeanddate.com, Stockholm 59.33 N 18.07 E, local time
    REFERENCE = [
        ("2026-06-21", "03:30", "22:08"),
        ("2026-12-21", "08:43", "14:48"),
        ("2026-10-10", "07:13", "17:54"),
        ("2026-10-24", "07:47", "17:15"),
        ("2026-10-25", "06:49", "16:13"),  # DST ended at 03:00
    ]

    def test_matchesPublishedTimes(self):
        for day, rise, sets in self.REFERENCE:
            with self.subTest(day=day):
                sunrise, sunset = sun.sun_times(datetime.date.fromisoformat(day), LAT, LON)
                for got, want in ((sunrise, rise), (sunset, sets)):
                    expected = local(f"{day} {want}")
                    self.assertLess(abs((got - expected).total_seconds()), 90, f"{got.astimezone(TIMEZONE)} vs {want}")

    def test_polarNightAndMidnightSun(self):
        svalbard = (78.2, 15.6)
        self.assertEqual((None, None), sun.sun_times(datetime.date(2026, 12, 21), *svalbard))
        self.assertEqual((None, None), sun.sun_times(datetime.date(2026, 6, 21), *svalbard))


if __name__ == "__main__":
    unittest.main()
