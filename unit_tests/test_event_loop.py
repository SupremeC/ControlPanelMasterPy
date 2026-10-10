#!/usr/bin/env python
"""Tests for ControlPanel's event loop, timers, background jobs and the
button flows that use them.

The constructor opens nothing, so a real ControlPanel is built and its
audio, WLED, OpenAI and calendar parts are replaced with mocks. Only the
two job lanes are started. Never call ControlPanel.start() here.
"""

from concurrent.futures import Future
import datetime
from queue import Empty
import threading
import time
import unittest
import unittest.mock as mock

from daemon.audio_ctrl import SysAudioEvent as aevent
from daemon.cevent import CEvent
from daemon.controlpanel_class import ControlPanel, EFFECT_BUTTONS
from daemon.events import CalendarAlarm, MorningTest, PlaybackChanged
from daemon.gCalender import TIMEZONE
from daemon.morning import State
from daemon.packet import HWEvent, Packet


def school_event(hour: int = 9, minute: int = 10) -> CEvent:
    start = datetime.datetime.now(TIMEZONE).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return CEvent(start, "Skola", "", None, False, True, start + datetime.timedelta(hours=6))


class EventLoopTestCase(unittest.TestCase):
    def setUp(self):
        cp = ControlPanel()
        cp._audioctrl = mock.Mock()
        cp._audioctrl.current_filepath = "/tmp/rec.wav"
        cp.wled_instance = mock.Mock()
        cp.ai = mock.Mock()
        cp.cal = mock.Mock()
        cp.cal.todays_events.return_value = []
        cp.speech = mock.Mock()
        cp.weather = mock.Mock()
        cp.weather.report.return_value = mock.Mock(facts="FACTS", sentence="SENTENCE")
        for lane in (cp._audio_jobs, cp._ai_jobs, cp._wled_jobs):
            lane.start()
            self.addCleanup(lane.stop)
        self.cp = cp

    def process_until(self, predicate, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.cp.process(max_wait=0.02)
            if predicate():
                return True
        return predicate()

    def sent_packets(self) -> list:
        packets = []
        while True:
            try:
                packets.append(self.cp._packet_sendqueue.get_nowait())
            except Empty:
                return packets

    def panel_on(self):
        self.cp._ctrls.get_ctrl_by_name("masterSw").state = True
        self.cp._ctrls.get_ctrl_by_name("InputsSw").state = True


class TestDispatch(EventLoopTestCase):
    def test_packet_isHandled(self):
        # act
        self.cp._events.put(Packet(HWEvent.HELLO, 1, 1))
        self.cp.process(max_wait=0)

        # assert
        self.assertIsNotNone(self.cp._last_received_hello)

    def test_playbackChanged_blinksSpeakerLeds(self):
        # act
        self.cp._events.put(PlaybackChanged(True))
        self.cp.process(max_wait=0)

        # assert
        blinks = [p for p in self.sent_packets() if p.hw_event == HWEvent.BLINKFOREVER]
        self.assertEqual(1, len(blinks))
        self.assertEqual(1, blinks[0].val)

    def test_handlerError_isLoggedNotRaised(self):
        # arrange
        def broken(_result):
            raise RuntimeError("handler bug")

        self.cp._run_job(self.cp._audio_jobs, "x", lambda: 1, on_done=broken)

        # act / assert
        with self.assertLogs("daemon.ctrlPanel", "ERROR") as logs:
            self.process_until(lambda: False, timeout=0.3)
        self.assertTrue(
            any(
                r.exc_info and isinstance(r.exc_info[1], RuntimeError)
                for r in logs.records
            )
        )


class TestTimers(EventLoopTestCase):
    def test_callLater_runsOnlyWhenDue(self):
        # arrange
        calls = []
        self.cp.call_later(0.2, calls.append, "done")

        # act
        self.cp.process(max_wait=0)

        # assert
        self.assertEqual([], calls)
        self.assertTrue(self.process_until(lambda: calls == ["done"]))

    def test_callLater_shortensEventWait(self):
        # arrange
        calls = []
        self.cp.call_later(0.05, calls.append, "done")

        # act
        started = time.monotonic()
        self.cp.process(max_wait=1.0)

        # assert
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(["done"], calls)


class TestJobs(EventLoopTestCase):
    def test_onDone_runsOnMainThreadWithResult(self):
        # arrange
        seen = []
        self.cp._run_job(
            self.cp._audio_jobs,
            "x",
            lambda: 42,
            on_done=lambda r: seen.append((r, threading.current_thread())),
        )

        # act / assert
        self.assertTrue(self.process_until(lambda: seen))
        self.assertEqual((42, threading.current_thread()), seen[0])

    def test_failureWithoutOnError_playsFailed(self):
        # arrange
        def boom():
            raise RuntimeError("job failed")

        # act
        with self.assertLogs("daemon.ctrlPanel", "ERROR"):
            self.cp._run_job(self.cp._audio_jobs, "x", boom)
            self.assertTrue(
                self.process_until(lambda: self.cp._audioctrl.sysaudio_play.called)
            )

        # assert
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.FAILED)


