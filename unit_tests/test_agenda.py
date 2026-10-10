#!/usr/bin/env python
"""daemon/agenda.py: which of today's events are mentioned (GH #14)."""

import datetime
import unittest

from daemon.agenda import Kind, last_day, select
from daemon.cevent import CEvent
from daemon.gCalender import TIMEZONE


def at(text: str) -> datetime.datetime:
    return TIMEZONE.localize(datetime.datetime.strptime(text, "%Y-%m-%d %H:%M"))


def timed(summary: str, start: str, end: str | None = None) -> CEvent:
    return CEvent(
        start=at(start), summary=summary, descr="", location=None,
        is_alarm=False, has_time=True, end=at(end) if end else None,
    )


def all_day(summary: str, first: str, days: int = 1) -> CEvent:
    start = at(f"{first} 00:00")
    end = TIMEZONE.localize(
        datetime.datetime.combine(start.date() + datetime.timedelta(days=days), datetime.time())
    )
    return CEvent(
        start=start, summary=summary, descr="", location=None,
        is_alarm=False, has_time=False, end=end,
    )


def kinds(events: list[CEvent], now: str, morning: bool = False) -> list[tuple[str, Kind]]:
    return [(i.event.summary, i.kind) for i in select(events, at(now), morning=morning)]


class TestShortEvents(unittest.TestCase):
    def test_upcoming_always(self):
        events = [timed("Scout", "2026-10-12 18:00", "2026-10-12 19:30")]
        self.assertEqual([("Scout", Kind.UPCOMING)], kinds(events, "2026-10-12 06:40"))

    def test_startedWithinAnHour_isMentioned(self):
        events = [timed("Lunch", "2026-10-12 12:00", "2026-10-12 12:30")]
        self.assertEqual([("Lunch", Kind.STARTED)], kinds(events, "2026-10-12 12:59"))

    def test_startedLongAgo_ongoing(self):
        events = [timed("Bouldering", "2026-10-12 14:00", "2026-10-12 17:00")]
        self.assertEqual([("Bouldering", Kind.ONGOING)], kinds(events, "2026-10-12 15:53"))

    def test_startedLongAgo_over_isDropped(self):
        events = [timed("Möte", "2026-10-12 14:00", "2026-10-12 15:00")]
        self.assertEqual([], kinds(events, "2026-10-12 15:53"))

    def test_noEndTime_countsOnlyFromStart(self):
        events = [timed("Möte", "2026-10-12 14:00")]
        self.assertEqual([("Möte", Kind.STARTED)], kinds(events, "2026-10-12 14:30"))
        self.assertEqual([], kinds(events, "2026-10-12 15:30"))

    def test_tomorrow_isDropped(self):
        events = [timed("Tandläkare", "2026-10-13 09:00", "2026-10-13 10:00")]
        self.assertEqual([], kinds(events, "2026-10-12 06:40", morning=True))

    def test_sortedByStart(self):
        events = [
            timed("B", "2026-10-12 18:00", "2026-10-12 19:00"),
            timed("A", "2026-10-12 09:00", "2026-10-12 10:00"),
        ]
        self.assertEqual(["A", "B"], [s for s, _ in kinds(events, "2026-10-12 06:40")])


class TestLongEvents(unittest.TestCase):
    def setUp(self):
        # Höstlov Mon 26 Oct - Fri 30 Oct
        self.lov = all_day("Höstlov", "2026-10-26", days=5)

    def test_onlyInTheMorning(self):
        self.assertEqual([], kinds([self.lov], "2026-10-26 06:40"))

    def test_firstDay(self):
        items = select([self.lov], at("2026-10-26 06:40"), morning=True)
        self.assertEqual(Kind.FIRST_DAY, items[0].kind)
        self.assertEqual(datetime.date(2026, 10, 30), items[0].last_day)

    def test_daysInBetween_areQuiet(self):
        self.assertEqual([], kinds([self.lov], "2026-10-28 06:40", morning=True))

    def test_lastDay(self):
        self.assertEqual(
            [("Höstlov", Kind.LAST_DAY)], kinds([self.lov], "2026-10-30 06:40", morning=True)
        )

    def test_oneAllDayEvent_isWholeDay(self):
        events = [all_day("Studiedag", "2026-10-12")]
        self.assertEqual(
            [("Studiedag", Kind.WHOLE_DAY)], kinds(events, "2026-10-12 06:40", morning=True)
        )

    def test_overEightHours_isLong(self):
        events = [timed("Utflykt", "2026-10-12 08:00", "2026-10-12 17:00")]
        self.assertEqual([], kinds(events, "2026-10-12 06:40"))
        self.assertEqual(
            [("Utflykt", Kind.WHOLE_DAY)], kinds(events, "2026-10-12 06:40", morning=True)
        )

    def test_wrongFarOffEnd_isLong(self):
        events = [timed("Gammal", "2026-10-12 07:00", "2027-03-01 07:00")]
        self.assertEqual(
            [("Gammal", Kind.FIRST_DAY)], kinds(events, "2026-10-12 06:40", morning=True)
        )
        self.assertEqual([], kinds(events, "2026-10-13 06:40", morning=True))

    def test_longEventsComeFirst(self):
        events = [timed("Scout", "2026-10-26 18:00", "2026-10-26 19:00"), self.lov]
        self.assertEqual(
            ["Höstlov", "Scout"],
            [s for s, _ in kinds(events, "2026-10-26 06:40", morning=True)],
        )

    def test_lastDay_isTheDayBeforeTheExclusiveEnd(self):
        self.assertEqual(datetime.date(2026, 10, 30), last_day(self.lov))
        midnight_end = timed("Fest", "2026-10-12 20:00", "2026-10-13 00:00")
        self.assertEqual(datetime.date(2026, 10, 12), last_day(midnight_end))


if __name__ == "__main__":
    unittest.main()
