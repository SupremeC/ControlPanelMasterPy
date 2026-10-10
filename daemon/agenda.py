"""Which of today's calendar events the panel mentions, decided at the
moment the text is made (GH #14):

- starts later today: always;
- started at most `agenda_started_hours` ago: yes;
- started earlier, still going on and short: yes, as ongoing;
- started earlier and over: no;
- long (all day, or longer than `agenda_long_event_hours`): only in the
  morning text, on its first and last day. An event with a wrongly set,
  far-off end time is long too, so at worst it is mentioned once.

No I/O; `now` is a timezone-aware local time.
"""

from dataclasses import dataclass
import datetime
import enum

from daemon.cevent import CEvent
from daemon.config import Config


class Kind(enum.Enum):
    UPCOMING = "upcoming"
    STARTED = "started"  # a moment ago
    ONGOING = "ongoing"  # until event.end
    WHOLE_DAY = "whole_day"  # long, but only today (e.g. an all-day event)
    FIRST_DAY = "first_day"  # long, starts today, goes on until last_day
    LAST_DAY = "last_day"  # long, started before today, ends today


LONG_KINDS = (Kind.WHOLE_DAY, Kind.FIRST_DAY, Kind.LAST_DAY)


@dataclass(frozen=True)
class Item:
    event: CEvent
    kind: Kind
    last_day: datetime.date
    """The last day the event takes place."""


def last_day(event: CEvent) -> datetime.date:
    """End times are exclusive: an all-day event ends at midnight after
    its last day."""
    if event.end is None or event.end <= event.start:
        return event.start.date()
    return (event.end - datetime.timedelta(microseconds=1)).date()


def is_long(event: CEvent, config: Config) -> bool:
    if not event.has_time:
        return True
    if event.end is None:
        return False
    return event.end - event.start > datetime.timedelta(
        hours=config.agenda_long_event_hours
    )


def select(
    events: list[CEvent],
    now: datetime.datetime,
    config: Config | None = None,
    morning: bool = False,
) -> list[Item]:
    """The events worth mentioning now: long ones first (morning only),
    then the others by start time."""
    cfg = config or Config()
    items = [i for i in (_item(e, now, cfg, morning) for e in events) if i]
    return sorted(items, key=lambda i: (i.kind not in LONG_KINDS, i.event.start))


def _item(event: CEvent, now: datetime.datetime, cfg: Config, morning: bool) -> Item | None:
    today = now.date()
    last = last_day(event)
    if event.start.date() > today or last < today:
        return None
    if is_long(event, cfg):
        if not morning:
            return None
        first = event.start.date()
        if first == today == last:
            return Item(event, Kind.WHOLE_DAY, last)
        if first == today:
            return Item(event, Kind.FIRST_DAY, last)
        if last == today:
            return Item(event, Kind.LAST_DAY, last)
        return None
    if event.start > now:
        return Item(event, Kind.UPCOMING, last)
    if now - event.start <= datetime.timedelta(hours=cfg.agenda_started_hours):
        return Item(event, Kind.STARTED, last)
    if event.end is not None and event.end > now:
        return Item(event, Kind.ONGOING, last)
    return None