def minutes_from_now(minutes: float) -> datetime.datetime:
    return datetime.datetime.now(TIMEZONE) + datetime.timedelta(minutes=minutes)


class TestMorningWiring(EventLoopTestCase):
    """The routine itself is tested in test_morning.py; these check that
    the panel feeds it and does what it asks."""

    def ring(self):
        # An alarm one minute overdue rings at once.
        self.cp._events.put(CalendarAlarm(minutes_from_now(-1)))
        self.cp.process(max_wait=0)
        self.assertEqual(State.RINGING, self.cp.morning.state)

    def press(self, pin: int, val: int = 1):
        self.cp._events.put(Packet(HWEvent.SWITCH, pin, val))
        self.cp.process(max_wait=0)

    def test_calendarAlarm_armsTheRoutine(self):
        # act
        self.cp._events.put(CalendarAlarm(minutes_from_now(120)))
        self.cp.process(max_wait=0)

        # assert
        self.assertEqual(State.ARMED, self.cp.morning.state)

    def test_ringing_alarmOverridesVolume_lightsAtEndState(self):
        # act
        self.ring()

        # assert
        audio = self.cp._audioctrl
        audio.volume_override.assert_called_once_with(True, 70)
        audio.alarm_start.assert_called_once_with(10)
        brightness, rgbw = self.cp.wled_instance.set_both.call_args.args
        self.assertEqual((255, (255, 140, 40, 255)), (brightness, rgbw))

    def test_masterSwitchOff_alarmStillRingsAndIsDismissed(self):
        # arrange
        self.assertFalse(self.cp._ctrls.get_ctrl_by_name("masterSw").state)
        self.ring()

        # act
        self.press(2)

        # assert: dismissed, the button's own sound is not played
        self.assertEqual(State.AWAKE, self.cp.morning.state)
        self.cp._audioctrl.alarm_stop.assert_called_once_with()
        self.cp._audioctrl.recsaved_play.assert_not_called()

    def test_offChime_waitsForTheAlarmToFadeOut(self):
        # arrange
        self.ring()
        started = time.monotonic()

        # act
        self.press(2)
        played = self.process_until(
            lambda: mock.call(aevent.CHIME_OFF)
            in self.cp._audioctrl.sysaudio_play.call_args_list
        )

        # assert: alarm fade-out (0.5 s) plus a 0.5 s silence
        self.assertTrue(played)
        self.assertGreaterEqual(time.monotonic() - started, 0.95)

    def test_dismissWithMasterSwitch_keepsItsStateQuietly(self):
        # arrange
        self.ring()

        # act
        self.press(12, 1)

        # assert
        self.assertTrue(self.cp._ctrls.get_ctrl_by_name("masterSw").state)
        played = [c.args[0] for c in self.cp._audioctrl.sysaudio_play.call_args_list]
        self.assertNotIn(aevent.SYSTEM_ON, played)

    def test_aiButtonAfterDismiss_chimeThenPreparedBriefing(self):
        # arrange
        self.ring()
        self.press(2)
        self.assertTrue(self.process_until(lambda: self.cp.speech.say.called))

        # act
        self.press(69)

        # assert
        self.assertTrue(
            self.process_until(lambda: self.cp.morning.state == State.DONE, timeout=5)
        )
        self.cp.speech.wake_text.assert_called_once_with(  # prepared, not again
            mock.ANY, "FACTS", school_day=False
        )
        self.cp._audioctrl.sysaudio_play.assert_any_call(aevent.CHIME_SPEAK, block=True)
        self.cp._audioctrl.play_bytes.assert_called_once_with(self.cp.speech.say.return_value)
        self.cp._audioctrl.volume_override.assert_called_with(False, 70)

    def test_aiButtonWhileRinging_dismissesAndPlaysBriefingAtOnce(self):
        # arrange
        self.ring()

        # act
        self.press(69)

        # assert
        self.assertEqual(State.BRIEFING, self.cp.morning.state)
        self.cp._audioctrl.alarm_stop.assert_called_once_with()
        self.assertTrue(
            self.process_until(lambda: self.cp.morning.state == State.DONE, timeout=5)
        )
        self.cp._audioctrl.play_bytes.assert_called_once()

    def test_schoolDay_isToldToTheWakeLine(self):
        # arrange
        self.cp.cal.todays_events.return_value = [school_event()]
        self.ring()
        self.press(2)

        # act
        self.assertTrue(self.process_until(lambda: self.cp.speech.say.called))

        # assert
        self.cp.speech.wake_text.assert_called_once_with(mock.ANY, "FACTS", school_day=True)

    def test_speechFails_onlyTheChimePlays(self):
        # arrange
        self.cp.speech.say.side_effect = RuntimeError("no network")
        with self.assertLogs("daemon.ctrlPanel", "ERROR"):
            self.ring()
            self.press(2)

            # act
            self.press(69)
            done = self.process_until(
                lambda: self.cp.morning.state == State.DONE, timeout=5
            )

        # assert
        self.assertTrue(done)
        self.cp._audioctrl.sysaudio_play.assert_any_call(aevent.CHIME_SPEAK, block=True)
        self.cp._audioctrl.play_bytes.assert_not_called()

    def test_cancelledSunrise_turnsBothStripsOff(self):
        # act
        self.cp.morning._actions.sunrise_release(off=True)

        # assert
        self.assertEqual(
            [mock.call(False, 0), mock.call(False, 1)],
            self.cp.wled_instance.set_wled_state.call_args_list,
        )

    def test_statusReply_isNotInput(self):
        # arrange
        self.ring()

        # act
        self.cp._events.put(Packet(HWEvent.STATUS, 2, 1))
        self.cp.process(max_wait=0)

        # assert
        self.assertEqual(State.RINGING, self.cp.morning.state)


