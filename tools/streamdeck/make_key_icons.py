#!/usr/bin/env python
"""Draws the Stream Deck key icons in tools/streamdeck/icons/ (144x144
PNG, the key's @2x size) with the standard library only, like
tools/make_icons.py. On/off pairs share a shape; "on" glows amber (or
the colour given), "off" is grey. The key title (the Swedish label)
is added by the Stream Deck app, so the icons carry no text.

Run from the repo root: python tools/streamdeck/make_key_icons.py
"""

import math
import struct
import sys
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "icons"
SIZE = 144
BG = (0x1A, 0x1A, 0x1D)
GREY = (0x4A, 0x4A, 0x52)
AMBER = (0xF5, 0xA6, 0x23)
GREEN = (0x4C, 0xD9, 0x64)
RED = (0xE5, 0x48, 0x4D)
BLUE = (0x8A, 0xB4, 0xFF)
WHITE = (0xEC, 0xEC, 0xEC)

Point = tuple[float, float]


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], b[1] - a[1])


def in_circle(p: Point, c: Point, r: float) -> bool:
    return dist(p, c) <= r


def in_ring(p: Point, c: Point, r: float, width: float) -> bool:
    d = dist(p, c)
    return r - width <= d <= r


def in_rect(p: Point, x0: float, y0: float, x1: float, y1: float, r: float = 0) -> bool:
    x, y = p
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    if r <= 0:
        return True
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def in_segment(p: Point, a: Point, b: Point, width: float) -> bool:
    """Within width/2 of the line segment a-b."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0 if length2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= width / 2


# Each shape: a function (point, colour) -> colour or None, in a 0-100 space.

def socket(p: Point, col):
    """A round wall socket with two pin holes."""
    if in_ring(p, (50, 50), 36, 6):
        return col
    if in_circle(p, (36, 50), 6) or in_circle(p, (64, 50), 6):
        return col
    return None


def bulb(p: Point, col):
    """A light bulb with a base."""
    if in_circle(p, (50, 42), 24):
        return col
    if in_rect(p, 40, 62, 60, 72, 3) or in_rect(p, 42, 74, 58, 80, 3):
        return col
    return None


def strip(p: Point, col):
    """A LED strip: a bar with five LEDs."""
    if in_rect(p, 10, 40, 90, 60, 8) and not any(in_circle(p, (18 + i * 16, 50), 5) for i in range(5)):
        return col
    return None


def demo(p: Point, col):
    """Four blinking buttons in a grid."""
    for i, c in enumerate(((32, 32), (68, 32), (32, 68), (68, 68))):
        if in_circle(p, c, 13):
            return col if i % 3 == 0 else (col if col != GREY else GREY)
    return None


def leds(p: Point, col):
    """A row of three small buttons with a halo."""
    for c in ((26, 50), (50, 50), (74, 50)):
        if in_circle(p, c, 9):
            return col
        if in_ring(p, c, 13, 2.5):
            return col
    return None


def power(p: Point, col):
    """The power symbol: a broken ring and a bar."""
    if in_ring(p, (50, 54), 30, 8):
        angle = math.degrees(math.atan2(p[1] - 54, p[0] - 50))  # -90 is up
        if not -125 < angle < -55:
            return col
    if in_rect(p, 45, 18, 55, 54, 4):
        return col
    return None


def speaker(p: Point, col):
    """A speaker with two sound arcs."""
    if in_rect(p, 18, 40, 34, 60) or (in_rect(p, 34, 26, 52, 74) and abs(p[1] - 50) <= (p[0] - 30) * 1.0):
        return col
    for r in (16, 26):
        if in_ring(p, (52, 50), r, 5) and p[0] > 55:
            return col
    return None


def stop(p: Point, col):
    """A square."""
    return col if in_rect(p, 30, 30, 70, 70, 6) else None


def lamp_toggle(p: Point, col):
    """A bulb with a two-way arrow under it (the bed lamp toggles)."""
    if in_circle(p, (50, 38), 20):
        return col
    if in_rect(p, 42, 56, 58, 64, 3):
        return col
    if in_segment(p, (28, 80), (72, 80), 6):
        return col
    for tip, back in (((24, 80), (34, 72)), ((24, 80), (34, 88)), ((76, 80), (66, 72)), ((76, 80), (66, 88))):
        if in_segment(p, tip, back, 6):
            return col
    return None


def question(p: Point, col):
    """A question mark: the state is unknown."""
    if in_ring(p, (50, 40), 18, 7):
        angle = math.degrees(math.atan2(p[1] - 40, p[0] - 50))
        if not 60 < angle < 180:
            return col
    if in_rect(p, 46, 50, 54, 66, 3) or in_circle(p, (50, 76), 5):
        return col
    return None


ICONS = {
    "uttag_on": (socket, AMBER),
    "uttag_off": (socket, GREY),
    "bakgrund_on": (bulb, AMBER),
    "bakgrund_off": (bulb, GREY),
    "slinga_on": (strip, AMBER),
    "slinga_off": (strip, GREY),
    "demo_on": (demo, GREEN),
    "demo_off": (demo, GREY),
    "knapplampor_on": (leds, AMBER),
    "knapplampor_off": (leds, GREY),
    "sanglampa": (lamp_toggle, WHITE),
    "slack_allt": (power, RED),
    "ljud": (speaker, BLUE),
    "stopp": (stop, RED),
    "okand": (question, GREY),
}


def pixel(x: int, y: int, shape, col) -> tuple[int, int, int, int]:
    acc = [0, 0, 0]
    for sy in range(3):
        for sx in range(3):
            p = ((x + (sx + 0.5) / 3) * 100 / SIZE, (y + (sy + 0.5) / 3) * 100 / SIZE)
            c = shape(p, col) or BG
            for i in range(3):
                acc[i] += c[i]
    return (acc[0] // 9, acc[1] // 9, acc[2] // 9, 255)


def png(shape, col) -> bytes:
    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        for x in range(SIZE):
            raw.extend(pixel(x, y, shape, col))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for name, (shape, col) in ICONS.items():
        path = OUT / f"{name}.png"
        path.write_bytes(png(shape, col))
        print(f"wrote {path.name} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
