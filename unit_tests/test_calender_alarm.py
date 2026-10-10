#!/usr/bin/env python
"""Calender: alarm detection, today's events, the refetch schedule, the
21:00 check for tomorrow's alarm and the temporary sunrise/alarm
callbacks. The Google service and the clock are fakes; nothing here
touches the network or starts the thread.
"""

import datetime
import unittest
import unittest.mock as mock

from googleapiclient.errors import HttpError

from daemon.gCalender import TIMEZONE, Calender


def at(text: str) -> datetime.datetime:
    """Local Stockholm time from 'YYYY-MM-DD HH:MM'."""
    return TIMEZONE.localize(datetime.datetime.strptime(text, "%Y-%m-%d %H:%M"))


def timed(summary: str, start: str) -> dict:
    return {"summary": summary, "start": {"dateTime": at(start).isoformat()}}


def all_day(summary: str, day: str) -> dict:
    return {"summary": summary, "start": {"date": day}}


class CalendarTestCase(unittest.TestCase):
    def setUp(self):
        self.now = at("2026-10-10 05:00")
        self.items: list[dict] = []
        patcher = mock.patch("daemon.gCalender.build")
        self.build = patcher.start()
        self.addCleanup(patcher.stop)
        self.list_call = self.build.return_value.events.return_value.list
        self.list_call.return_value.execute.side_effect = lambda: {
            "items": self.items
        }
        self.on_alarm = mock.Mock()
        self.on_sunrise = mock.Mock()
        self.cal = Calender(self.on_alarm, self.on_sunrise, now=lambda: self.now)
        self.cal.refresh_tokens = mock.Mock(return_value=True)

    def fetched(self, *items: dict) -> Calender:
        self.items = list(items)
        self.assertTrue(self.cal.fetch())
        return self.cal


class TestAlarmDetection(CalendarTestCase):
    def test_titleMatchIsCaseInsensitive(self):
        # act
        cal = self.fetched(timed(" WAKEUPalarm ", "2026-10-10 07:00"))

        # assert
        self.assertEqual(at("2026-10-10 07:00"), cal.next_alarm())
        self.assertEqual([], cal.todays_events())

    def test_allDayAlarmIsAnEventNotAnAlarm(self):
        # act
        cal = self.fetched(all_day("wakeUpAlarm", "2026-10-10"))

        # assert
        self.assertIsNone(cal.next_alarm())
        self.assertEqual(1, len(cal.todays_events()))

    def test_otherTitlesAreNotAlarms(self):
        # act
        cal = self.fetched(timed("wakeUpAlarm later", "2026-10-10 07:00"))

        # assert
        self.assertIsNone(cal.next_alarm())

    def test_nextAlarm_isFirstAtOrAfterNow(self):
        # arrange
        cal = self.fetched(
            timed("wakeUpAlarm", "2026-10-11 06:45"),
            timed("wakeUpAlarm", "2026-10-10 04:30"),
            timed("wakeUpAlarm", "2026-10-10 07:00"),
        )

        # act / assert
        self.assertEqual(at("2026-10-10 07:00"), cal.next_alarm())
        self.assertEqual(
            at("2026-10-10 04:30"), cal.next_alarm(at("2026-10-10 04:00"))
        )
        self.now = at("2026-10-10 07:01")
        self.assertEqual(at("2026-10-11 06:45"), cal.next_alarm())

    def test_noAlarm_isNone(self):
        # act
        cal = self.fetched(timed("Dentist", "2026-10-10 09:00"))

        # assert
        self.assertIsNone(cal.next_alarm())


