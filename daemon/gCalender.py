import datetime
import threading
import logging
from pathlib import Path
from typing import Callable, List
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pytz

from daemon.cevent import CEvent
from daemon.config import Config


logger = logging.getLogger("daemon.gCalender")

TIMEZONE = pytz.timezone("Europe/Stockholm")
PAGE_SIZE = 250  # the API maximum
MAX_PAGES = 10


def _local_now() -> datetime.datetime:
    return datetime.datetime.now(TIMEZONE)


def _local_midnight(day: datetime.date) -> datetime.datetime:
    return TIMEZONE.localize(datetime.datetime.combine(day, datetime.time()))


def _next_at(now: datetime.datetime, at: datetime.time) -> datetime.datetime:
    """The first local time `at` after now."""
    due = TIMEZONE.localize(datetime.datetime.combine(now.date(), at))
    if due <= now:
        due = TIMEZONE.localize(
            datetime.datetime.combine(now.date() + datetime.timedelta(days=1), at)
        )
    return due


class Calender:
    """Today's and tomorrow's events from the primary Google calendar.

    A thread refetches them: every `refetch_near` seconds from
    `refetch_near_from` (local time) until today's alarm has rung, every
    `refetch_far` seconds otherwise. An event titled `alarm_title`
    (case-insensitive, with a time of day) is a wake-up alarm; next_alarm()
    returns the next one. At `alarm_check_at` the log says whether tomorrow
    has an alarm.

    The thread also fires the old callbacks: on_sunrise(minutes) when the
    next alarm is `sunrise_minutes` away and on_alarm() when it is due.
    They go away when MorningRoutine owns the timing.
    """

    THREAD_JOIN_TIMEOUT = 2  # seconds

    def __init__(
        self,
        p_callback_alarm: Callable[[], None],
        p_callback_sr: Callable[[int], None],
        token_file: Path = Config.google_token_file,
        update_interval: float = Config.calendar_update_interval,
        config: Config | None = None,
        now: Callable[[], datetime.datetime] = _local_now,
    ):
        cfg = config or Config()
        self._token_file = token_file
        self.UPDATE_INTERVAL = update_interval
        self._alarm_title = cfg.alarm_title.casefold()
        self._refetch_near = datetime.timedelta(seconds=cfg.calendar_refetch_near)
        self._refetch_far = datetime.timedelta(seconds=cfg.calendar_refetch_far)
        self._refetch_near_from: datetime.time = cfg.calendar_refetch_near_from
        self._alarm_check_at: datetime.time = cfg.alarm_check_at
        self._sunrise = datetime.timedelta(minutes=cfg.sunrise_minutes)
        self._late_grace = datetime.timedelta(minutes=cfg.late_start_grace_minutes)
        self._now = now
        # If modifying these scopes, delete the file token.json.
        self.SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
        self.creds = None
        # Replaced as a whole by fetch(), so readers on other threads
        # always see one consistent download.
        self._events: List[CEvent] = []
        self._alarms: List[datetime.datetime] = []
        self._fetch_lock = threading.Lock()
        self._next_fetch: datetime.datetime | None = None
        self._checked_tomorrow: datetime.date | None = None
        self._sunrise_fired: datetime.datetime | None = None
        self._alarm_fired: datetime.datetime | None = None
        self.on_alarm = p_callback_alarm
        self.on_sunrise = p_callback_sr
        self._stop_event = threading.Event()
        self.cal_updater_thread: threading.Thread | None = None

    def start(self) -> None:
        """Starts the thread that refetches the events and fires
        the sunrise and alarm callbacks."""
        if self.cal_updater_thread is not None:
            return
        self._stop_event.clear()
        self.cal_updater_thread = threading.Thread(
            target=self.__cal_update, name="calendar", daemon=True
        )
        self.cal_updater_thread.start()

    def stop(self) -> None:
        """Stop Calender from updating itself. Safe to call more than once,
        and before start()."""
        self._stop_event.set()
        if self.cal_updater_thread is None:
            return
        if self.cal_updater_thread.is_alive():
            self.cal_updater_thread.join(self.THREAD_JOIN_TIMEOUT)
        self.cal_updater_thread = None

    def todays_events(self) -> List[CEvent]:
        """Today's events from the last fetch, alarms left out."""
        today = self._now().date()
        return [e for e in self._events if e.start.date() == today]

    def next_alarm(
        self, not_before: datetime.datetime | None = None
    ) -> datetime.datetime | None:
        """Start of the first alarm at or after not_before (default now),
        from the last fetch. None if today and tomorrow have none."""
        not_before = not_before or self._now()
        return next((a for a in self._alarms if a >= not_before), None)

    def __cal_update(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._update()
            except Exception:
                logger.exception("Calendar update failed")
            self._stop_event.wait(self.UPDATE_INTERVAL)

    def _update(self) -> None:
        """One round of the thread: refetch if due, then the 21:00 check
        and the old callbacks."""
        now = self._now()
        if self._next_fetch is None or now >= self._next_fetch:
            fetched = self.fetch()
            self._next_fetch = self._next_fetch_time(now)
            if fetched:
                self._check_tomorrow(now)
        self._fire_callbacks(now)

    def _next_fetch_time(self, now: datetime.datetime) -> datetime.datetime:
        """15 min from 04:00 until today's alarm has rung, 2 h otherwise.
        Never later than the next 04:00 or 21:00, so both start fresh."""
        rung_today = any(
            a.date() == now.date() and a <= now for a in self._alarms
        )
        near = now.time() >= self._refetch_near_from and not rung_today
        due = now + (self._refetch_near if near else self._refetch_far)
        return min(
            due,
            _next_at(now, self._refetch_near_from),
            _next_at(now, self._alarm_check_at),
        )

    def _check_tomorrow(self, now: datetime.datetime) -> None:
        """Once a day, from 21:00: log tomorrow's alarm or warn there is none."""
        tomorrow = now.date() + datetime.timedelta(days=1)
        if now.time() < self._alarm_check_at or self._checked_tomorrow == tomorrow:
            return
        self._checked_tomorrow = tomorrow
        alarm = next((a for a in self._alarms if a.date() == tomorrow), None)
        if alarm is None:
            logger.warning("No wake-up alarm in the calendar for tomorrow %s", tomorrow)
        else:
            logger.info("Wake-up alarm tomorrow at %s", alarm.strftime("%H:%M"))

    def _fire_callbacks(self, now: datetime.datetime) -> None:
        # An alarm that is a little overdue (slow refetch, daemon restart)
        # still rings.
        alarm = self.next_alarm(now - self._late_grace)
        if alarm is None:
            return
        if self._sunrise_fired != alarm and alarm - self._sunrise <= now < alarm:
            self._sunrise_fired = alarm
            self.on_sunrise(int(self._sunrise.total_seconds() // 60))
        if self._alarm_fired != alarm and now >= alarm:
            self._alarm_fired = alarm
            self.on_alarm()

    def fetch(self) -> bool:
        """Downloads today's and tomorrow's events. Blocking. On failure
        the events from the last fetch are kept and False is returned."""
        with self._fetch_lock:
            if not self.refresh_tokens():
                return False
            window_start = _local_midnight(self._now().date())
            window_end = window_start + datetime.timedelta(days=2)
            window_end = _local_midnight(window_end.date())  # DST-safe
            try:
                items = self._list_events(window_start, window_end)
            except HttpError as error:
                logger.error("Fetching calendar events failed: %s", error)
                return False
            events = [
                e
                for e in map(self._parse_event, items)
                if e is not None and e.start >= window_start
            ]
            self._events = [e for e in events if not e.is_alarm]
            self._alarms = sorted(e.start for e in events if e.is_alarm)
            logger.info(
                "downloaded %d calendar events, alarms: %s",
                len(self._events),
                [a.strftime("%a %H:%M") for a in self._alarms],
            )
            return True

    def _list_events(
        self, window_start: datetime.datetime, window_end: datetime.datetime
    ) -> List[dict]:
        """Every event that overlaps the window, all pages. Google filters
        timeMin on the END time, so an event that started long ago but has
        not ended (a long or wrongly set end time) is listed too, first."""
        service = build("calendar", "v3", credentials=self.creds)
        items: List[dict] = []
        page_token = None
        for _ in range(MAX_PAGES):
            page = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=window_start.isoformat(),
                    timeMax=window_end.isoformat(),
                    maxResults=PAGE_SIZE,
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                )
                .execute()
            )
            items += page.get("items", [])
            page_token = page.get("nextPageToken")
            if page_token is None:
                return items
        logger.warning("Calendar has more than %d events; rest ignored", len(items))
        return items

    def _parse_event(self, event: dict) -> CEvent | None:
        start, has_time = Calender.parse_event_date(event["start"].get("dateTime"))
        if start is None:
            start, has_time = Calender.parse_event_date(event["start"].get("date"))
        if start is None:
            return None
        summary = event.get("summary", "")
        return CEvent(
            start=start,
            summary=summary,
            descr=event.get("description") or "",
            location=event.get("location"),
            # An all-day event cannot wake anyone.
            is_alarm=has_time and summary.strip().casefold() == self._alarm_title,
            has_time=has_time,
        )

    def refresh_tokens(self) -> bool:
        """Loads the Google tokens from token.json and refreshes them if
        they have expired. Returns False if there are no usable tokens.

        A new token.json needs a browser login (the OAuth flow with the
        client_secret_*.json file in daemon/), which the daemon cannot do,
        so the calendar is skipped until one is created by hand.
        """
        self.creds = None
        if self._token_file.exists():
            self.creds = Credentials.from_authorized_user_file(
                str(self._token_file), self.SCOPES
            )
        if self.creds and self.creds.valid:
            return True
        if self.creds and self.creds.expired and self.creds.refresh_token:
            logger.info("refreshing Google credential tokens")
            try:
                self.creds.refresh(Request())
            except RefreshError as e:
                logger.error(
                    "Google token refresh failed (%s). Calendar skipped until "
                    "a new %s is created with a browser login",
                    e,
                    self._token_file,
                )
                return False
            # Save the credentials for the next run
            with open(self._token_file, "w") as token:
                token.write(self.creds.to_json())
            return True
        logger.error(
            "No usable Google token in %s. Calendar skipped until a new one "
            "is created with a browser login",
            self._token_file,
        )
        return False

    @staticmethod
    def parse_event_date(date_as_str: str) -> tuple[datetime.datetime, bool]:
        """Returns (start, has_time). All-day dates become local midnight,
        so every start is timezone-aware and comparable."""
        try:
            if date_as_str is None:
                return (None, False)
            if len(date_as_str) == 10:  # yyyy-mm-dd
                day = datetime.date.fromisoformat(date_as_str)
                return (_local_midnight(day), False)
            start = datetime.datetime.fromisoformat(date_as_str)
            return (start.astimezone(TIMEZONE), True)
        except Exception as e:
            logger.error(e)
            return (None, False)