class TestMorningTest(EventLoopTestCase):
    def test_signal_runsCompressedRoutine_thenRealOneIsBack(self):
        # arrange
        real = self.cp.morning

        # act
        self.cp.post(MorningTest())
        self.cp.process(max_wait=0)

        # assert
        test = self.cp.morning
        self.assertIsNot(real, test)
        self.assertEqual(State.ARMED, test.state)
        self.assertEqual(1, test._cfg.sunrise_minutes)
        self.assertEqual(9, test._cfg.alarm_ramp_seconds)
        test._handled = test._alarm  # as after a finished run
        test.state = State.IDLE
        self.cp.process(max_wait=0)
        self.assertIs(real, self.cp.morning)
        self.assertIs(self.cp._config, self.cp._morning_cfg)

    def test_calendarDuringTest_goesToTheRealRoutine(self):
        # arrange
        real = self.cp.morning
        self.cp.start_morning_test()

        # act
        self.cp._events.put(CalendarAlarm(minutes_from_now(600)))
        self.cp.process(max_wait=0)

        # assert
        self.assertEqual(State.ARMED, real.state)

    def test_whileRinging_isIgnored(self):
        # arrange
        self.cp._events.put(CalendarAlarm(minutes_from_now(-1)))
        self.cp.process(max_wait=0)

        # act
        with self.assertLogs("daemon.ctrlPanel", "WARNING"):
            self.cp.start_morning_test()

        # assert
        self.assertIs(self.cp._real_morning, self.cp.morning)


