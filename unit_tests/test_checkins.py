#!/usr/bin/env python
"""daemon/checkins.py: when the check-ins before leaving play. The clock
is a fake; tick() is called directly."""

import datetime
import unittest
import unittest.mock as mock

from daemon.checkins import Checkins
from daemon.config import Config
from daemon.gCalender import TIMEZONE


def at(text: str) -> datetime.datetime:
    return TIMEZONE.localize(datetime.datetime.strptime(f"2026-10-13 {text}", "%Y-%m-%d %H:%M"))


class CheckinsTestCase(unittest.TestCase):
    def setUp(self):
        self.now = at("07:00")
        self.leave = at("08:55")
        self.actions = mock.Mock()
        self.timers = []
        self.checkins = Checkins(
            self.actions,
            lambda: self.now,
            lambda delay, fn, *args: self.timers.append((delay, fn)),
            lambda: self.leave,
            Config(),
        )

    def at(self, text: str) -> None:
        self.now = at(text)
        self.checkins.tick()

    def played(self) -> list[int]:
        return [c.args[0] for c in self.actions.checkin_play.call_args_list]


class TestSchedule(CheckinsTestCase):
    def test_wholeMorning(self):
        # act: tick every minute from 07:00 to 09:30
        for minute in range(150):
            self.at(f"{7 + minute // 60:02d}:{minute % 60:02d}")

        # assert
        self.assertEqual([30, 15, 5, 0], self.played())
        self.actions.checkin_prepare.assert_called_once_with(self.leave)
        self.assertTrue(self.checkins.finished())

    def test_prepare_tenMinutesBeforeTheOverview(self):
        self.at("08:14")
        self.actions.checkin_prepare.assert_not_called()
        self.at("08:15")
        self.actions.checkin_prepare.assert_called_once_with(self.leave)

    def test_playsAtTheDueMinute(self):
        self.at("08:24")
        self.assertEqual([], self.played())
        self.at("08:25")
        self.actions.checkin_play.assert_called_once_with(30, self.leave)

    def test_lateStart_skipsWhatIsPast_playsTheLatestDue(self):
        # act: daemon restarted at 08:41
        with self.assertLogs("daemon.checkins", "INFO") as logs:
            self.at("08:41")

        # assert: 30 skipped, 15 (due 08:40) within the grace
        self.assertEqual([15], self.played())
        self.assertTrue(any("30 min skipped" in line for line in logs.output))
        self.actions.checkin_prepare.assert_not_called()

    def test_tooLate_nothingPlays(self):
        self.at("08:44")
        self.assertEqual([], self.played())
        self.at("08:50")
        self.assertEqual([5], self.played())

    def test_noSchool_nothing(self):
        self.leave = None
        self.at("08:25")
        self.assertEqual([], self.played())
        self.assertTrue(self.checkins.finished())

    def test_movedLater_newSchedule(self):
        self.at("08:25")
        self.leave = at("09:55")
        self.at("08:40")  # the old 15 is no longer due
        self.at("09:25")
        self.assertEqual([30, 30], self.played())

    def test_deleted_stopsTheRest(self):
        self.at("08:25")
        self.leave = None
        self.at("08:40")
        self.assertEqual([30], self.played())

    def test_scaled_forTheTest(self):
        checkins = Checkins(
            self.actions, lambda: self.now, lambda *a: None, lambda: self.leave,
            Config(), scale=0.1,
        )
        self.now = self.leave - datetime.timedelta(minutes=3)
        checkins.tick()
        self.actions.checkin_play.assert_called_once_with(30, self.leave)


class TestLoop(CheckinsTestCase):
    def test_startTicksAndReschedules(self):
        self.checkins.start()
        self.assertEqual(1, len(self.timers))
        self.timers[0][1]()
        self.assertEqual(2, len(self.timers))

    def test_stop_endsTheLoop(self):
        self.checkins.start()
        self.checkins.stop()
        self.timers[0][1]()
        self.assertEqual(1, len(self.timers))


if __name__ == "__main__":
    unittest.main()
