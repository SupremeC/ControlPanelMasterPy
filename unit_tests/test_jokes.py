#!/usr/bin/env python
"""daemon/jokes.py: tags for the day, picking from the rated pool, and
the memory of what was told."""

import datetime
import json
from pathlib import Path
import random
import tempfile
import unittest

from daemon.gCalender import TIMEZONE
from daemon.jokes import Joke, JokeBox, day_tags, load, pick
from daemon.weather import DayWeather, Intensity, Part, PrecipKind, Precipitation, Sky, Wind

TUESDAY = datetime.date(2026, 10, 13)


def part(sky=Sky.OVERCAST, kind: PrecipKind | None = None) -> Part:
    start = TIMEZONE.localize(datetime.datetime(2026, 10, 13, 6))
    precip = Precipitation(kind, Intensity.LIGHT, False, True, 1.0) if kind else None
    return Part("morgon", start, start + datetime.timedelta(hours=3), 5, 7, None, sky,
                False, precip, False, Wind.CALM, 2.0, None)


def day(parts, tmax=7.0, sunrise="07:00") -> DayWeather:
    rise = TIMEZONE.localize(datetime.datetime.combine(TUESDAY, datetime.time.fromisoformat(sunrise)))
    return DayWeather("idag", TUESDAY, tuple(parts), tmax - 3, tmax, None, None, 0.0,
                      False, None, rise, rise + datetime.timedelta(hours=10))


class TestDayTags(unittest.TestCase):
    def test_weekdayAlways(self):
        self.assertEqual({"tisdag"}, day_tags(TUESDAY))

    def test_rainAndCold(self):
        tags = day_tags(TUESDAY, day([part(kind=PrecipKind.RAIN)], tmax=2))
        self.assertEqual({"tisdag", "regn", "kallt"}, tags)

    def test_snow(self):
        self.assertIn("snö", day_tags(TUESDAY, day([part(kind=PrecipKind.WET_SNOW)])))
        self.assertNotIn("regn", day_tags(TUESDAY, day([part(kind=PrecipKind.SNOW)])))

    def test_sunWarmDark(self):
        tags = day_tags(TUESDAY, day([part(Sky.CLEAR), part(Sky.NEARLY_CLEAR)], tmax=20, sunrise="07:40"))
        self.assertEqual({"tisdag", "sol", "varmt", "mörkt"}, tags)

    def test_cloudy_noSun(self):
        self.assertNotIn("sol", day_tags(TUESDAY, day([part(Sky.CLEAR), part(Sky.OVERCAST)])))


class TestPick(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(1)

    def test_tagsMustAllFit(self):
        jokes = [Joke("a", "torr", ("regn", "måndag"), "A"), Joke("b", "torr", ("regn",), "B")]
        for _ in range(20):
            self.assertEqual("b", pick(jokes, {}, TUESDAY, {"tisdag", "regn"}, 45, self.rng).id)

    def test_nothingFits_none(self):
        jokes = [Joke("a", "torr", ("snö",), "A")]
        self.assertIsNone(pick(jokes, {}, TUESDAY, {"tisdag"}, 45, self.rng))

    def test_recentlyTold_isLeftOut(self):
        jokes = [Joke("a", "torr", (), "A"), Joke("b", "torr", (), "B")]
        told = {"a": "2026-10-01"}
        for _ in range(20):
            self.assertEqual("b", pick(jokes, told, TUESDAY, {"tisdag"}, 45, self.rng).id)

    def test_allTold_oldestComesBack(self):
        jokes = [Joke("a", "torr", (), "A"), Joke("b", "torr", (), "B")]
        told = {"a": "2026-10-01", "b": "2026-10-12"}
        self.assertEqual("a", pick(jokes, told, TUESDAY, {"tisdag"}, 45, self.rng).id)

    def test_weightsAndTaggedBoost(self):
        jokes = [Joke("plain", "torr", (), "A"), Joke("great", "torr", (), "B", weight=3),
                 Joke("tuesday", "torr", ("tisdag",), "C")]
        counts = {j.id: 0 for j in jokes}
        for _ in range(7000):
            counts[pick(jokes, {}, TUESDAY, {"tisdag"}, 45, self.rng).id] += 1
        # weights 1 : 3 : 3
        self.assertAlmostEqual(1000, counts["plain"], delta=150)
        self.assertAlmostEqual(3000, counts["great"], delta=250)
        self.assertAlmostEqual(3000, counts["tuesday"], delta=250)


class TestJokeBox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.pool = self.dir / "jokes.json"
        self.state = self.dir / "state.json"

    def test_noPool_none(self):
        with self.assertLogs("daemon.jokes", "INFO"):
            self.assertIsNone(JokeBox(self.pool, self.state, 45).next(TUESDAY))

    def test_brokenPool_loggedAndNone(self):
        self.pool.write_text("[{]", encoding="utf-8")
        with self.assertLogs("daemon.jokes", "ERROR"):
            self.assertEqual([], load(self.pool))

    def test_toldJokesAreRemembered(self):
        # arrange
        jokes = [{"id": "a", "style": "torr", "tags": [], "text": "A"},
                 {"id": "b", "style": "absurd", "tags": [], "text": "B", "weight": 3}]
        self.pool.write_text(json.dumps(jokes), encoding="utf-8")

        # act: two days, a fresh box each time (as after a restart)
        first = JokeBox(self.pool, self.state, 45).next(TUESDAY)
        second = JokeBox(self.pool, self.state, 45).next(TUESDAY + datetime.timedelta(days=1))

        # assert
        self.assertEqual({"a", "b"}, {first.id, second.id})
        told = json.loads(self.state.read_text(encoding="utf-8"))["told"]
        self.assertEqual({first.id: "2026-10-13", second.id: "2026-10-14"}, told)


if __name__ == "__main__":
    unittest.main()