class TestWeatherRefresh(EventLoopTestCase):
    def test_refreshesOnTheAiLaneAndReschedules(self):
        # act
        self.cp._weather_refresh()

        # assert
        self.assertTrue(self.process_until(lambda: self.cp.weather.refresh.called))
        timers = [t for t in self.cp._timers if t[2] == self.cp._weather_refresh]
        self.assertEqual(1, len(timers))
        self.assertAlmostEqual(time.monotonic() + 3600, timers[0][0], delta=5)

    def test_failure_isQuiet(self):
        # arrange
        self.cp.weather.refresh.side_effect = RuntimeError("bug")

        # act
        with self.assertLogs("daemon.ctrlPanel", "ERROR"):
            self.cp._weather_refresh()
            self.process_until(lambda: False, timeout=0.3)  # let the job finish

        # assert
        self.cp._audioctrl.sysaudio_play.assert_not_called()


class TestAiButton(EventLoopTestCase):
    def test_success_blinksUntilAnswerPlayed(self):
        # arrange
        btn = mock.MagicMock()

        # act
        self.cp.ai_talk(btn, audio_call=False)

        # assert
        btn.leds[0].blink.assert_called_once_with(forever=True)
        self.assertTrue(self.process_until(lambda: btn.leds[0].blink_stop.called))
        self.cp.speech.status_text.assert_called_once_with(
            mock.ANY, [], None, "FACTS", "SENTENCE"
        )
        self.cp._audioctrl.play_bytes.assert_called_once_with(self.cp.speech.say.return_value)

    def test_noWeather_asksWithoutIt(self):
        # arrange
        btn = mock.MagicMock()
        self.cp.weather.report.return_value = None

        # act
        self.cp.ai_talk(btn, audio_call=False)

        # assert
        self.assertTrue(self.process_until(lambda: btn.leds[0].blink_stop.called))
        self.cp.speech.status_text.assert_called_once_with(mock.ANY, [], None, "", "")

    def test_failure_playsFailedAndStopsBlink(self):
        # arrange
        btn = mock.MagicMock()
        self.cp.cal.fetch.side_effect = RuntimeError("no network")

        # act
        with self.assertLogs("daemon.ctrlPanel", "ERROR"):
            self.cp.ai_talk(btn, audio_call=False)
            self.assertTrue(self.process_until(lambda: btn.leds[0].blink_stop.called))

        # assert
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.FAILED)

    def test_whileBusy_isIgnored(self):
        # arrange
        btn = mock.MagicMock()
        self.cp._ai_job = Future()  # still running

        # act
        self.cp.ai_talk(btn, audio_call=False)

        # assert
        btn.leds[0].blink.assert_not_called()


class TestEffectButton(EventLoopTestCase):
    def test_effect_rendersOnAudioLaneThenPlays(self):
        # arrange
        self.cp._audioctrl.render_effect.return_value = "/tmp/out.wav"

        # act
        self.cp.apply_soundeffect(Packet(HWEvent.SWITCH, 18, 1))

        # assert
        self.assertTrue(
            self.process_until(lambda: self.cp._audioctrl.effect_done.called)
        )
        self.cp._audioctrl.render_effect.assert_called_once_with(
            "/tmp/rec.wav", EFFECT_BUTTONS[18]
        )
        self.cp._audioctrl.effect_done.assert_called_once_with("/tmp/out.wav")

    def test_whileBusy_isIgnored(self):
        # arrange
        self.cp._effect_job = Future()  # still running

        # act
        self.cp.apply_soundeffect(Packet(HWEvent.SWITCH, 18, 1))
        self.process_until(lambda: False, timeout=0.2)

        # assert
        self.cp._audioctrl.render_effect.assert_not_called()


