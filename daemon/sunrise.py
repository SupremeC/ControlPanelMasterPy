"""The sunrise light curve. Pure: no I/O, no clock.

frame(progress) gives the LED strips' brightness and colour at a point in
the sunrise, from 0.0 (start) to 1.0 (alarm time). Brightness rises
exponentially, so the first minutes stay very dim the way a real dawn
does. Colour follows `sunrise_colour_stops` (dark red -> orange -> amber)
and reaches the warm white end colour at `sunrise_white_at`; after that
only the brightness changes.
"""

from typing import NamedTuple

from daemon.config import Config

RGBW = tuple[int, int, int, int]


class Frame(NamedTuple):
    brightness: int  # 0-255, WLED segment brightness
    rgbw: RGBW


def frame(progress: float, config: Config | None = None) -> Frame:
    cfg = config or Config()
    p = max(0.0, min(progress, 1.0))
    return Frame(_brightness(p, cfg), _colour(p, cfg))


def _brightness(p: float, cfg: Config) -> int:
    start, end = cfg.sunrise_start_brightness, cfg.sunrise_end_brightness
    return round(start * (end / start) ** p)


def _colour(p: float, cfg: Config) -> RGBW:
    stops = (*cfg.sunrise_colour_stops, (cfg.sunrise_white_at, cfg.sunrise_end_rgbw))
    if p >= stops[-1][0]:
        return tuple(stops[-1][1])
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if p <= p1:
            t = (p - p0) / (p1 - p0)
            return tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    raise AssertionError("unreachable")
