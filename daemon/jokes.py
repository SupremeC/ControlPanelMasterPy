"""Approved wake-up jokes (GH #14). The text model's jokes were mostly
not funny, so the wake line takes a joke from a pool rated by hand
(tools/joke_pool.py makes candidates) and falls back to the model only
when the pool is empty or missing.

`jokes_file` (gitignored) is a JSON list of
    {"id": "j001", "style": "torr", "tags": ["regn"], "text": "...", "weight": 3}
Weight 3 for a joke rated great, 1 for OK. A joke with tags is told only
on a day all its tags fit (weekday, weather), and is then preferred.
`joke_state_file` (gitignored) remembers when each joke was told, so none
comes back within `joke_repeat_days` unless the pool runs out.

Blocking file I/O: run it on the AI lane, like the rest of the speech.
"""

from dataclasses import dataclass
import datetime
import json
import logging
import os
from pathlib import Path
import random

from daemon.personal import WEEKDAYS
from daemon.weather import DayWeather, PrecipKind, Sky

logger = logging.getLogger("daemon.jokes")

TAGGED_BOOST = 3  # a joke made for today's tags is this much likelier
COLD_MAX = 3  # the day's highest temperature at or below this: "kallt"
WARM_MAX = 18  # at or above this: "varmt"
DARK_AFTER = datetime.time(7, 15)  # sunrise later than this: "mörkt"
_SNOWY = {PrecipKind.SNOW, PrecipKind.WET_SNOW, PrecipKind.SLEET, PrecipKind.GRAUPEL}
_SUNNY = {Sky.CLEAR, Sky.NEARLY_CLEAR}


@dataclass(frozen=True)
class Joke:
    id: str
    style: str
    tags: tuple[str, ...]
    text: str
    weight: int = 1


def day_tags(day: datetime.date, weather: DayWeather | None = None) -> set[str]:
    """The tags that fit `day`: its weekday, plus weather tags."""
    tags = {WEEKDAYS[day.weekday()]}
    if weather is None:
        return tags
    kinds = {p.precip.kind for p in weather.parts if p.precip and p.precip.likely}
    if kinds & _SNOWY:
        tags.add("snö")
    if kinds - _SNOWY:
        tags.add("regn")
    if weather.temp_max <= COLD_MAX:
        tags.add("kallt")
    if weather.temp_max >= WARM_MAX:
        tags.add("varmt")
    skies = [p.sky for p in weather.parts if p.sky is not None]
    if skies and not kinds and sum(s in _SUNNY for s in skies) * 2 > len(skies):
        tags.add("sol")
    if weather.sunrise is not None and weather.sunrise.time() > DARK_AFTER:
        tags.add("mörkt")
    return tags


def load(path: Path) -> list[Joke]:
    """The approved jokes; [] when the file is missing or broken."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [
            Joke(
                id=str(j["id"]),
                style=str(j.get("style", "")),
                tags=tuple(j.get("tags", ())),
                text=" ".join(str(j["text"]).split()),
                weight=max(1, int(j.get("weight", 1))),
            )
            for j in data
            if str(j.get("text", "")).strip()
        ]
    except FileNotFoundError:
        logger.info("%s missing: the text model writes the joke", path)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        logger.error("%s is not valid (%s): the text model writes the joke", path, e)
    return []


def pick(
    jokes: list[Joke],
    told: dict[str, str],
    day: datetime.date,
    tags: set[str],
    repeat_days: int,
    rng: random.Random | None = None,
) -> Joke | None:
    """A joke for `day`, weighted, never one whose tags do not fit. Jokes
    told within repeat_days are left out; if that leaves none, the ones
    told longest ago are used. `told` maps id -> ISO date."""
    rng = rng or random.Random()
    fitting = [j for j in jokes if set(j.tags) <= tags]
    if not fitting:
        return None
    cutoff = day - datetime.timedelta(days=repeat_days)

    def last(j: Joke) -> datetime.date:
        try:
            return datetime.date.fromisoformat(told.get(j.id, ""))
        except ValueError:
            return datetime.date.min

    fresh = [j for j in fitting if last(j) <= cutoff]
    if not fresh:
        oldest = min(last(j) for j in fitting)
        fresh = [j for j in fitting if last(j) == oldest]
    weights = [j.weight * (TAGGED_BOOST if j.tags else 1) for j in fresh]
    return rng.choices(fresh, weights=weights)[0]


class JokeBox:
    """The pool and its memory of what was told when."""

    def __init__(self, jokes_file: Path, state_file: Path, repeat_days: int):
        self._jokes_file = Path(jokes_file)
        self._state_file = Path(state_file)
        self._repeat_days = repeat_days

    def next(self, day: datetime.date, weather: DayWeather | None = None) -> Joke | None:
        """Picks today's joke and records it as told. None without a pool."""
        jokes = load(self._jokes_file)
        if not jokes:
            return None
        told = self._told()
        joke = pick(jokes, told, day, day_tags(day, weather), self._repeat_days)
        if joke is not None:
            told[joke.id] = day.isoformat()
            self._save(told)
            logger.info("Joke %s (%s, tags %s)", joke.id, joke.style, ",".join(joke.tags) or "-")
        return joke

    def _told(self) -> dict[str, str]:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.get("told", {}).items()}
        except FileNotFoundError:
            return {}
        except (ValueError, AttributeError) as e:
            logger.error("%s is not valid (%s): starting afresh", self._state_file, e)
            return {}

    def _save(self, told: dict[str, str]) -> None:
        tmp = self._state_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"told": told}, indent=1), encoding="utf-8")
            os.replace(tmp, self._state_file)
        except OSError as e:
            logger.error("Could not save %s: %s", self._state_file, e)
