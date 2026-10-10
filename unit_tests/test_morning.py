#!/usr/bin/env python
"""MorningRoutine with a fake clock and a recording Actions mock.

The fake clock runs the routine's call_later timers in time order, so a
whole morning (or night) is simulated in milliseconds.
"""

import datetime
import heapq
import itertools
import unittest
import unittest.mock as mock

import pytz

from daemon.config import Config
from daemon.morning import MorningRoutine, State

TZ = pytz.timezone("Europe/Stockholm")
CFG = Config()


def at(text: str) -> datetime.datetime:
    """Local time on Monday 2026-10-12 from 'HH:MM' or 'HH:MM:SS'."""
    fmt = "%Y-%m-%d %H:%M:%S" if text.count(":") == 2 else "%Y-%m-%d %H:%M"
    return TZ.localize(datetime.datetime.strptime(f"2026-10-12 {text}", fmt))


ALARM = at("07:00")


class FakeClock:
    def __init__(self, start: datetime.datetime):
        self.t = start
        self._timers: list = []
        self._seq = itertools.count()

    def now(self) -> datetime.datetime:
        return self.t

    def call_later(self, delay: float, fn) -> None:
        due = self.t + datetime.timedelta(seconds=delay)
        heapq.heappush(self._timers, (due, next(self._seq), fn))

    def run_until(self, when: datetime.datetime) -> None:
        while self._timers and self._timers[0][0] <= when:
            due, _, fn = heapq.heappop(self._timers)
            self.t = due
            fn()
        self.t = when


class MorningTestCase(unittest.TestCase):
    start = "21:00"

    def setUp(self):
        self.clock = FakeClock(self.start_time())
        self.actions = mock.Mock()
        self.routine = MorningRoutine(
            self.actions, self.clock.now, self.clock.call_later, CFG
        )
        self.routine.start()

    def start_time(self) -> datetime.datetime:
        return at(self.start) - datetime.timedelta(days=1) if self.start >= "12" else at(self.start)

    def run_until(self, text: str) -> None:
        self.clock.run_until(at(text))

    def press(self, pin: int = 2, value: int = 1) -> bool:
        return self.routine.on_input(pin, value)

    def calls(self, name: str) -> list:
        return [c for c in self.actions.method_calls if c[0] == name]

    def frames(self) -> list[float]:
        return [c.args[0] for c in self.calls("sunrise_frame")]

    def ring_and_dismiss(self, until: str = "07:01") -> None:
        self.routine.set_alarm(ALARM)
        self.run_until(until)
        self.assertEqual(State.RINGING, self.routine.state)
        self.assertTrue(self.press())
        self.assertEqual(State.AWAKE, self.routine.state)


class TestBeforeTheAlarm(MorningTestCase):
    def test_arms_thenSunriseFromThirtyMinutesBefore(self):
        # act
        self.routine.set_alarm(ALARM)
        self.run_until("06:29:58")

        # assert
        self.assertEqual(State.ARMED, self.routine.state)
        self.assertEqual([], self.frames())
        self.run_until("06:45")
        self.assertEqual(State.SUNRISE, self.routine.state)
        frames = self.frames()
        self.assertAlmostEqual(0.0, frames[0], delta=0.01)
        self.assertAlmostEqual(0.5, frames[-1], delta=0.01)
        self.assertEqual(sorted(frames), frames)

    def test_atAlarmTime_endFrameThenRingsQuietlyWithOverride(self):
        # act
        self.routine.set_alarm(ALARM)
        self.run_until("07:00")

        # assert
        self.assertEqual(State.RINGING, self.routine.state)
        self.assertEqual(1.0, self.frames()[-1])
        names = [c[0] for c in self.actions.method_calls if c[0] != "sunrise_frame"]
        self.assertEqual(
            ["briefing_prepare", "volume_override", "alarm_start"], names
        )
        self.actions.volume_override.assert_called_once_with(True)
        self.actions.alarm_start.assert_called_once_with(CFG.alarm_start_volume)

    def test_briefingPreparedOnceTenMinutesBefore(self):
        # act
        self.routine.set_alarm(ALARM)
        self.run_until("06:49:58")
        self.actions.briefing_prepare.assert_not_called()
        self.run_until("06:59")

        # assert
        self.actions.briefing_prepare.assert_called_once_with()

    def test_stripSwitch_handsLightsBack_alarmStillRings(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("06:40")
        frames_before = len(self.frames())

        # act
        used = self.press(pin=35)
        self.run_until("07:00")

        # assert
        self.assertTrue(used)
        self.actions.sunrise_release.assert_called_once_with()
        self.assertEqual(frames_before, len(self.frames()))
        self.assertEqual(State.RINGING, self.routine.state)

    def test_sunrise_stripPotsIgnored_otherInputPasses(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("06:40")

        # act / assert
        self.assertTrue(self.press(pin=58, value=700))
        self.assertTrue(self.press(pin=54, value=10))
        self.assertFalse(self.press(pin=62, value=500))  # volume pot
        self.assertFalse(self.press(pin=2))
        self.assertEqual(State.SUNRISE, self.routine.state)

    def test_alarmDeletedDuringSunrise_lightsOffNoRing(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("06:40")

        # act
        self.routine.set_alarm(None)
        self.run_until("07:30")

        # assert
        self.assertEqual(State.IDLE, self.routine.state)
        self.actions.sunrise_release.assert_called_once_with(off=True)
        self.actions.alarm_start.assert_not_called()

    def test_deletedAlarmAddedAgain_arms(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.routine.set_alarm(None)

        # act
        self.routine.set_alarm(ALARM)

        # assert
        self.assertEqual(State.ARMED, self.routine.state)

    def test_alarmMovedLater_ringsAtNewTime(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("05:00")

        # act
        self.routine.set_alarm(at("07:30"))
        self.run_until("07:29:58")

        # assert
        self.actions.alarm_start.assert_not_called()
        self.run_until("07:30")
        self.assertEqual(State.RINGING, self.routine.state)

    def test_alarmMovedLaterDuringSunrise_restartsFromDark(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("06:45")

        # act
        self.routine.set_alarm(at("08:00"))

        # assert
        self.assertEqual(State.ARMED, self.routine.state)
        self.actions.sunrise_release.assert_called_once_with(off=True)
        self.actions.reset_mock()
        self.run_until("07:31")
        self.assertAlmostEqual(0.0, self.frames()[0], delta=0.01)


class TestRestart(MorningTestCase):
    start = "06:50"

    def test_midSunrise_resumesAtTheRightBrightness(self):
        # act
        self.routine.set_alarm(ALARM)

        # assert
        self.assertEqual(State.SUNRISE, self.routine.state)
        self.assertAlmostEqual(2 / 3, self.frames()[0], delta=0.01)
        self.actions.briefing_prepare.assert_called_once_with()


class TestLateRestart(MorningTestCase):
    start = "07:10"

    def test_withinGrace_ringsAtOnceWithLightsOn(self):
        # act
        self.routine.set_alarm(ALARM)

        # assert
        self.assertEqual(State.RINGING, self.routine.state)
        self.assertEqual([1.0], self.frames())
        self.actions.briefing_prepare.assert_called_once_with()


class TestVeryLateRestart(MorningTestCase):
    start = "07:20"

    def test_afterGrace_skippedAndLogged(self):
        # act
        with self.assertLogs("daemon.morning", "WARNING"):
            self.routine.set_alarm(ALARM)
        self.routine.set_alarm(ALARM)  # the next fetch reports it again

        # assert
        self.assertEqual(State.IDLE, self.routine.state)
        self.actions.alarm_start.assert_not_called()


class TestRinging(MorningTestCase):
    def levels(self) -> list[int]:
        return [c.args[0] for c in self.calls("alarm_set_level")]

    def test_rampsToAlarmVolumeThenEachCycleLouder(self):
        # act
        self.routine.set_alarm(ALARM)
        self.run_until("07:01:30")
        self.assertEqual(CFG.alarm_volume, self.levels()[-1])
        self.run_until("07:04")
        self.assertEqual(CFG.alarm_volume + CFG.alarm_cycle_step, self.levels()[-1])
        self.run_until("07:14")

        # assert
        self.assertEqual(100, self.levels()[-1])
        self.assertEqual(sorted(self.levels()), self.levels())

    def test_notDismissed_givesUpAfterFifteenMinutes_lightsStay(self):
        # arrange
        self.routine.set_alarm(ALARM)

        # act
        with self.assertLogs("daemon.morning", "WARNING"):
            self.run_until("07:15")

        # assert
        self.assertEqual(State.IDLE, self.routine.state)
        self.actions.alarm_stop.assert_called_once_with()
        self.actions.sunrise_release.assert_called_once_with()
        self.assertEqual(mock.call(False), self.actions.volume_override.call_args)
        self.routine.set_alarm(ALARM)  # still in the calendar
        self.assertEqual(State.IDLE, self.routine.state)

    def test_potsDoNotDismiss_stripPotsIgnored(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("07:00:30")

        # act / assert
        self.assertFalse(self.press(pin=62, value=300))
        self.assertTrue(self.press(pin=55, value=300))
        self.assertEqual(State.RINGING, self.routine.state)

    def test_anyDigitalInput_dismissesQuietly(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("07:01")

        # act
        with self.assertLogs("daemon.morning", "INFO") as logs:
            used = self.press(pin=38)

        # assert
        self.assertTrue(used)
        self.assertEqual(State.AWAKE, self.routine.state)
        self.actions.alarm_stop.assert_called_once_with()
        self.actions.chime.assert_called_once_with("off")
        self.actions.sunrise_release.assert_called_once_with()
        self.actions.briefing_play.assert_not_called()
        self.assertTrue(any("ring_to_dismiss=60s" in line for line in logs.output))


class TestAfterDismissal(MorningTestCase):
    def test_briefingPlaysFiveMinutesLater(self):
        # arrange
        self.ring_and_dismiss()

        # act
        self.run_until("07:05:58")
        self.actions.briefing_play.assert_not_called()
        with self.assertLogs("daemon.morning", "INFO") as logs:
            self.run_until("07:06")

        # assert
        self.assertEqual(State.BRIEFING, self.routine.state)
        self.actions.briefing_play.assert_called_once_with()
        self.assertTrue(any("briefing=pushed" in line for line in logs.output))

    def test_aiButton_playsBriefingNow(self):
        # arrange
        self.ring_and_dismiss()
        self.run_until("07:02")

        # act
        with self.assertLogs("daemon.morning", "INFO") as logs:
            used = self.press(pin=69)

        # assert
        self.assertTrue(used)
        self.assertEqual(State.BRIEFING, self.routine.state)
        self.assertTrue(any("briefing=pulled" in line for line in logs.output))

    def test_aiButtonWhileRinging_dismissesAndPullsBriefing(self):
        # arrange
        self.routine.set_alarm(ALARM)
        self.run_until("07:01")

        # act
        with self.assertLogs("daemon.morning", "INFO") as logs:
            used = self.press(pin=69)

        # assert
        self.assertTrue(used)
        self.assertEqual(State.BRIEFING, self.routine.state)
        self.actions.alarm_stop.assert_called_once_with()
        self.actions.chime.assert_called_once_with("off")
        self.actions.briefing_play.assert_called_once_with()
        self.assertTrue(any("briefing=pulled" in line for line in logs.output))

    def test_aiButtonOnReRing_onlyDismisses(self):
        # arrange: briefing already played, no second input
        self.ring_and_dismiss()
        self.run_until("07:06")
        self.routine.briefing_finished()
        self.run_until("07:11")
        self.assertEqual(State.RINGING, self.routine.state)

        # act
        self.press(pin=69)

        # assert
        self.assertEqual(State.DONE, self.routine.state)
        self.actions.briefing_play.assert_called_once_with()

    def test_volumeOverrideHeldUntilBriefingPlayed(self):
        # arrange
        self.ring_and_dismiss()
        self.run_until("07:06")
        self.actions.volume_override.assert_called_once_with(True)

        # act
        self.routine.briefing_finished()

        # assert
        self.assertEqual(mock.call(False), self.actions.volume_override.call_args)
        self.assertEqual(State.DONE, self.routine.state)

    def test_briefingNeverFinishes_timesOut(self):
        # arrange
        self.ring_and_dismiss()
        self.run_until("07:02")
        self.press(pin=69)

        # act
        with self.assertLogs("daemon.morning", "WARNING"):
            self.run_until("07:07")

        # assert
        self.assertEqual(mock.call(False), self.actions.volume_override.call_args)
        self.assertEqual(State.IDLE, self.routine.state)

    def test_secondInput_noReRing_runEnds(self):
        # arrange
        self.ring_and_dismiss()
        self.run_until("07:03")

        # act
        with self.assertLogs("daemon.morning", "INFO") as logs:
            used = self.press(pin=5)
        self.run_until("07:06")
        self.routine.briefing_finished()
        self.run_until("07:30")

        # assert
        self.assertFalse(used)  # the panel handles it as usual
        self.assertEqual(State.IDLE, self.routine.state)
        self.actions.alarm_start.assert_called_once()
        self.assertTrue(
            any("dismiss_to_second_input=120s" in line for line in logs.output)
        )

    def test_releaseOfTheDismissingPress_isNotASecondInput(self):
        # arrange
        self.ring_and_dismiss()

        # act
        self.press(pin=27, value=0)  # moment button release, same press
        self.run_until("07:06")
        self.routine.briefing_finished()
        self.run_until("07:11")

        # assert
        self.assertEqual(2, self.actions.alarm_start.call_count)

    def test_noSecondInput_ringsAgainAtMostTwice(self):
        # arrange
        self.ring_and_dismiss()
        self.run_until("07:06")
        self.routine.briefing_finished()

        # act: ring 2 at 07:11, dismissed; ring 3 at 07:22, dismissed
        self.run_until("07:11")
        self.assertEqual(State.RINGING, self.routine.state)
        self.assertTrue(self.press())
        self.assertEqual(State.DONE, self.routine.state)
        self.run_until("07:22")
        self.assertEqual(State.RINGING, self.routine.state)
        self.assertTrue(self.press())
        self.run_until("08:00")

        # assert
        self.assertEqual(State.IDLE, self.routine.state)
        self.assertEqual(3, self.actions.alarm_start.call_count)
        self.actions.briefing_play.assert_called_once_with()
        self.assertEqual(mock.call(False), self.actions.volume_override.call_args)

    def test_nextDaysAlarm_armsAfterTheRun(self):
        # arrange
        self.ring_and_dismiss()
        self.press(pin=69)
        tomorrow = ALARM + datetime.timedelta(days=1)

        # act
        self.routine.set_alarm(tomorrow)
        self.assertEqual(State.BRIEFING, self.routine.state)
        self.run_until("07:02")
        self.press(pin=5)
        self.routine.briefing_finished()
        self.run_until("07:02:02")

        # assert
        self.assertEqual(State.ARMED, self.routine.state)

    def test_stateChangesAreLoggedRelativeToTheAlarm(self):
        # act
        with self.assertLogs("daemon.morning", "INFO") as logs:
            self.routine.set_alarm(ALARM)
            self.run_until("07:00")

        # assert
        self.assertTrue(
            any("SUNRISE -> RINGING (T+0:00)" in line for line in logs.output)
        )


if __name__ == "__main__":
    unittest.main()
