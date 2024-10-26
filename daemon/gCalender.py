import datetime
import time
import logging
import os.path
from typing import List
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from cevent import CEvent


logger = logging.getLogger("daemon.gCalender")


class Calender:
    def __init__(self):
        # If modifying these scopes, delete the file token.json.
        self.SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
        self.creds = None
        self.alarmName: str = "wakeUpAlarm"
        self.time_to_update: datetime.datetime = None
        self.events: List[CEvent] = []
        self.alarm: CEvent = None

    def update(self, force: bool = False) -> bool:
        """Downloads todays calender events/alarm once per day at 05:00 aclock.
        Call this function reguarly.
        You can force a fresh download of events by passing force=True.

        Parameters
        ----------
        force : [bool]
            Force refresh of todays events from Google Calender

        Returns
        -------
        bool
            Is it time to start the wakeUp alarm?
        """
        try:
            current_time = datetime.datetime.now(datetime.timezone.utc)
            if (
                force
                or self.time_to_update is None
                or current_time >= self.time_to_update
            ):
                self.get_todays_events()
                self.time_to_update = self._next_update()

            if self.alarm is None:
                return False
            if self.alarm.start is None:
                self.alarm = None
                return False
            if current_time > self.alarm.start:
                diff = current_time - self.alarm.start
                self.alarm = None
                if diff.total_seconds() < 60:
                    return True
        except Exception as e:
            logger.error(e)
        return False

    def get_todays_events(self) -> List[CEvent]:
        self.refresh_tokens()
        try:
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
                logger.info("No upcoming events found for today.")
                return

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
                )
                if not e.is_alarm:
                    items.append(e)
                if e.is_alarm:
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
        print("Current working directory:", os.getcwd())
        if os.path.exists("daemon/token.json"):
            self.creds = Credentials.from_authorized_user_file(
                "daemon/token.json", self.SCOPES
            )
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            logger.warning("Google Calender credentials(tokens) expired or not valid")
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "daemon/client_secret_776060522090-prfipc44cc0ef87rr78rg5773an22uan.apps.googleusercontent.com.json",
                    self.SCOPES,
                )
                self.creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open("token.json", "w") as token:
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

    def _next_update(self) -> datetime.datetime:
        """Returns datetime of the next time the hour is 05:00"""
        time_for_update = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=5, minute=0, second=0, microsecond=0
        )
        # Ensure the first call happens tomorrow if it has passed today
        if datetime.datetime.now(datetime.timezone.utc) > time_for_update:
            time_for_update += datetime.timedelta(days=1)
        return time_for_update


if __name__ == "__main__":
    cal = Calender()
    while True:
        do_alarm = cal.update()
        do_alarm = cal.update()
        do_alarm = cal.update()
        events = cal.events
        print(f"Do_alarm: {do_alarm}")
        print(f"Events ({len(events)}): {events}")
        time.sleep(4)
        break
