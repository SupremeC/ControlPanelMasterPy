#!/usr/bin/env python
"""WeatherService (daemon/weather_service.py): cache, stale fallback, the
state file across restarts, hourly temperature history, location and
warnings. The SMHI fetches are mocked; the clock is fixed.
"""

import copy
import dataclasses
import datetime
import json
from pathlib import Path
import tempfile
import unittest
import unittest.mock as mock

from daemon.config import Config
from daemon.smhi import TIMEZONE, SmhiError
from daemon.weather_service import WeatherService

SAMPLE = Path(__file__).resolve().parent / "data" / "smhi_snow1g_2026-10-10.json"
SAMPLE_RAW = json.loads(SAMPLE.read_text(encoding="utf-8"))
HOME = (59.3293, 18.0686)  # central Stockholm


def local(text: str) -> datetime.datetime:
    naive = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=TIMEZONE)


def yellow_wind_over_home() -> list:
    lat, lon = HOME
    ring = [[lon - 1, lat - 1], [lon + 1, lat - 1], [lon + 1, lat + 1],
            [lon - 1, lat + 1], [lon - 1, lat - 1]]
    return [{
        "id": 1,
        "descriptions": [],
        "warningAreas": [{
            "areaName": {"sv": "Stockholms län"},
            "warningLevel": {"code": "YELLOW"},
            "eventDescription": {"sv": "Mycket kraftig vind"},
            "approximateStart": "2026-10-12T10:00:00Z",
            "approximateEnd": "2026-10-12T16:00:00Z",
            "normalProbability": True,
            "descriptions": [],
            "area": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}},
        }],
    }]


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.personal = self.dir / "personal.json"
        self.write_personal(location={"lat": HOME[0], "lon": HOME[1]})
        self.cfg = dataclasses.replace(
            Config(),
            personal_file=self.personal,
            weather_state_file=self.dir / "weather_state.json",
        )
        self.now = local("2026-10-12 06:35")
        patcher = mock.patch("daemon.weather_service.fetch_forecast_json")
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)
        self.fetch.side_effect = lambda *a, **kw: copy.deepcopy(SAMPLE_RAW)
        patcher = mock.patch("daemon.weather_service.fetch_warnings_json")
        self.fetch_warnings = patcher.start()
        self.addCleanup(patcher.stop)
        self.fetch_warnings.return_value = []
        self.service = self.new_service()

    def new_service(self) -> WeatherService:
        return WeatherService(self.cfg, clock=lambda: self.now)

    def write_personal(self, **data):
        self.personal.write_text(json.dumps({"name": "Kim", **data}), encoding="utf-8")

    def write_state(self, **state):
        self.cfg.weather_state_file.write_text(json.dumps({"version": 1, **state}))

    def state(self) -> dict:
        return json.loads(self.cfg.weather_state_file.read_text(encoding="utf-8"))

    def later(self, **delta):
        self.now += datetime.timedelta(**delta)


class TestReport(ServiceTestCase):
    def test_morning(self):
        report = self.service.report()
        self.assertTrue(report.facts.startswith("Väder idag, måndag 12 oktober:\n- Morgon"))
        self.assertEqual(
            "Idag blir det 7 till 9 grader och risk för lätt regn på morgonen.",
            report.sentence,
        )
        self.fetch.assert_called_once_with(*HOME, timeout=10)
        self.fetch_warnings.assert_called_once_with(10)

    def test_evening_isTonightAndTomorrow(self):
        self.now = local("2026-10-11 17:30")
        report = self.service.report()
        self.assertEqual(["ikväll", "imorgon"], [d.label for d in report.days])
        self.assertIn("\n\nVäder imorgon, måndag 12 oktober:\n", report.facts)

    def test_unexpectedError_isLoggedAndNone(self):
        self.fetch.side_effect = RuntimeError("bug")
        with self.assertLogs("daemon.weather", "ERROR"):
            self.assertIsNone(self.service.report())

    def test_forecastNotCoveringNow_isNone(self):
        self.now = local("2026-10-20 06:35")  # the sample ends on the 14th
        with self.assertLogs("daemon.weather", "WARNING"):
            self.assertIsNone(self.service.report())


