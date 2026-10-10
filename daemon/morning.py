"""The morning routine: sunrise, alarm, dismissal, briefing and re-ring.

MorningRoutine is a state machine without I/O. It gets the time from
`now()`, runs its own tick through `call_later` and does everything
through an `Actions` object (ControlPanel). Every decision is derived
from the clock on each tick, not from counted steps, so a daemon restart
in the middle resumes at the right point.

    IDLE -> ARMED -> SUNRISE -> RINGING -> AWAKE -> BRIEFING -> DONE -> IDLE
                       |          ^  |                           |
     strip switch:     v          |  +- gives up after 15 min    |
                    WAITING ------+     (lights stay) -> IDLE    |
                                  +--- no second input 10 min ---+

- ARMED: an alarm is known. The briefing is prepared 10 min before it.
- SUNRISE: the lights belong to the routine; strip pots are ignored
  because they drift. A strip switch hands the lights back (WAITING).
- RINGING: any digital input dismisses. Not dismissed, it gets louder
  every cycle and gives up after `alarm_give_up_minutes`.
- AWAKE: the briefing plays 5 min after dismissal, or on the AI button
  (also when the AI button is what dismissed the alarm).
- DONE: waits for a second input; without one the alarm rings again
  (at most `rering_max` times). Then IDLE until the next alarm.

The volume override is on from the first ring until the briefing has
played (or the routine gives up), so speech is as loud as the alarm.
"""

import datetime
import enum
import logging
from typing import Callable, Protocol

from daemon.config import Config

logger = logging.getLogger("daemon.morning")

STRIP_SWITCHES = range(32, 38)
STRIP_POTS = range(54, 62)
ANALOG_PINS = range(54, 63)  # the strip pots and the volume pot
AI_BUTTON = 69


def alarm_ramp_level(elapsed: float, seconds: float, start: int, end: int) -> int:
    """Alarm level (percent) `elapsed` seconds into a ramp from start to
    end. The level rises by the same factor every second, which sounds
    like an even rise; a straight line would jump at first, then stall."""
    if seconds <= 0 or elapsed >= seconds:
        return end
    t = max(elapsed, 0) / seconds
    return round(start * (end / start) ** t)


class Actions(Protocol):
    """What the routine asks the panel to do. Calls come on the main
    thread and must not block."""

    def sunrise_frame(self, progress: float) -> None: ...
    # The routine stops owning the lights: off=True turns them off (the
    # sunrise was cancelled), otherwise they stay as they are.
    def sunrise_release(self, off: bool = False) -> None: ...
    def alarm_start(self, level: int) -> None: ...
    def alarm_set_level(self, level: int) -> None: ...
    def alarm_stop(self) -> None: ...
    def chime(self, kind: str) -> None: ...  # "off"
    def volume_override(self, on: bool) -> None: ...
    def briefing_prepare(self) -> None: ...
    # Plays the "speak" chime and the briefing, then the panel calls
    # MorningRoutine.briefing_finished().
    def briefing_play(self) -> None: ...


class State(enum.Enum):
    IDLE = "IDLE"
    ARMED = "ARMED"
    SUNRISE = "SUNRISE"
    WAITING = "WAITING"  # lights handed back, the alarm still rings
    RINGING = "RINGING"
    AWAKE = "AWAKE"
    BRIEFING = "BRIEFING"
    DONE = "DONE"


class MorningRoutine:
    def __init__(
        self,
        actions: Actions,
        now: Callable[[], datetime.datetime],
        call_later: Callable[[float, Callable[[], None]], None],
        config: Config | None = None,
    ):
        cfg = config or Config()
        self._actions = actions
        self._now = now
        self._call_later = call_later
        self._cfg = cfg
        self._sunrise = datetime.timedelta(minutes=cfg.sunrise_minutes)
        self._grace = datetime.timedelta(minutes=cfg.late_start_grace_minutes)
        self._prepare_lead = datetime.timedelta(
            minutes=cfg.briefing_prepare_lead_minutes
        )
        self.state = State.IDLE
        self._started = False
        self._stopped = False
        # The latest alarm from the calendar, and the one this run is for.
        self._pending: datetime.datetime | None = None
        self._alarm: datetime.datetime | None = None
        self._handled: datetime.datetime | None = None
        self._prepared_for: datetime.datetime | None = None
        self._ring_started: datetime.datetime | None = None
        self._level: int | None = None
        self._dismissed_at: datetime.datetime | None = None
        self._watching = False  # for a second input after dismissal
        self._rerings = 0
        self._briefing_played = False
        self._briefing_started: datetime.datetime | None = None

    # ---- inputs -------------------------------------------------------

    def start(self) -> None:
        """Starts the tick. Call once, on the main thread."""
        if self._started:
            return
        self._started = True
        self._call_later(self._cfg.sunrise_tick_seconds, self._tick_loop)

    def stop(self) -> None:
        """Ends the tick. The routine does nothing more after this."""
        self._stopped = True

    @property
    def handled_alarm(self) -> datetime.datetime | None:
        """The alarm of the last finished run."""
        return self._handled

    def set_alarm(self, alarm: datetime.datetime | None) -> None:
        """The next alarm from the calendar (None: there is none). Call
        after every fetch. Changes apply until the alarm starts ringing;
        after that they wait for the next run. An alarm this routine has
        already handled is ignored."""
        if alarm is not None and self._handled is not None and alarm <= self._handled:
            alarm = None
        self._pending = alarm
        self.tick()

    def on_input(self, pin: int, value: int) -> bool:
        """A switch, button or pot changed (not a status reply). Returns
        True if the routine used it up and the panel must ignore it."""
        digital = pin not in ANALOG_PINS
        state = self.state
        if state == State.SUNRISE:
            if pin in STRIP_SWITCHES:
                self._actions.sunrise_release()
                self._set_state(State.WAITING, "strip switch")
                return True
            return pin in STRIP_POTS
        if state == State.RINGING:
            if digital:
                self._dismiss()
                if pin == AI_BUTTON and self.state == State.AWAKE:
                    self._play_briefing("pulled")
                return True
            return pin in STRIP_POTS
        if not digital or state not in (State.AWAKE, State.BRIEFING, State.DONE):
            return False
        self._activity()
        if state == State.AWAKE and pin == AI_BUTTON:
            self._play_briefing("pulled")
            return True
        return False

    def briefing_finished(self) -> None:
        """The briefing has played (or failed). Called by the panel."""
        if self.state != State.BRIEFING:
            return
        self._briefing_started = None
        self._actions.volume_override(False)
        self._set_state(State.DONE, "briefing played")
        self.tick()

    def tick(self) -> None:
        """Re-evaluates the state against the clock."""
        now = self._now()
        state = self.state
        if state in (State.IDLE, State.ARMED, State.SUNRISE, State.WAITING):
            self._follow_calendar(now)
            state = self.state
        if state in (State.ARMED, State.SUNRISE, State.WAITING):
            self._before_alarm(now)
        elif state == State.RINGING:
            self._ringing(now)
        elif state == State.AWAKE:
            if now >= self._dismissed_at + self._seconds(
                self._cfg.briefing_delay_seconds
            ):
                self._play_briefing("pushed")
            else:
                self._check_rering(now)
        elif state == State.BRIEFING:
            timeout = self._seconds(self._cfg.briefing_timeout_seconds)
            if now >= self._briefing_started + timeout:
                logger.warning("morning: briefing did not finish in time")
                self.briefing_finished()
        elif state == State.DONE:
            self._check_rering(now)

    # ---- states -------------------------------------------------------

    def _follow_calendar(self, now: datetime.datetime) -> None:
        """Before the alarm rings, the run follows the calendar: a new
        alarm arms, a moved one moves, a deleted one cancels."""
        alarm = self._pending
        if alarm == self._alarm:
            return
        if self.state == State.IDLE:
            self._alarm = alarm
            self._set_state(State.ARMED, f"alarm at {alarm:%a %H:%M}")
            return
        if alarm is None:
            if self.state == State.SUNRISE:
                self._actions.sunrise_release(off=True)
            self._end_run("alarm deleted", handled=False)
            return
        logger.info("morning: alarm moved to %s", f"{alarm:%a %H:%M}")
        self._alarm = alarm
        if self.state == State.SUNRISE and now < alarm - self._sunrise:
            self._actions.sunrise_release(off=True)
            self._set_state(State.ARMED, "sunrise not due yet")

    def _before_alarm(self, now: datetime.datetime) -> None:
        alarm = self._alarm
        if now >= alarm + self._grace:
            logger.warning("morning: alarm at %s missed (daemon down?)", f"{alarm:%H:%M}")
            self._end_run("alarm missed")
            return
        if now >= alarm - self._prepare_lead and self._prepared_for != alarm:
            self._prepared_for = alarm
            self._actions.briefing_prepare()
        if now >= alarm:
            if self.state != State.WAITING:
                self._actions.sunrise_frame(1.0)
            self._ring(now)
            return
        sunrise_start = alarm - self._sunrise
        if self.state == State.ARMED and now >= sunrise_start:
            self._set_state(State.SUNRISE)
        if self.state == State.SUNRISE:
            self._actions.sunrise_frame((now - sunrise_start) / self._sunrise)

    def _ring(self, now: datetime.datetime) -> None:
        self._ring_started = now
        self._level = self._cfg.alarm_start_volume
        self._actions.volume_override(True)
        self._actions.alarm_start(self._level)
        self._set_state(State.RINGING)

    def _ringing(self, now: datetime.datetime) -> None:
        elapsed = (now - self._ring_started).total_seconds()
        if elapsed >= self._cfg.alarm_give_up_minutes * 60:
            logger.warning(
                "morning: alarm not dismissed in %s min, giving up",
                self._cfg.alarm_give_up_minutes,
            )
            self._actions.alarm_stop()
            self._actions.sunrise_release()
            self._end_run("gave up")
            return
        level = self._ring_level(elapsed)
        if level != self._level:
            self._level = level
            self._actions.alarm_set_level(level)

    def _ring_level(self, elapsed: float) -> int:
        cfg = self._cfg
        cycle = int(elapsed // cfg.alarm_cycle_seconds)
        target = min(100, cfg.alarm_volume + cycle * cfg.alarm_cycle_step)
        if cycle == 0:
            start = cfg.alarm_start_volume
        else:
            start = min(100, cfg.alarm_volume + (cycle - 1) * cfg.alarm_cycle_step)
        into_cycle = elapsed - cycle * cfg.alarm_cycle_seconds
        return alarm_ramp_level(into_cycle, cfg.alarm_ramp_seconds, start, target)

    def _dismiss(self) -> None:
        now = self._now()
        took = (now - self._ring_started).total_seconds()
        logger.info("morning metric: ring_to_dismiss=%ds ring=%d", took, self._rerings)
        self._actions.alarm_stop()
        self._actions.chime("off")
        if self._rerings == 0:
            self._actions.sunrise_release()
        self._dismissed_at = now
        self._watching = self._rerings < self._cfg.rering_max
        if self._briefing_played:
            self._actions.volume_override(False)
            self._set_state(State.DONE, "dismissed")
            self.tick()
        else:
            self._set_state(State.AWAKE, "dismissed")

    def _activity(self) -> None:
        if not self._watching:
            return
        since = (self._now() - self._dismissed_at).total_seconds()
        if since < self._cfg.activity_min_gap_seconds:
            return
        self._watching = False
        logger.info("morning metric: dismiss_to_second_input=%ds", since)
        if self.state == State.DONE:
            self.tick()

    def _check_rering(self, now: datetime.datetime) -> None:
        if self._watching:
            due = self._dismissed_at + self._seconds(self._cfg.rering_after_seconds)
            if now >= due:
                self._rerings += 1
                logger.info("morning: no second input, ringing again")
                self._ring(now)
            return
        if self.state == State.DONE:
            self._end_run("awake")

    def _play_briefing(self, how: str) -> None:
        logger.info("morning metric: briefing=%s", how)
        self._briefing_played = True
        self._briefing_started = self._now()
        self._set_state(State.BRIEFING)
        self._actions.briefing_play()

    def _end_run(self, reason: str, handled: bool = True) -> None:
        """Back to IDLE. A handled alarm is not armed again."""
        if self.state in (State.RINGING, State.AWAKE, State.BRIEFING, State.DONE):
            self._actions.volume_override(False)
        if handled:
            self._handled = self._alarm
            if self._pending is not None and self._pending <= self._handled:
                self._pending = None
        self._set_state(State.IDLE, reason)
        self._alarm = None
        self._ring_started = None
        self._level = None
        self._dismissed_at = None
        self._watching = False
        self._rerings = 0
        self._briefing_played = False
        self._briefing_started = None

    # ---- helpers ------------------------------------------------------

    def _tick_loop(self) -> None:
        if self._stopped:
            return
        try:
            self.tick()
        except Exception:
            logger.exception("morning: tick failed")
        self._call_later(self._cfg.sunrise_tick_seconds, self._tick_loop)

    def _set_state(self, state: State, reason: str = "") -> None:
        if state == self.state:
            return
        logger.info(
            "morning: %s -> %s (%s)%s",
            self.state.value,
            state.value,
            self._relative_time(),
            f" {reason}" if reason else "",
        )
        self.state = state

    def _relative_time(self) -> str:
        if self._alarm is None:
            return "no alarm"
        seconds = int((self._now() - self._alarm).total_seconds())
        sign = "-" if seconds < 0 else "+"
        minutes, secs = divmod(abs(seconds), 60)
        return f"T{sign}{minutes}:{secs:02d}"

    @staticmethod
    def _seconds(value: float) -> datetime.timedelta:
        return datetime.timedelta(seconds=value)
