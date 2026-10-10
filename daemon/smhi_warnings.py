"""SMHI impact-based weather warnings (IBWW). No authentication.

Docs: https://opendata.smhi.se/warnings/ (rendered with JavaScript).

warning.json is a list of warnings, each with one or more warning areas.
An area has its own level (MESSAGE, YELLOW, ORANGE, RED), event
description, approximate start and end (UTC; the end may be missing) and a
GeoJSON polygon or multipolygon in lon/lat. A warning concerns the
listener when the home point lies inside an area's polygon.

This module fetches, parses and filters. Wording is elsewhere.
"""

from dataclasses import dataclass
import datetime
from enum import IntEnum
import logging

import requests

from daemon.smhi import SmhiError

logger = logging.getLogger("daemon.smhi_warnings")

WARNINGS_URL = (
    "https://opendata-download-warnings.smhi.se/ibww/api/version/1/warning.json"
)

Ring = tuple[tuple[float, float], ...]  # (lon, lat) points, GeoJSON order
Polygon = tuple[Ring, ...]  # outer ring, then holes


class Level(IntEnum):
    MESSAGE = 0  # e.g. risk of water shortage; not a warning
    YELLOW = 1
    ORANGE = 2
    RED = 3


@dataclass(frozen=True)
class WeatherWarning:
    level: Level
    event: str
    """What, in Swedish, e.g. 'Mycket kraftig vind'."""
    area: str
    """Where, in Swedish, e.g. 'Stockholms län'."""
    start: datetime.datetime | None
    """UTC; None = already in force."""
    end: datetime.datetime | None
    """UTC; None = until further notice."""
    certain: bool
    """False when SMHI marks the warning as less probable than normal."""
    text: str
    """SMHI's short description of the incident (Swedish), or ''."""
    polygons: tuple[Polygon, ...]

    def covers(self, lat: float, lon: float) -> bool:
        return any(_in_polygon(lon, lat, p) for p in self.polygons)

    def overlaps(self, start: datetime.datetime, end: datetime.datetime) -> bool:
        return (self.start is None or self.start < end) and (
            self.end is None or self.end > start
        )


def fetch_warnings_json(timeout: float) -> list:
    """The raw warning list. Blocking; raises SmhiError."""
    try:
        response = requests.get(WARNINGS_URL, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise SmhiError(f"SMHI warnings {WARNINGS_URL}: {e}") from e
    except ValueError as e:
        raise SmhiError(f"SMHI warnings {WARNINGS_URL} is not JSON: {e}") from e


def parse_warnings(raw: list) -> list[WeatherWarning]:
    """One WeatherWarning per warning area. Pure. Raises SmhiError when
    the layout is not what this code knows; an area with an unknown level
    or geometry is logged and skipped."""
    if not isinstance(raw, list):
        raise SmhiError(f"SMHI warnings format has changed: {type(raw).__name__}")
    result = []
    try:
        for warning in raw:
            for area in warning["warningAreas"]:
                parsed = _area(area, warning)
                if parsed:
                    result.append(parsed)
    except (KeyError, TypeError, ValueError) as e:
        raise SmhiError(f"SMHI warnings format has changed: {e!r}") from e
    return result


def relevant(
    warnings: list[WeatherWarning],
    lat: float,
    lon: float,
    start: datetime.datetime,
    end: datetime.datetime,
    min_level: Level = Level.YELLOW,
) -> list[WeatherWarning]:
    """Warnings at the point during start..end, most severe first."""
    found = [
        w
        for w in warnings
        if w.level >= min_level and w.overlaps(start, end) and w.covers(lat, lon)
    ]
    far_future = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
    return sorted(found, key=lambda w: (-w.level, w.start or far_future))


def _area(area: dict, warning: dict) -> WeatherWarning | None:
    code = area["warningLevel"]["code"]
    try:
        level = Level[code]
    except KeyError:
        logger.warning("Unknown SMHI warning level %s: skipped", code)
        return None
    geometry = area["area"]["geometry"]
    if geometry["type"] == "Polygon":
        polygons = (_polygon(geometry["coordinates"]),)
    elif geometry["type"] == "MultiPolygon":
        polygons = tuple(_polygon(p) for p in geometry["coordinates"])
    else:
        logger.warning("Unknown SMHI warning geometry %s: skipped", geometry["type"])
        return None
    return WeatherWarning(
        level=level,
        event=area["eventDescription"]["sv"],
        area=area["areaName"]["sv"],
        start=_time(area.get("approximateStart")),
        end=_time(area.get("approximateEnd")),
        certain=area.get("normalProbability", True),
        text=_incident(area.get("descriptions") or warning.get("descriptions") or []),
        polygons=polygons,
    )


def _polygon(rings: list) -> Polygon:
    return tuple(tuple((float(p[0]), float(p[1])) for p in ring) for ring in rings)


def _incident(descriptions: list) -> str:
    for d in descriptions:
        if d["title"]["code"] == "INCIDENT":
            return d["text"]["sv"].strip()
    return ""


def _time(text: str | None) -> datetime.datetime | None:
    if not text:
        return None
    t = datetime.datetime.fromisoformat(text)
    if t.tzinfo is None:
        raise ValueError(f"time without zone: {text}")
    return t.astimezone(datetime.timezone.utc)


def _in_polygon(x: float, y: float, polygon: Polygon) -> bool:
    outer, *holes = polygon
    return _in_ring(x, y, outer) and not any(_in_ring(x, y, h) for h in holes)


def _in_ring(x: float, y: float, ring: Ring) -> bool:
    """Ray casting (even-odd rule). Fine for county-sized areas at
    Stockholm's latitude; points exactly on an edge may go either way."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside
