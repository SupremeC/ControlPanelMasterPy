#!/usr/bin/env python
"""SMHI snow1g: parsing a saved real response, missing values, local time
and the errors. requests is mocked; nothing here touches the network.
"""

import copy
import datetime
import json
from pathlib import Path
import unittest
import unittest.mock as mock

import requests

from daemon.smhi import (
    TIMEZONE,
    PrecipType,
    SmhiError,
    fetch_forecast,
    forecast_url,
    parse_forecast,
)

# Real response fetched 2026-10-10 14:14 local time for a point in
# Stockholm, trimmed to its first 66 steps (hourly, then 3 h and 6 h).
# Its geometry is set to central Stockholm.
SAMPLE = Path(__file__).resolve().parent / "data" / "smhi_snow1g_2026-10-10.json"


def local(text: str) -> datetime.datetime:
    """Stockholm time from 'YYYY-MM-DD HH:MM'."""
    naive = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=TIMEZONE)


def item(time: str, start: str | None = None, **data) -> dict:
    """One timeSeries item. Times are UTC 'YYYY-MM-DDTHH:MM:SSZ'."""
    result = {"time": time, "data": {"air_temperature": 5.0, **data}}
    if start:
        result["intervalParametersStartTime"] = start
    return result


def response(*items: dict) -> dict:
    return {
        "createdTime": "2026-10-10T12:14:41Z",
        "referenceTime": "2026-10-10T12:00:00Z",
        "geometry": {"type": "Point", "coordinates": [18.07, 59.33]},
        "timeSeries": list(items),
    }


class TestParseSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(SAMPLE.read_text(encoding="utf-8"))
        cls.forecast = parse_forecast(cls.raw)

    def test_times(self):
        f = self.forecast
        self.assertEqual(66, len(f.steps))
        self.assertEqual(local("2026-10-10 14:14"), f.created.replace(second=0))
        self.assertEqual(local("2026-10-10 15:00"), f.steps[0].end)
        self.assertEqual(datetime.timezone.utc, f.steps[0].end.tzinfo)
        self.assertEqual("15:00", f"{f.steps[0].local_end:%H:%M}")
        self.assertEqual("Europe/Stockholm", str(f.steps[0].local_end.tzinfo))

    def test_firstStep_values(self):
        s = self.forecast.steps[0]
        self.assertEqual(local("2026-10-10 14:00"), s.start)
        self.assertEqual(6.9, s.temp)
        self.assertEqual(1.3, s.wind)
        self.assertEqual(4.0, s.gust)
        self.assertEqual(27, s.wind_dir)
        self.assertEqual(94, s.humidity)
        self.assertEqual(5.1, s.visibility)
        self.assertEqual(8, s.cloud)
        self.assertEqual(1.4, s.precip)
        self.assertEqual(1.6, s.precip_max)
        self.assertEqual(100, s.precip_prob)
        self.assertEqual(PrecipType.RAIN, s.precip_type)
        self.assertEqual(0, s.frozen_part)
        self.assertEqual(5, s.thunder_prob)
        self.assertEqual(19, s.symbol)

    def test_dryStep_hasNoFrozenPart(self):
        # 2026-10-13 00:00 UTC: no precipitation, frozen part is -9
        s = self.forecast.steps[59]
        self.assertEqual(PrecipType.NONE, s.precip_type)
        self.assertIsNone(s.frozen_part)

    def test_intervalsGrowLaterInTheForecast(self):
        steps = self.forecast.steps
        self.assertEqual(1, steps[0].hours)
        self.assertEqual(1, steps[59].hours)
        self.assertEqual(3, steps[60].hours)
        self.assertEqual(6, steps[62].hours)

    def test_stepsAreContiguous(self):
        steps = self.forecast.steps
        for before, after in zip(steps, steps[1:]):
            self.assertEqual(before.end, after.start)

    def test_rawResponseIsNotChanged(self):
        before = copy.deepcopy(self.raw)
        parse_forecast(self.raw)
        self.assertEqual(before, self.raw)


