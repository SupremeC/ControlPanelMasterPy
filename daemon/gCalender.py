import datetime
import threading
import time
import logging
import os.path
from typing import Callable, List
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pytz

if __name__ == "__main__":
    from cevent import CEvent
else:
    from daemon.cevent import CEvent


logger = logging.getLogger("daemon.gCalender")


class Calender:
    def __init__(
        self, p_callback_alarm: Callable[[], None], p_callback_sr: Callable[[int], None]
    ):
        # If modifying these scopes, delete the file token.json.
        self.SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
        self.creds = None
        self.alarmName: str = "wakeUpAlarm"
        self.time_to_update_utc: datetime.datetime = None
        self.events: List[CEvent] = []
        self.alarm: CEvent = None
        self.on_alarm = p_callback_alarm
        self.on_sunrise = p_callback_sr
        self.cal_auto_update: bool = True
        self.cal_updater_thread = threading.Thread(
            target=self.__cal_update,
            kwargs=dict(),
        )
        self.cal_updater_thread.start()

    def stop(self) -> None:
        """Stop Calender from updating itself"""
        self.cal_auto_update = False

    def upcoming_events_today(self) -> List[CEvent]:
        if self.events is None:
            return []
        return [
            obj
            for obj in self.events
            if obj.start
            > (
                datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(hours=1)
            )
        ]

    def __cal_update(self) -> None:
        """Downloads todays calender events/alarm"""
        while self.cal_auto_update:
            swedish_timezone = pytz.timezone("Europe/Stockholm")
            try:
                current_time = datetime.datetime.now(swedish_timezone)
                current_time_utc = datetime.datetime.now(datetime.timezone.utc)
                if (
                    self.time_to_update_utc is None
                    or current_time_utc >= self.time_to_update_utc
                ):
                    self.events = self.get_todays_events()
                    self.time_to_update_utc = self._next_update_utc()

                if (
                    self.alarm is not None
                    and self.alarm.has_time
                    and not self.alarm.reminder_done
                ):
                    if current_time > self.alarm.start - datetime.timedelta(
                        minutes=self.alarm.reminder
                    ):
                        self.on_sunrise(self.alarm.reminder)
                if self.alarm is not None and self.alarm.has_time:
                    if current_time > self.alarm.start:
                        self.alarm = None
                        self.on_alarm()
            except Exception as e:
                logger.error(e)
            time.sleep(60)

    def get_todays_events(self) -> List[CEvent]:
        self.refresh_tokens()
        try:
            # Set the timezone to Stockholm, Sweden
            swedish_timezone = pytz.timezone("Europe/Stockholm")
            service = build("calendar", "v3", credentials=self.creds)

            # Call the Calendar API
            # now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            logger.debug("Getting todays first 10 events")
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=Calender.start_of_today_utc(),
                    timeMax=Calender.end_of_today_utc(),
                    maxResults=10,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])

            if not events:
                logger.debug("No upcoming events found for today.")
                return None

            self.alarm = None
            items = list()
            for event in events:
                start = Calender.parse_event_date(event["start"].get("dateTime"))
                if start is None or start[0] is None:
                    start = Calender.parse_event_date(event["start"].get("date"))
                rminutes = 16
                s = event["summary"]
                descr = (
                    "" if event.get("description") is None else event.get("description")
                )
                loc = event.get("location")
                alarm = True if event["summary"] == self.alarmName else False
                if event["reminders"] is not None:
                    if (event["reminders"].get("overrides")) is not None:
                        for re in event["reminders"].get("overrides"):
                            minutes = int(re.get("minutes"))
                            rminutes = max(rminutes, minutes)
                e = CEvent(
                    start=start[0],
                    reminder=rminutes,
                    summary=s,
                    descr=descr,
                    location=loc,
                    is_alarm=alarm,
                    has_time=start[1],
                    reminder_done=False,
                )
                if not e.is_alarm:
                    items.append(e)
                if (
                    e.is_alarm
                    and e.has_time
                    and datetime.datetime.now(swedish_timezone) < e.start
                ):
                    self.alarm = e
            self.events = items
            print(f"downloaded {len(items)} calender events")
            return items
        except HttpError as error:
            logger.error(f"An error occurred: {error}")

    def refresh_tokens(self) -> None:
        self.creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        # print("Current working directory:", os.getcwd())
        folder = "daemon/"
        if __name__ == "__main__":
            folder = ""

        if os.path.exists("daemon/token.json"):
            self.creds = Credentials.from_authorized_user_file(
                folder + "token.json", self.SCOPES
            )
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            logger.warning("Google Calender credentials(tokens) expired or not valid")
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    folder
                    + "/client_secret_776060522090-prfipc44cc0ef87rr78rg5773an22uan.apps.googleusercontent.com.json",
                    self.SCOPES,
                )
                self.creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(folder + "token.json", "w") as token:
                token.write(self.creds.to_json())

    def parse_event_date(date_as_str: str) -> tuple[datetime.datetime, bool]:
        try:
            if date_as_str is None:
                return (None, False)
            if len(date_as_str) == 10:  # yyyy-mm-dd
                date = datetime.datetime.strptime(date_as_str, "%Y-%m-%d")
                return (date, False)
            else:
                date = datetime.datetime.fromisoformat(date_as_str)
                return (date, True)
        except Exception as e:
            logger.error(e)
            return (None, False)

    def start_of_today_utc():
        now = datetime.datetime.now(datetime.timezone.utc)
        # Set the time to 00:00:00 (start of the day) while keeping the date
        start_of_today = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        return start_of_today

    def end_of_today_utc() -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        # Calculate the start of tomorrow in UTC
        start_of_tomorrow = (now + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Subtract 1 microsecond to get the end of today (23:59:59.999999)
        end_of_today = start_of_tomorrow - datetime.timedelta(microseconds=1)
        return end_of_today.isoformat()

    def _next_update_utc(self, h: int = 2) -> datetime.datetime:
        """Returns datetime of the next time to update"""
        return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=h
        )
        time_for_update = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=5, minute=0, second=0, microsecond=0
        )
        # Ensure the first call happens tomorrow if it has passed today
        if datetime.datetime.now(datetime.timezone.utc) > time_for_update:
            time_for_update += datetime.timedelta(days=1)
        return time_for_update


if __name__ == "__main__":
    cal = Calender(None, None)
    while True:
        do_alarm = cal.update()
        do_alarm = cal.update()
        do_alarm = cal.update()
        events = cal.events
        print(f"Do_alarm: {do_alarm}")
        print(f"Events ({len(events)}): {events}")
        break