class TestRecordButton(EventLoopTestCase):
    def test_pressRelease_startThenStopInOrder(self):
        # arrange
        self.panel_on()
        order = []
        self.cp._audioctrl.start_recording.side_effect = lambda: order.append("start") or True
        self.cp._audioctrl.stop_recording.side_effect = lambda: order.append("stop") or "/tmp/new.wav"

        # act
        self.cp._events.put(Packet(HWEvent.SWITCH, 27, 1))
        self.cp._events.put(Packet(HWEvent.SWITCH, 27, 0))

        # assert
        self.assertTrue(
            self.process_until(lambda: self.cp._audioctrl.recording_stopped.called)
        )
        self.assertEqual(["start", "stop"], order)
        self.cp._audioctrl.prepare_recording.assert_called_once()
        self.cp._audioctrl.recording_stopped.assert_called_once_with("/tmp/new.wav")
        self.cp._audioctrl.sysaudio_play.assert_any_call(aevent.REC_STOPPED)

    def test_startFails_playsCouldNotRec(self):
        # arrange
        self.panel_on()
        self.cp._audioctrl.start_recording.return_value = False

        # act
        self.cp._events.put(Packet(HWEvent.SWITCH, 27, 1))

        # assert
        self.assertTrue(
            self.process_until(lambda: self.cp._audioctrl.sysaudio_play.called)
        )
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.REC_COULD_NOT_REC)


class TestDemoAndBedLamp(EventLoopTestCase):
    def test_demo_togglesLedsFromTheMainLoop(self):
        # arrange
        led = mock.Mock()
        led.set_led_state.return_value = [Packet(HWEvent.LED, 1, 1)]
        self.cp.demo_on = True
        self.cp._demo_leds = [led]

        # act
        self.process_until(lambda: led.set_led_state.call_count >= 2, timeout=1)
        self.cp.demo_on = False
        calls = led.set_led_state.call_count
        self.process_until(lambda: False, timeout=0.3)

        # assert
        self.assertGreaterEqual(calls, 2)
        self.assertEqual(calls, led.set_led_state.call_count, "demo must stop")

    def test_bedLamp_pulseEndsOnATimer(self):
        # arrange
        self.panel_on()
        lamp = self.cp._ctrls.get_ctrl(38).slaves[0]

        # act
        self.cp._set_relays(Packet(HWEvent.SWITCH, 38, 0), is_safetyctrl=True)

        # assert: on now, off after the pulse, without blocking the loop
        self.assertTrue(lamp.state)
        self.assertEqual(1, len(self.cp._timers))
        self.assertTrue(self.process_until(lambda: not self.cp._timers, timeout=1))
        self.assertFalse(lamp.state)


class TestSendQueue(EventLoopTestCase):
    def test_allLedsBurst_fitsInSendQueue(self):
        # arrange
        burst = self.cp._ctrls.set_all_leds(False)

        # act
        self.cp.send_packets(burst)

        # assert
        self.assertEqual(len(burst), self.cp._packet_sendqueue.qsize())
        self.cp._audioctrl.sysaudio_play.assert_not_called()


