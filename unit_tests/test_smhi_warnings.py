#!/usr/bin/env python
"""SMHI warnings (daemon/smhi_warnings.py): parsing a saved real response,
point-in-polygon with holes and multipolygons, level and time filters.
requests is mocked; nothing here touches the network.
"""

import datetime
import json
from pathlib import Path
import unittest
import unittest.mock as mock

import requests

from daemon.smhi import TIMEZONE, SmhiError
from daemon.smhi_warnings import (
    WARNINGS_URL,
    Level,
    fetch_warnings_json,
    parse_warnings,
    relevant,
)

# Real response fetched 2026-10-10, trimmed to four warnings: water
# shortage messages for Stockholm, Uppsala and Kalmar (a multipolygon with
# Öland) and a yellow gale warning for Vänern, the central Baltic (a
# polygon with Gotland as a hole) and the Gulf of Riga.
SAMPLE = Path(__file__).resolve().parent / "data" / "smhi_warnings_2026-10-10.json"

HOME = (59.3293, 18.0686)  # central Stockholm
VISBY = (57.634, 18.294)
EAST_OF_GOTLAND = (57.5, 19.6)
VANERN = (58.95, 13.3)
KALMAR = (56.663, 16.356)
BORGHOLM = (56.879, 16.656)


def local(text: str) -> datetime.datetime:
    naive = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=TIMEZONE)


def box(lat0: float, lon0: float, lat1: float, lon1: float) -> list:
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]


def area(
    level: str = "YELLOW",
    event: str = "Mycket kraftig vind",
    start: str | None = "2026-10-12T04:00:00.000Z",
    end: str | None = "2026-10-12T16:00:00.000Z",
    geometry: dict | None = None,
    **extra,
) -> dict:
    result = {
        "areaName": {"sv": "Stockholms län"},
        "warningLevel": {"code": level},
        "eventDescription": {"sv": event},
        "normalProbability": True,
        "descriptions": [],
        "area": {
            "type": "Feature",
            "geometry": geometry or {"type": "Polygon", "coordinates": box(59, 17, 60, 19)},
        },
        **extra,
    }
    if start:
        result["approximateStart"] = start
    if end:
        result["approximateEnd"] = end
    return result


def warning(*areas: dict, descriptions: list | None = None) -> dict:
    return {"id": 1, "warningAreas": list(areas), "descriptions": descriptions or []}


MONDAY = (local("2026-10-12 06:00"), local("2026-10-12 22:00"))


class TestRealSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.warnings = parse_warnings(json.loads(SAMPLE.read_text(encoding="utf-8")))

    def named(self, name: str):
        (w,) = [w for w in self.warnings if w.area == name]
        return w

    def test_oneEntryPerArea(self):
        self.assertEqual(6, len(self.warnings))

    def test_fields(self):
        w = self.named("Vänern")
        self.assertEqual((Level.YELLOW, "Kuling 14-17 m/s", True), (w.level, w.event, w.certain))
        self.assertEqual(local("2026-10-10 10:00"), w.start.replace(microsecond=0))
        self.assertEqual(local("2026-10-10 16:00"), w.end.replace(microsecond=0))
        self.assertIn("14-17 m/s", w.text)

    def test_openEnded(self):
        self.assertIsNone(self.named("Stockholms län").end)

    def test_home_onlyHasAMessage(self):
        covering = [w.area for w in self.warnings if w.covers(*HOME)]
        self.assertEqual(["Stockholms län"], covering)
        self.assertEqual([], relevant(self.warnings, *HOME, *MONDAY))
        messages = relevant(self.warnings, *HOME, *MONDAY, min_level=Level.MESSAGE)
        self.assertEqual(["Stockholms län"], [w.area for w in messages])

    def test_hole_isOutside(self):
        baltic = self.named("Mellersta Östersjön")
        self.assertFalse(baltic.covers(*VISBY))
        self.assertTrue(baltic.covers(*EAST_OF_GOTLAND))

    def test_multipolygon(self):
        kalmar = self.named("Kalmar län")
        self.assertEqual(2, len(kalmar.polygons))
        self.assertTrue(kalmar.covers(*KALMAR))
        self.assertTrue(kalmar.covers(*BORGHOLM))
        self.assertFalse(kalmar.covers(*HOME))

    def test_timeFilter(self):
        saturday = (local("2026-10-10 06:00"), local("2026-10-10 22:00"))
        self.assertEqual(["Vänern"], [w.area for w in relevant(self.warnings, *VANERN, *saturday)])
        self.assertEqual([], relevant(self.warnings, *VANERN, *MONDAY))


class TestSynthetic(unittest.TestCase):
    def test_levelsAndOrder(self):
        raw = [
            warning(area("YELLOW", "Regn", start="2026-10-12T10:00:00Z")),
            warning(area("YELLOW", "Vind", start="2026-10-12T06:00:00Z")),
            warning(area("RED", "Storm")),
            warning(area("MESSAGE", "Brandrisk")),
        ]
        found = relevant(parse_warnings(raw), *HOME, *MONDAY)
        self.assertEqual(["Storm", "Vind", "Regn"], [w.event for w in found])

    def test_overlap(self):
        cases = [
            ("2026-10-12T20:00:00Z", None, False),  # starts after the day (22:00 local)
            ("2026-10-11T06:00:00Z", "2026-10-12T04:00:00Z", False),  # ended at 06:00
            ("2026-10-11T06:00:00Z", "2026-10-12T05:00:00Z", True),
            (None, None, True),  # in force, no end
        ]
        for start, end, expected in cases:
            with self.subTest(start=start, end=end):
                raw = [warning(area(start=start, end=end))]
                self.assertEqual(expected, bool(relevant(parse_warnings(raw), *HOME, *MONDAY)))

    def test_lessProbable(self):
        (w,) = parse_warnings([warning(area(normalProbability=False))])
        self.assertFalse(w.certain)

    def test_incidentText_fromTheWarningWhenTheAreaHasNone(self):
        incident = {"title": {"code": "INCIDENT"}, "text": {"sv": " Byar 25 m/s. "}}
        (w,) = parse_warnings([warning(area(), descriptions=[incident])])
        self.assertEqual("Byar 25 m/s.", w.text)

    def test_unknownLevelOrGeometry_isLoggedAndSkipped(self):
        raw = [
            warning(area("PURPLE")),
            warning(area(geometry={"type": "Point", "coordinates": [17.9, 59.4]})),
            warning(area()),
        ]
        with self.assertLogs("daemon.smhi_warnings", "WARNING") as logs:
            self.assertEqual(1, len(parse_warnings(raw)))
        self.assertEqual(2, len(logs.output))

    def test_formatChange_isSmhiError(self):
        for raw in ({"warnings": []}, [{"id": 1}], [warning({"areaName": {}})]):
            with self.subTest(raw=raw):
                with self.assertRaises(SmhiError):
                    parse_warnings(raw)


class TestFetch(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("daemon.smhi_warnings.requests.get")
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def test_ok(self):
        self.get.return_value.json.return_value = []
        self.assertEqual([], fetch_warnings_json(timeout=7))
        self.get.assert_called_once_with(WARNINGS_URL, timeout=7)

    def test_errors_areSmhiError(self):
        for error in (requests.HTTPError("503 Server Error"), requests.Timeout("timed out")):
            with self.subTest(error=error):
                self.get.side_effect = error
                with self.assertRaises(SmhiError):
                    fetch_warnings_json(timeout=7)


if __name__ == "__main__":
    unittest.main()
