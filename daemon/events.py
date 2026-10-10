"""Events that ControlPanel handles one at a time on the main thread.

Packets from the Mega go into the same queue as plain Packet objects.
"""

from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CalendarAlarm:
    """The wake-up alarm in the calendar is due."""


@dataclass(frozen=True)
class SunriseDue:
    """The wake-up alarm is `minutes` away; time to start the sunrise."""

    minutes: int


@dataclass(frozen=True)
class PlaybackChanged:
    """Audio playback started (True) or stopped (False)."""

    playing: bool


@dataclass(frozen=True)
class JobDone:
    """A background job finished. on_done gets the job's result and
    on_error the exception; both run on the main thread."""

    name: str
    future: Future
    on_done: Callable[[Any], None] | None = None
    on_error: Callable[[BaseException], None] | None = None
