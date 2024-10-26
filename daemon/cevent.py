from dataclasses import dataclass
from datetime import datetime, time


@dataclass
class CEvent:
    start: datetime
    reminder: int
    summary: str
    descr: str
    location: str
    is_alarm: bool
    has_time: bool
    """True == Full day event"""

    def __str__(self) -> str:
        msg = f"{self.summary} {self.descr} "
        msg += "at " + datetime.strftime(self.start,"%H:%M") if self.has_time else ""
        if self.location != None and self.location != "":
            msg += f" location={self.location}"
        return msg

    def __repr__(self) -> str:
        msg = f"{self.summary} {self.descr} "
        msg += "at " + datetime.strftime(self.start,"%H:%M") if self.has_time else ""
        if self.location != None and self.location != "":
            msg += f" location={self.location}"
        return msg