class TestFetch(CalendarTestCase):
    def test_asksForTodayAndTomorrowInLocalTime(self):
        # act
        self.fetched()

        # assert
        kwargs = self.list_call.call_args.kwargs
        self.assertEqual("2026-10-10T00:00:00+02:00", kwargs["timeMin"])
        self.assertEqual("2026-10-12T00:00:00+02:00", kwargs["timeMax"])

    def test_todaysEvents_leavesOutTomorrowAndAlarms(self):
        # act
        cal = self.fetched(
            all_day("Holiday", "2026-10-10"),
            timed("wakeUpAlarm", "2026-10-10 07:00"),
            timed("Football", "2026-10-10 17:00"),
            timed("Dentist", "2026-10-11 09:00"),
        )

        # assert
        self.assertEqual(
            ["Holiday", "Football"], [e.summary for e in cal.todays_events()]
        )

    def test_utcStartIsShownInLocalTime(self):
        # act
        self.items = [
            {"summary": "Football", "start": {"dateTime": "2026-10-10T15:00:00Z"}}
        ]
        self.cal.fetch()

        # assert
        self.assertEqual(at("2026-10-10 17:00"), self.cal.todays_events()[0].start)

    def test_eventsStartedBeforeToday_areIgnored(self):
        # Google lists events that started long ago but have not ended,
        # e.g. a recurring alarm whose end time is months after its start.
        cal = self.fetched(
            timed("wakeUpAlarm", "2026-01-26 06:45"),
            timed("Holiday trip", "2026-10-09 10:00"),
            timed("wakeUpAlarm", "2026-10-11 06:45"),
        )

        # assert
        self.assertEqual([at("2026-10-11 06:45")], cal._alarms)
        self.assertEqual([], cal.todays_events())

    def test_readsAllPages(self):
        # arrange: the real alarm only on the second page
        pages = [
            {"items": [timed("wakeUpAlarm", "2026-01-26 06:45")], "nextPageToken": "p2"},
            {"items": [timed("wakeUpAlarm", "2026-10-11 06:45")]},
        ]
        self.list_call.return_value.execute.side_effect = pages

        # act
        self.assertTrue(self.cal.fetch())

        # assert
        self.assertEqual(at("2026-10-11 06:45"), self.cal.next_alarm())
        tokens = [c.kwargs["pageToken"] for c in self.list_call.call_args_list]
        self.assertEqual([None, "p2"], tokens)

    def test_httpError_keepsLastEvents(self):
        # arrange
        cal = self.fetched(timed("wakeUpAlarm", "2026-10-10 07:00"))
        self.list_call.return_value.execute.side_effect = HttpError(
            mock.Mock(status=500), b"boom"
        )

        # act
        with self.assertLogs("daemon.gCalender", "ERROR"):
            ok = cal.fetch()

        # assert
        self.assertFalse(ok)
        self.assertEqual(at("2026-10-10 07:00"), cal.next_alarm())

    def test_noToken_keepsLastEventsAndSkipsApi(self):
        # arrange
        cal = self.fetched(timed("wakeUpAlarm", "2026-10-10 07:00"))
        self.build.reset_mock()
        cal.refresh_tokens.return_value = False

        # act
        ok = cal.fetch()

        # assert
        self.assertFalse(ok)
        self.build.assert_not_called()
        self.assertEqual(at("2026-10-10 07:00"), cal.next_alarm())


class TestRefetchSchedule(CalendarTestCase):
    def next_fetch(self, now: str, *items: dict) -> datetime.datetime:
        self.fetched(*items)
        return self.cal._next_fetch_time(at(now))

    def test_beforeFour_waitsAtMostUntilFour(self):
        self.assertEqual(at("2026-10-10 04:00"), self.next_fetch("2026-10-10 03:00"))

    def test_afterFour_beforeAlarm_isNear(self):
        alarm = timed("wakeUpAlarm", "2026-10-10 07:00")
        self.assertEqual(
            at("2026-10-10 05:15"), self.next_fetch("2026-10-10 05:00", alarm)
        )

    def test_afterFour_noAlarmToday_isNear(self):
        # An alarm added late in the morning is still seen in time.
        self.assertEqual(at("2026-10-10 09:15"), self.next_fetch("2026-10-10 09:00"))

    def test_afterAlarmRang_isFar(self):
        alarm = timed("wakeUpAlarm", "2026-10-10 07:00")
        self.assertEqual(
            at("2026-10-10 09:05"), self.next_fetch("2026-10-10 07:05", alarm)
        )

    def test_far_waitsAtMostUntilTwentyOne(self):
        alarm = timed("wakeUpAlarm", "2026-10-10 07:00")
        self.assertEqual(
            at("2026-10-10 21:00"), self.next_fetch("2026-10-10 20:00", alarm)
        )

    def test_lateEvening_isFar(self):
        alarm = timed("wakeUpAlarm", "2026-10-10 07:00")
        self.assertEqual(
            at("2026-10-11 00:30"), self.next_fetch("2026-10-10 22:30", alarm)
        )

    def test_update_fetchesOnlyWhenDue(self):
        # arrange
        self.cal._update()
        self.now = at("2026-10-10 05:14")

        # act
        self.cal._update()
        self.now = at("2026-10-10 05:15")
        self.cal._update()

        # assert
        self.assertEqual(2, self.list_call.call_count)


class TestTomorrowCheck(CalendarTestCase):
    def test_atTwentyOne_noAlarmTomorrow_warnsOnce(self):
        # arrange
        self.items = [timed("wakeUpAlarm", "2026-10-10 07:00")]
        self.now = at("2026-10-10 21:00")

        # act
        with self.assertLogs("daemon.gCalender", "WARNING") as logs:
            self.cal._update()
        self.now = at("2026-10-10 23:00")
        with self.assertNoLogs("daemon.gCalender", "WARNING"):
            self.cal._update()

        # assert
        self.assertIn("2026-10-11", logs.output[0])

    def test_atTwentyOne_alarmTomorrow_logsItsTime(self):
        # arrange
        self.items = [timed("wakeUpAlarm", "2026-10-11 06:45")]
        self.now = at("2026-10-10 21:00")

        # act
        with self.assertLogs("daemon.gCalender", "INFO") as logs:
            self.cal._update()

        # assert
        self.assertTrue(any("tomorrow at 06:45" in line for line in logs.output))
        self.assertFalse(any("WARNING" in line for line in logs.output))

    def test_beforeTwentyOne_noCheck(self):
        # arrange
        self.now = at("2026-10-10 20:59")

        # act / assert
        with self.assertNoLogs("daemon.gCalender", "WARNING"):
            self.cal._update()

    def test_failedFetch_noWarning(self):
        # arrange
        self.cal.refresh_tokens.return_value = False
        self.now = at("2026-10-10 21:00")

        # act / assert
        with self.assertNoLogs("daemon.gCalender", "WARNING"):
            self.cal._update()


class TestOldCallbacks(CalendarTestCase):
    def setUp(self):
        super().setUp()
        self.items = [timed("wakeUpAlarm", "2026-10-10 07:00")]

    def run_at(self, *times: str) -> None:
        for t in times:
            self.now = at(t)
            self.cal._update()

    def test_sunriseAtThirtyMinutesBefore_alarmAtTime_eachOnce(self):
        # act / assert
        self.run_at("2026-10-10 06:29")
        self.on_sunrise.assert_not_called()
        self.run_at("2026-10-10 06:30", "2026-10-10 06:31")
        self.on_sunrise.assert_called_once_with(30)
        self.on_alarm.assert_not_called()
        self.run_at("2026-10-10 07:00", "2026-10-10 07:01", "2026-10-10 07:20")
        self.on_alarm.assert_called_once_with()

    def test_deletedAlarm_firesNothing(self):
        # arrange
        self.run_at("2026-10-10 06:00")
        self.items = []
        self.cal._next_fetch = None  # due now

        # act
        self.run_at("2026-10-10 06:30", "2026-10-10 07:00")

        # assert
        self.on_sunrise.assert_not_called()
        self.on_alarm.assert_not_called()

    def test_restartShortlyAfterAlarm_ringsWithoutSunrise(self):
        # act
        self.run_at("2026-10-10 07:10")

        # assert
        self.on_alarm.assert_called_once_with()
        self.on_sunrise.assert_not_called()

    def test_restartLongAfterAlarm_doesNotRing(self):
        # act
        self.run_at("2026-10-10 07:20")

        # assert
        self.on_sunrise.assert_not_called()
        self.on_alarm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
