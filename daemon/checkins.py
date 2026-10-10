"""Check-ins before leaving for school (GH #14): spoken without anyone
pressing anything, at `checkin_minutes` (30, 15, 5, 0) before the leave
time. The first one is the overview of the day, prepared
`checkin_prepare_lead_minutes` ahead; the others are fixed countdown
texts.

Checkins has no I/O, like MorningRoutine. Each tick it asks `leave_time()`
(the calendar's "Skola" event minus the travel time, or None) and plays
what is due. Everything is derived from the clock, so a moved or deleted
event, a daemon restart or a new day just works:

- a check-in more than `checkin_grace_minutes` late is skipped, not
  played late;
- a moved leave time is a new schedule (its check-ins play again at
  their new times); a deleted one stops the rest.

`scale` shrinks the offsets (minutes x scale), for the SIGUSR1 test.
"""

import datetime
import logging
from typing import Callable, Protocol

from daemon.config import Config

logger = logging.getLogger("daemon.checkins")

TICK_SECONDS = 5


class Actions(Protocol):
    """Calls come on the main thread and must not block."""

    def checkin_prepare(self, leave: datetime.datetime) -> None: ...
    # minutes is the label from checkin_minutes (30 = the overview).
    def checkin_play(self, minutes: int, leave: datetime.datetime) -> None: ...


class Checkins:
    def __init__(
        self,
        actions: Actions,
        now: Callable[[], datetime.datetime],
        call_later: Callable[..., object],
        leave_time: Callable[[], datetime.datetime | None],
        config: Config | None = None,
        scale: float = 1.0,
    ):
        self._actions = actions
        self._now = now
        self._call_later = call_later
        self._leave_time = leave_time
        self._cfg = config or Config()
        self._scale = scale
        self._minutes = sorted(self._cfg.checkin_minutes, reverse=True)
        self._done: set[tuple[datetime.datetime, int]] = set()
        self._prepared: set[datetime.datetime] = set()
        self._leave: datetime.datetime | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick_loop()

    def stop(self) -> None:
        self._running = False

    @property
    def leave(self) -> datetime.datetime | None:
        """The leave time seen at the last tick."""
        return self._leave

    def finished(self) -> bool:
        """Every check-in of the current leave time is done (or none)."""
        return self._leave is None or all(
            (self._leave, m) in self._done for m in self._minutes
        )

    def tick(self) -> None:
        now = self._now()
        leave = self._leave_time()
        if leave != self._leave:
            logger.info(
                "check-ins: leave time %s",
                f"{leave:%a %H:%M}" if leave else "none",
            )
            self._leave = leave
        if leave is None or not self._minutes:
            return
        self._forget_before(now - datetime.timedelta(days=1))
        grace = datetime.timedelta(minutes=self._cfg.checkin_grace_minutes * self._scale)
        first = self._due(leave, self._minutes[0])
        prepare_at = first - self._offset(self._cfg.checkin_prepare_lead_minutes)
        if leave not in self._prepared and prepare_at <= now <= first + grace:
            self._prepared.add(leave)
            self._actions.checkin_prepare(leave)
        # Only the latest due check-in plays; earlier ones are skipped.
        due = [m for m in self._minutes if (leave, m) not in self._done and self._due(leave, m) <= now]
        for m in due:
            self._done.add((leave, m))
        if not due:
            return
        m = due[-1]
        for skipped in due[:-1]:
            logger.info("check-ins: %d min skipped (too late)", skipped)
        if now - self._due(leave, m) <= grace:
            logger.info("check-ins: %d min before %s", m, f"{leave:%H:%M}")
            self._actions.checkin_play(m, leave)
        else:
            logger.info("check-ins: %d min skipped (too late)", m)

    def _forget_before(self, moment: datetime.datetime) -> None:
        self._done = {(leave, m) for leave, m in self._done if leave >= moment}
        self._prepared = {leave for leave in self._prepared if leave >= moment}

    def _due(self, leave: datetime.datetime, minutes: int) -> datetime.datetime:
        return leave - self._offset(minutes)

    def _offset(self, minutes: float) -> datetime.timedelta:
        return datetime.timedelta(minutes=minutes * self._scale)

    def _tick_loop(self) -> None:
        if not self._running:
            return
        try:
            self.tick()
        except Exception:
            logger.exception("check-ins tick failed")
        self._call_later(TICK_SECONDS, self._tick_loop)
