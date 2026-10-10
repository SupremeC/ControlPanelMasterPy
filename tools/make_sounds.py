#!/usr/bin/env python
"""Synthesises the morning routine's sounds as soft marimba-like tones:

    alarm_soft.wav   8 s pentatonic pattern that loops without a seam
    chime_off.wav    two falling notes: the alarm is off
    chime_speak.wav  two rising notes: speech follows

Run on the Pi from the repo root. Writes to daemon/systemsounds/ (not in
git). Existing files are kept unless --force, so sounds you replaced by
hand survive. The daemon loads system sounds at start: restart it after.

    bin/python tools/make_sounds.py [--force] [--out DIR]
"""

import argparse
from pathlib import Path
import sys
import wave

import numpy as np

RATE = 48000  # matches mixer.init in AudioCtrl
C5, D5, E5, G5, A5, C6 = 523.25, 587.33, 659.25, 783.99, 880.0, 1046.5


def note(freq: float, seconds: float, decay: float) -> np.ndarray:
    """A struck bar: the fundamental plus a quieter 4th partial that
    dies away faster, a 5 ms attack and an exponential decay."""
    t = np.arange(int(RATE * seconds)) / RATE
    attack = np.minimum(1.0, t / 0.005)
    body = np.sin(2 * np.pi * freq * t) * np.exp(-t / decay)
    shimmer = 0.25 * np.sin(2 * np.pi * 4 * freq * t) * np.exp(-t / (decay / 4))
    return attack * (body + shimmer)


def mix(notes: list[tuple[float, float]], length: float, decay: float,
        loop: bool = False) -> np.ndarray:
    """Places (start, freq) notes on a track of `length` seconds. With
    loop, each note's tail past the end wraps to the start."""
    tail = decay * 6
    track = np.zeros(int(RATE * (length + tail)))
    for start, freq in notes:
        n = note(freq, tail, decay)
        i = int(RATE * start)
        track[i:i + len(n)] += n
    end = int(RATE * length)
    if loop:
        overflow = track[end:]
        track[: len(overflow)] += overflow
        return track[:end]
    return track


def to_wav(path: Path, samples: np.ndarray, peak: float) -> None:
    samples = samples / np.max(np.abs(samples)) * peak
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((samples * 32767).astype("<i2").tobytes())


def sounds() -> dict[str, tuple[np.ndarray, float]]:
    step = 0.4
    phrase1 = [C5, E5, G5, A5, G5, E5]
    phrase2 = [D5, G5, A5, C6, A5, G5]
    alarm = [(i * step, f) for i, f in enumerate(phrase1)]
    alarm += [(4.0 + i * step, f) for i, f in enumerate(phrase2)]
    return {
        "alarm_soft": (mix(alarm, 8.0, decay=0.6, loop=True), 0.8),
        "chime_off": (mix([(0.0, G5), (0.2, C5)], 0.2, decay=0.4), 0.5),
        "chime_speak": (mix([(0.0, E5), (0.15, A5)], 0.15, decay=0.35), 0.5),
    }


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=root / "daemon" / "systemsounds")
    parser.add_argument("--force", action="store_true", help="overwrite")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for name, (samples, peak) in sounds().items():
        path = args.out / f"{name}.wav"
        if path.exists() and not args.force:
            print(f"kept     {path} (use --force to overwrite)")
            continue
        to_wav(path, samples, peak)
        print(f"wrote    {path} ({len(samples) / RATE:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
