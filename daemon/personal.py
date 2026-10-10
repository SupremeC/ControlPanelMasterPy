"""Who the panel talks to. Read from daemon/personal.json, which is
gitignored because this repo is public (see personal.example.json):

    {"name": "...", "birthday": "YYYY-MM-DD"}

The age is computed from the birthday, so it never goes stale.
"""

from dataclasses import dataclass
import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger("daemon.personal")

WEEKDAYS = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")
MONTHS = (
    "januari", "februari", "mars", "april", "maj", "juni", "juli",
    "augusti", "september", "oktober", "november", "december",
)


@dataclass(frozen=True)
class Personal:
    name: str = ""
    birthday: datetime.date | None = None

    def age(self, today: datetime.date) -> int | None:
        """Full years on `today`, or None without a birthday."""
        b = self.birthday
        if b is None:
            return None
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))

    def describe(self, today: datetime.date) -> str:
        """'Kim, 13 år' or a neutral phrase when unknown (Swedish)."""
        who = self.name or "ett barn"
        age = self.age(today)
        return f"{who}, {age} år," if age is not None else who

    @staticmethod
    def load(path: Path) -> "Personal":
        """Reads the file. A missing or broken file is logged and gives
        a Personal without name and age, so speech still works."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            birthday = data.get("birthday")
            return Personal(
                name=str(data.get("name", "")).strip(),
                birthday=datetime.date.fromisoformat(birthday) if birthday else None,
            )
        except FileNotFoundError:
            logger.warning("%s missing: speaking without name and age", path)
        except (ValueError, TypeError, AttributeError) as e:
            logger.error("%s is not valid (%s): speaking without name and age", path, e)
        return Personal()


def swedish_date(day: datetime.date) -> str:
    """'måndag 12 oktober'"""
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