class TestCache(ServiceTestCase):
    def test_freshForecast_isReused(self):
        self.service.report()
        self.later(minutes=20)
        self.service.report()
        self.assertEqual(1, self.fetch.call_count)
        self.assertEqual(1, self.fetch_warnings.call_count)
        self.later(minutes=11)
        self.service.report()
        self.assertEqual(2, self.fetch.call_count)

    def test_smhiDown_usesARecentForecast(self):
        self.service.report()
        self.later(hours=2)
        self.fetch.side_effect = SmhiError("503")
        with self.assertLogs("daemon.weather", "WARNING") as logs:
            self.assertIsNotNone(self.service.report())
        self.assertIn("Using the forecast fetched 06:35", logs.output[0])

    def test_smhiDown_tooOld_isNone(self):
        self.service.report()
        self.later(hours=7)
        self.fetch.side_effect = SmhiError("503")
        with self.assertLogs("daemon.weather", "WARNING"):
            self.assertIsNone(self.service.report())

    def test_smhiDownFromTheStart_isNone(self):
        self.fetch.side_effect = SmhiError("404")
        with self.assertLogs("daemon.weather", "WARNING"):
            self.assertIsNone(self.service.report())

    def test_restart_usesTheStateFile(self):
        self.service.report()
        self.later(hours=1)
        self.fetch.side_effect = SmhiError("timed out")
        with self.assertLogs("daemon.weather", "WARNING"):
            self.assertIsNotNone(self.new_service().report())

    def test_brokenStateFile_isIgnored(self):
        self.cfg.weather_state_file.write_text("{")
        with self.assertLogs("daemon.weather", "WARNING") as logs:
            self.assertIsNotNone(self.service.report())
        self.assertIn("is not usable", logs.output[0])
        self.assertEqual(1, self.state()["version"])  # rewritten

    def test_refresh_fetchesAndNeverRaises(self):
        self.service.refresh()
        self.assertTrue(self.cfg.weather_state_file.exists())
        self.later(hours=1)
        self.fetch.side_effect = RuntimeError("bug")
        with self.assertLogs("daemon.weather", "ERROR"):
            self.service.refresh()


class TestLocation(ServiceTestCase):
    def test_withoutLocation_centralStockholm(self):
        self.write_personal()
        self.service.report()
        self.fetch.assert_called_once_with(59.3293, 18.0686, timeout=10)

    def test_moved_refetchesAndNeverUsesTheOldPlace(self):
        self.service.report()
        self.write_personal(location={"lat": 57.7, "lon": 11.97})
        self.later(minutes=5)
        self.fetch.side_effect = SmhiError("503")
        with self.assertLogs("daemon.weather", "WARNING"):
            self.assertIsNone(self.service.report())
        self.assertEqual(mock.call(57.7, 11.97, timeout=10), self.fetch.call_args)


class TestHistory(ServiceTestCase):
    def test_colderThanYesterday(self):
        self.write_state(temps={"2026-10-11": {str(h): 15.0 for h in range(24)}})
        facts = self.service.report().facts
        self.assertIn("grader kallare än igår.", facts)

    def test_tempsMergedAndPruned(self):
        # arrange: the sample starts at 15:00 on the 10th, so 08:00 is known
        # only from an earlier fetch
        self.now = local("2026-10-10 16:00")
        self.write_state(temps={"2026-10-07": {"12": 9.0}, "2026-10-10": {"8": 3.0}})

        # act
        self.service.report()

        # assert
        temps = self.state()["temps"]
        self.assertEqual(["2026-10-10", "2026-10-11"], sorted(temps))
        self.assertEqual(3.0, temps["2026-10-10"]["8"])
        self.assertIn("16", temps["2026-10-10"])
        self.assertEqual(24, len(temps["2026-10-11"]))


class TestWarnings(ServiceTestCase):
    def test_warningOverHome(self):
        self.fetch_warnings.return_value = yellow_wind_over_home()
        report = self.service.report()
        self.assertIn(
            "Vädervarningar från SMHI:\n- Gul varning: Mycket kraftig vind, "
            "från klockan 12 till klockan 18.",
            report.facts,
        )
        self.assertTrue(report.sentence.endswith("SMHI har en gul varning för mycket kraftig vind."))

    def test_warningsDown_forecastStillThere(self):
        self.fetch_warnings.side_effect = SmhiError("503")
        with self.assertLogs("daemon.weather", "WARNING"):
            report = self.service.report()
        self.assertNotIn("Vädervarningar", report.facts)


if __name__ == "__main__":
    unittest.main()