class TestParseEdgeCases(unittest.TestCase):
    def test_missingValue_isNone(self):
        raw = response(
            item("2026-10-10T13:00:00Z", wind_speed=9999, symbol_code=9999)
        )
        s = parse_forecast(raw).steps[0]
        self.assertIsNone(s.wind)
        self.assertIsNone(s.symbol)
        self.assertEqual(5.0, s.temp)

    def test_absentParameter_isNone(self):
        s = parse_forecast(response(item("2026-10-10T13:00:00Z"))).steps[0]
        self.assertIsNone(s.precip)
        self.assertIsNone(s.precip_type)

    def test_unknownPrecipType_isLoggedAndNone(self):
        raw = response(
            item("2026-10-10T13:00:00Z", predominant_precipitation_type_at_surface=42)
        )
        with self.assertLogs("daemon.smhi", "WARNING"):
            self.assertIsNone(parse_forecast(raw).steps[0].precip_type)

    def test_noIntervalStart_usesThePreviousStep(self):
        raw = response(item("2026-10-10T13:00:00Z"), item("2026-10-10T16:00:00Z"))
        first, second = parse_forecast(raw).steps
        self.assertEqual(local("2026-10-10 14:00"), first.start)
        self.assertEqual(first.end, second.start)
        self.assertEqual(3, second.hours)

    def test_dstEnd_keepsBothTwoOClocks(self):
        # 2026-10-25: 03:00 CEST becomes 02:00 CET, so 02:00 local comes twice
        raw = response(
            item("2026-10-25T00:00:00Z", "2026-10-24T23:00:00Z"),
            item("2026-10-25T01:00:00Z", "2026-10-25T00:00:00Z"),
            item("2026-10-25T02:00:00Z", "2026-10-25T01:00:00Z"),
        )
        steps = parse_forecast(raw).steps
        self.assertEqual(
            ["02:00", "02:00", "03:00"], [f"{s.local_end:%H:%M}" for s in steps]
        )
        self.assertEqual(
            ["+0200", "+0100", "+0100"], [f"{s.local_end:%z}" for s in steps]
        )
        self.assertTrue(all(s.hours == 1 for s in steps))
        self.assertTrue(steps[0].end < steps[1].end < steps[2].end)


class TestParseFormatChange(unittest.TestCase):
    def assertFormatError(self, raw):
        with self.assertRaises(SmhiError):
            parse_forecast(raw)

    def test_noTimeSeries(self):
        self.assertFormatError({"createdTime": "2026-10-10T12:14:41Z"})

    def test_emptyTimeSeries(self):
        self.assertFormatError(response())

    def test_oldPmp3gLayout(self):
        # pmp3g had validTime and a parameters list instead of time and data
        self.assertFormatError(
            {
                "approvedTime": "2026-10-10T12:00:00Z",
                "createdTime": "2026-10-10T12:00:00Z",
                "timeSeries": [
                    {
                        "validTime": "2026-10-10T13:00:00Z",
                        "parameters": [{"name": "t", "values": [6.9]}],
                    }
                ],
            }
        )

    def test_noTemperatureAnywhere(self):
        raw = response({"time": "2026-10-10T13:00:00Z", "data": {"wind_speed": 2}})
        self.assertFormatError(raw)

    def test_timeWithoutZone(self):
        self.assertFormatError(response(item("2026-10-10T13:00:00")))


class TestFetch(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("daemon.smhi.requests.get")
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def test_url(self):
        self.assertEqual(
            "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
            "/geotype/point/lon/18.0686/lat/59.3293/data.json",
            forecast_url(59.3293, 18.0686),
        )

    def test_ok_passesTheTimeoutAndParses(self):
        # arrange
        self.get.return_value.json.return_value = response(item("2026-10-10T13:00:00Z"))

        # act
        forecast = fetch_forecast(59.4, 17.9, timeout=7)

        # assert
        self.assertEqual(1, len(forecast.steps))
        self.get.assert_called_once_with(forecast_url(59.4, 17.9), timeout=7)
        self.get.return_value.raise_for_status.assert_called_once()

    def test_notFound_isSmhiError(self):
        self.get.return_value.raise_for_status.side_effect = requests.HTTPError(
            "404 Client Error: Not Found"
        )
        with self.assertRaisesRegex(SmhiError, "404"):
            fetch_forecast(59.4, 17.9, timeout=7)

    def test_timeout_isSmhiError(self):
        self.get.side_effect = requests.Timeout("read timed out")
        with self.assertRaisesRegex(SmhiError, "timed out"):
            fetch_forecast(59.4, 17.9, timeout=7)

    def test_htmlBody_isSmhiError(self):
        self.get.return_value.json.side_effect = requests.JSONDecodeError(
            "Expecting value", "<html>", 0
        )
        with self.assertRaises(SmhiError):
            fetch_forecast(59.4, 17.9, timeout=7)


if __name__ == "__main__":
    unittest.main()
