"""Events that ControlPanel handles one at a time on the main thread.

Packets from the Mega go into the same queue as plain Packet objects.
"""

from concurrent.futures import Future
from dataclasses import dataclass
import datetime
from typing import Any, Callable


@dataclass(frozen=True)
class CalendarAlarm:
    """The calendar was fetched. `alarm` is the next wake-up alarm (an
    overdue one within the late-start grace included), or None."""

    alarm: datetime.datetime | None


@dataclass(frozen=True)
class MorningTest:
    """Run the whole morning routine compressed, starting now (SIGUSR1)."""


@dataclass(frozen=True)
class NightTest:
    """Run the night-off now, whatever the time (SIGUSR2)."""


@dataclass(frozen=True)
class PlaybackChanged:
    """Audio playback started (True) or stopped (False)."""

    playing: bool


@dataclass(frozen=True)
class Command:
    """A request from another thread (the web API) to run one of the
    Remote commands (daemon/remote.py) on the main thread. The command's
    result or exception goes to future. A command may itself return a
    Future (work on a job lane); its outcome is passed on when it ends."""

    name: str
    kwargs: dict
    future: Future


@dataclass(frozen=True)
class JobDone:
    """A background job finished. on_done gets the job's result and
    on_error the exception; both run on the main thread."""

    name: str
    future: Future
    on_done: Callable[[Any], None] | None = None
    on_error: Callable[[BaseException], None] | None = None
