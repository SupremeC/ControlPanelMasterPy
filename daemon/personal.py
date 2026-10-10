"""Who the panel talks to. Read from daemon/personal.json, which is
gitignored because this repo is public (see personal.example.json):

    {"name": "...", "birthday": "YYYY-MM-DD",
     "location": {"lat": 59.33, "lon": 18.07},
     "bring": {"weekdays": {"tisdag": ["gympapåsen"]},
               "keywords": {"scout": ["scoutskjortan"]}}}

The age is computed from the birthday, so it never goes stale. The
location (home, for the weather) and the bring rules are optional. Bring
rules say what to take along: weekday rules on school days, keyword rules
when one of today's events has the keyword in its title (any case).
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
    location: tuple[float, float] | None = None
    """(lat, lon) of home."""
    bring_weekdays: tuple[tuple[int, tuple[str, ...]], ...] = ()
    """(weekday, things): Monday is 0, as in date.weekday()."""
    bring_keywords: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """(casefolded keyword, things)."""

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

    def things_to_bring(
        self, day: datetime.date, titles: list[str], school_day: bool
    ) -> list[str]:
        """What to take along today, each thing once, in rule order."""
        things: list[str] = []
        if school_day:
            for weekday, items in self.bring_weekdays:
                if weekday == day.weekday():
                    things += items
        folded = [t.casefold() for t in titles]
        for keyword, items in self.bring_keywords:
            if any(keyword in t for t in folded):
                things += items
        return list(dict.fromkeys(things))

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
                location=_location(data.get("location"), path),
                **_bring(data.get("bring"), path),
            )
        except FileNotFoundError:
            logger.warning("%s missing: speaking without name and age", path)
        except (ValueError, TypeError, AttributeError) as e:
            logger.error("%s is not valid (%s): speaking without name and age", path, e)
        return Personal()


def _location(value, path: Path) -> tuple[float, float] | None:
    """A broken location is logged and ignored; name and age still work."""
    if value is None:
        return None
    try:
        lat, lon = float(value["lat"]), float(value["lon"])
    except (KeyError, TypeError, ValueError) as e:
        logger.error("%s: location is not valid (%r): ignored", path, e)
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        logger.error("%s: location %s, %s is out of range: ignored", path, lat, lon)
        return None
    return lat, lon


def _bring(value, path: Path) -> dict:
    """Bring rules as Personal fields. Broken rules are logged and left
    out; the rest of the file still works."""
    if value is None:
        return {}
    weekdays, keywords = [], []
    try:
        for name, items in (value.get("weekdays") or {}).items():
            day = name.strip().casefold()
            if day not in WEEKDAYS:
                logger.error("%s: bring: unknown weekday %r: ignored", path, name)
                continue
            weekdays.append((WEEKDAYS.index(day), _things(items)))
        for keyword, items in (value.get("keywords") or {}).items():
            keywords.append((keyword.strip().casefold(), _things(items)))
    except (AttributeError, TypeError) as e:
        logger.error("%s: bring is not valid (%s): ignored", path, e)
        return {}
    return {"bring_weekdays": tuple(weekdays), "bring_keywords": tuple(keywords)}


def _things(items) -> tuple[str, ...]:
    if isinstance(items, str):
        items = [items]
    return tuple(str(i).strip() for i in items if str(i).strip())


def swedish_date(day: datetime.date) -> str:
    """'måndag 12 oktober'"""
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
