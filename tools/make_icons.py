#!/usr/bin/env python
"""Writes the page's home-screen icons, daemon/web/icon-192.png and
icon-512.png: the same four panel buttons as daemon/web/icon.svg,
drawn with the standard library only (no image library on the Pi).

Run from the repo root: python tools/make_icons.py
"""

import struct
import sys
import zlib
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "daemon" / "web"
BACKGROUND = (0x1A, 0x1A, 0x1D)
EDGE = (0x2A, 0x2A, 0x2F)
BUTTONS = {  # centre (in 64ths), colour
    (20, 20): (0xF5, 0xA6, 0x23),
    (44, 20): (0x4C, 0xD9, 0x64),
    (20, 44): (0x3A, 0x3A, 0x40),
    (44, 44): (0xE5, 0x48, 0x4D),
}


def rounded_rect_inside(x: float, y: float, size: float, radius: float) -> bool:
    """Is (x, y) inside the square [0, size] with rounded corners?"""
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def pixel(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    """RGBA of one pixel, supersampled 3x3 for smooth edges."""
    acc = [0, 0, 0, 0]
    for sy in range(3):
        for sx in range(3):
            px = (x + (sx + 0.5) / 3) * 64 / size
            py = (y + (sy + 0.5) / 3) * 64 / size
            colour = None
            if rounded_rect_inside(px, py, 64, 14):
                colour = BACKGROUND
                in_outer = rounded_rect_inside(px - 4, py - 4, 56, 11)
                in_inner = rounded_rect_inside(px - 6, py - 6, 52, 9)
                if in_outer and not in_inner:
                    colour = EDGE  # the thin frame
                for (bx, by), button in BUTTONS.items():
                    if (px - bx) ** 2 + (py - by) ** 2 <= 64:  # radius 8
                        colour = button
            if colour is not None:
                for i in range(3):
                    acc[i] += colour[i]
                acc[3] += 255
    return tuple(v // 9 for v in acc)


def png(size: int) -> bytes:
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        for x in range(size):
            raw.extend(pixel(x, y, size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    for size in (192, 512):
        path = WEB_DIR / f"icon-{size}.png"
        path.write_bytes(png(size))
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
