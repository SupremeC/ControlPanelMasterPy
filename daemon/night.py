"""Night-off: the panel goes dark at `night_off_at` (22:30) because Axel
is sleeping. The backlight, every LED and the sockets in
`night_off_sockets` go off and the LED strips go to a dim red night
light; nothing is said or played. Inputs keep working: someone awake who
flips the backlight up gets it, and keeps it.

NightOff has no I/O, like Checkins and MorningRoutine. It ticks every
`night_tick_seconds` through `call_later` and derives everything from
the clock: the night window runs from `night_off_at` until `night_until`
(crossing midnight), and a night is identified by the local date of its
`night_off_at`. Inside the window the shutdown runs once per night; a
daemon restart inside the window runs it again (harmless, everything is
off). Nothing is persisted. While `active`, ControlPanel also keeps a
Mega status resync from re-lighting the backlight and the aux LEDs.

Times are local (Europe/Stockholm), so the DST changes just work: the
night of the autumn change is an hour longer and fires once.
"""

import datetime
import logging
from typing import Callable, Protocol

from daemon.config import Config
from daemon.gCalender import TIMEZONE

logger = logging.getLogger("daemon.night")


class Actions(Protocol):
    """Called on the main thread; must not block."""

    def lights_off(self) -> None: ...


class NightOff:
    def __init__(
        self,
        actions: Actions,
        now: Callable[[], datetime.datetime],
        call_later: Callable[..., object],
        config: Config | None = None,
    ):
        self._actions = actions
        self._now = now
        self._call_later = call_later
        self._cfg = config or Config()
        self._done: datetime.date | None = None  # the night already handled
        self._started: datetime.datetime | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._started = self._now()
        self._tick_loop()

    def stop(self) -> None:
        self._running = False

    @property
    def active(self) -> bool:
        """Inside the night window (night_off_at until night_until)."""
        return self._night_of(self._now()) is not None

    def tick(self) -> None:
        now = self._now()
        night = self._night_of(now)
        if night is None or night == self._done:
            return
        self._done = night
        off_at = self._off_at(night)
        if self._started is not None and self._started > off_at:
            logger.info(
                "night: lights off again (daemon started at %s)",
                f"{self._started:%H:%M}",
            )
        else:
            logger.info(
                "night: lights off, strips low red (%s; bed lamp and bed socket untouched)",
                f"{off_at:%H:%M}",
            )
        self._actions.lights_off()

    def _night_of(self, now: datetime.datetime) -> datetime.date | None:
        """The date of the night_off_at that opened the window now is in,
        or None outside the window."""
        t = now.time()
        if t >= self._cfg.night_off_at:
            return now.date()
        if t < self._cfg.night_until:
            return now.date() - datetime.timedelta(days=1)
        return None

    def _off_at(self, night: datetime.date) -> datetime.datetime:
        return TIMEZONE.localize(datetime.datetime.combine(night, self._cfg.night_off_at))

    def _tick_loop(self) -> None:
        if not self._running:
            return
        try:
            self.tick()
        except Exception:
            logger.exception("night tick failed")
        self._call_later(self._cfg.night_tick_seconds, self._tick_loop)