class TestWledButtons(EventLoopTestCase):
    def test_ledstripOnOff_readsStateOffTheMainThread(self):
        # arrange
        self.panel_on()
        main = threading.current_thread()
        reader = []
        state = mock.Mock()
        state.seg_state = [mock.Mock(seg_state=False)]

        def read_state():
            reader.append(threading.current_thread())
            return state

        self.cp.wled_instance.read_state.side_effect = read_state

        # act
        self.cp._events.put(Packet(HWEvent.SWITCH, 32, 1))
        self.cp.process(max_wait=0)

        # assert: the button is handled at once, the toggle follows the read
        self.assertTrue(
            self.process_until(lambda: self.cp.wled_instance.toggle_wled_state.called)
        )
        self.assertNotEqual(main, reader[0])
        self.cp.wled_instance.toggle_wled_state.assert_called_once_with(0)

    def test_masterOff_turnsWledOffOnTheLane(self):
        # arrange
        self.panel_on()

        # act
        started = time.monotonic()
        self.cp._events.put(Packet(HWEvent.SWITCH, 12, 0))
        self.cp.process(max_wait=0)

        # assert
        self.assertLess(time.monotonic() - started, 0.5)
        self.cp._audioctrl.sysaudio_play.assert_called_with(aevent.SYSTEM_OFF)
        self.assertTrue(
            self.process_until(lambda: self.cp.wled_instance.set_wled_state.called)
        )
        self.cp.wled_instance.set_wled_state.assert_called_once_with(False)


class TestCheckins(EventLoopTestCase):
    def test_leaveTime_isSchoolStartMinusTravel(self):
        # arrange
        school = school_event(9, 10)
        self.cp.cal.todays_events.return_value = [school]

        # act / assert
        self.assertEqual(school.start - datetime.timedelta(minutes=15), self.cp._leave_time())

    def test_leaveTime_noSchool_isNone(self):
        self.assertIsNone(self.cp._leave_time())

    def test_countdown_cachedTextAtCheckinVolume(self):
        # act
        self.cp._play_checkin(15, datetime.datetime.now(TIMEZONE))

        # assert
        self.cp.speech.cached.assert_called_once_with("15 minuter kvar.")
        self.cp._audioctrl.sysaudio_play.assert_called_once_with(
            aevent.CHIME_SPEAK, block=True, volume=60
        )
        self.cp._audioctrl.play_bytes.assert_called_once_with(
            self.cp.speech.cached.return_value, volume=60
        )

    def test_overview_preparedAudioIsPlayedOnce(self):
        # arrange
        leave = datetime.datetime.now(TIMEZONE)
        self.cp.speech.say.return_value = b"overview"
        self.cp._prepare_checkins(leave)

        # act
        self.cp._play_checkin(30, leave)

        # assert: made once, at prepare; the countdown texts are cached then
        self.cp.speech.overview_text.assert_called_once_with(
            mock.ANY, [], leave + datetime.timedelta(minutes=15), 30, "FACTS", "SENTENCE"
        )
        self.assertEqual(
            [mock.call("15 minuter kvar."), mock.call("5 minuter kvar. Skor och jacka."),
             mock.call("Dags att gå. Ha en bra dag!")],
            self.cp.speech.cached.call_args_list,
        )
        self.cp._audioctrl.play_bytes.assert_called_once_with(b"overview", volume=60)
        self.assertEqual({}, self.cp._overview_audio)

    def test_overviewNotPrepared_isMadeNow(self):
        # act
        self.cp._play_checkin(30, datetime.datetime.now(TIMEZONE))

        # assert
        self.cp.speech.overview_text.assert_called_once()
        self.cp._audioctrl.play_bytes.assert_called_once_with(
            self.cp.speech.say.return_value, volume=60
        )

    def test_speechFails_onlyTheChime(self):
        # arrange
        self.cp.speech.cached.side_effect = RuntimeError("no network")

        # act
        with self.assertLogs("daemon.ctrlPanel", "ERROR"):
            self.cp._play_checkin(5, datetime.datetime.now(TIMEZONE))

        # assert
        self.cp._audioctrl.sysaudio_play.assert_called_once_with(
            aevent.CHIME_SPEAK, block=True, volume=60
        )
        self.cp._audioctrl.play_bytes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
