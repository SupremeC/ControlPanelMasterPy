#!/usr/bin/env python
"""daemon/night.py with a fake clock: when the night-off fires, that it
fires once per night, and what `active` says. The clock runs NightOff's
own tick timers in time order, so a whole night takes milliseconds."""

import datetime
import heapq
import itertools
import unittest
import unittest.mock as mock

import pytz

from daemon.config import Config
from daemon.night import NightOff

TZ = pytz.timezone("Europe/Stockholm")


def at(text: str, day: str = "2026-10-12") -> datetime.datetime:
    """Local time on `day` (a Monday by default) from 'HH:MM'."""
    return TZ.localize(datetime.datetime.strptime(f"{day} {text}", "%Y-%m-%d %H:%M"))


class FakeClock:
    """Like test_morning's, but normalized after every step so the local
    time is right across a DST change."""

    def __init__(self, start: datetime.datetime):
        self.t = start
        self._timers: list = []
        self._seq = itertools.count()

    def now(self) -> datetime.datetime:
        return self.t

    def call_later(self, delay: float, fn) -> None:
        due = TZ.normalize(self.t + datetime.timedelta(seconds=delay))
        heapq.heappush(self._timers, (due, next(self._seq), fn))

    def run_until(self, when: datetime.datetime) -> None:
        while self._timers and self._timers[0][0] <= when:
            due, _, fn = heapq.heappop(self._timers)
            self.t = due
            fn()
        self.t = when


class NightTestCase(unittest.TestCase):
    def start_at(self, when: datetime.datetime) -> None:
        self.clock = FakeClock(when)
        self.actions = mock.Mock()
        self.fired: list[datetime.datetime] = []
        self.actions.lights_off.side_effect = lambda: self.fired.append(self.clock.now())
        self.night = NightOff(self.actions, self.clock.now, self.clock.call_later, Config())
        self.night.start()

    def run_until(self, text: str, day: str = "2026-10-12") -> None:
        self.clock.run_until(at(text, day))


class TestFires(NightTestCase):
    def test_at2230_withinOneTick_andOnlyOnceThatNight(self):
        # arrange
        self.start_at(at("22:00"))

        # act / assert
        self.run_until("22:29")
        self.assertEqual([], self.fired)
        self.run_until("22:31")
        self.assertEqual(1, len(self.fired))
        self.assertLessEqual(self.fired[0] - at("22:30"), datetime.timedelta(seconds=30))
        self.run_until("04:59", "2026-10-13")
        self.assertEqual(1, len(self.fired))

    def test_startInsideTheWindow_firesOnceAsAgain(self):
        # arrange / act
        with self.assertLogs("daemon.night", "INFO") as logs:
            self.start_at(at("23:15"))
            self.run_until("23:20")

        # assert
        self.assertEqual(1, len(self.fired))
        self.assertIn("again (daemon started at 23:15)", logs.output[0])
        self.run_until("04:59", "2026-10-13")
        self.assertEqual(1, len(self.fired))

    def test_firstNight_logsTheTime(self):
        # arrange / act
        with self.assertLogs("daemon.night", "INFO") as logs:
            self.start_at(at("22:00"))
            self.run_until("22:31")

        # assert
        self.assertIn("lights off, strips low red (22:30", logs.output[0])
        self.assertNotIn("again", logs.output[0])

    def test_startOutsideTheWindow_doesNotFire(self):
        for start in ("05:30", "12:00"):
            with self.subTest(start=start):
                self.start_at(at(start))
                self.run_until("21:00")
                self.assertEqual([], self.fired)

    def test_nextNight_firesAgain(self):
        # arrange
        self.start_at(at("22:00"))

        # act
        self.run_until("23:00", "2026-10-13")

        # assert
        self.assertEqual(2, len(self.fired))
        self.assertEqual(datetime.timedelta(hours=24), self.fired[1] - self.fired[0])

    def test_dstEnd_firesOnce_nextNightIs25HoursLater(self):
        # arrange: clocks go back 03:00 -> 02:00 on 2026-10-25
        self.start_at(at("22:00", "2026-10-24"))

        # act
        self.run_until("23:00", "2026-10-25")

        # assert
        self.assertEqual(2, len(self.fired))
        self.assertEqual("2026-10-24 22:30", f"{self.fired[0]:%Y-%m-%d %H:%M}")
        self.assertEqual("2026-10-25 22:30", f"{self.fired[1]:%Y-%m-%d %H:%M}")
        self.assertEqual(datetime.timedelta(hours=25), self.fired[1] - self.fired[0])

    def test_actionError_isLoggedAndTheTickGoesOn(self):
        # arrange
        self.start_at(at("22:00"))
        self.actions.lights_off.side_effect = RuntimeError("bug")

        # act
        with self.assertLogs("daemon.night", "ERROR"):
            self.run_until("22:31")
        self.actions.lights_off.side_effect = None
        self.run_until("23:00", "2026-10-13")

        # assert: the first night is still counted as handled; the next fires
        self.assertEqual(2, self.actions.lights_off.call_count)

    def test_stop_endsTheTicks(self):
        # arrange
        self.start_at(at("22:00"))

        # act
        self.night.stop()
        self.run_until("23:00")

        # assert
        self.assertEqual([], self.fired)


class TestActive(NightTestCase):
    def test_insideAndOutsideTheWindow(self):
        self.start_at(at("12:00"))
        expected = {"22:29": False, "22:30": True, "23:00": True, "03:00": True,
                    "04:59": True, "05:00": False, "05:01": False, "12:00": False}
        for text, active in expected.items():
            with self.subTest(time=text):
                self.clock.t = at(text)
                self.assertEqual(active, self.night.active)


if __name__ == "__main__":
    unittest.main()
