"""Draws the plugin's static images (the manifest needs PNG files): the
Marketplace icon, the category icon, one icon per action and the key
placeholder. Everything the keys show at runtime is SVG from src/icons.ts.

    python make_images.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "com.supremec.panelen.sdPlugin" / "imgs"
AMBER = (255, 179, 71, 255)
DARK = (21, 22, 26, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


def save(name: str, draw_fn, size: int) -> None:
    """name.png at `size` and name@2x.png at twice that, drawn at 4x and shrunk."""
    for suffix, px in (("", size), ("@2x", size * 2)):
        scale = 4
        img = Image.new("RGBA", (px * scale, px * scale), CLEAR)
        draw_fn(ImageDraw.Draw(img), px * scale)
        img = img.resize((px, px), Image.LANCZOS)
        img.save(OUT / f"{name}{suffix}.png")


def rounded(d: ImageDraw.ImageDraw, s: int, fill, radius=0.16) -> None:
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * radius), fill=fill)


def plugin_icon(d: ImageDraw.ImageDraw, s: int) -> None:
    """Amber tile with a dark panel: three switches."""
    rounded(d, s, AMBER, 0.2)
    w = s * 0.08
    for i, on in enumerate((True, False, True)):
        x = s * (0.25 + 0.25 * i)
        d.rounded_rectangle((x - w, s * 0.28, x + w, s * 0.72), radius=int(w), fill=DARK)
        cy = s * (0.38 if on else 0.62)
        d.ellipse((x - w * 0.7, cy - w * 0.7, x + w * 0.7, cy + w * 0.7), fill=AMBER)


def category_icon(d: ImageDraw.ImageDraw, s: int) -> None:
    """Monochrome white: the same three switches, no tile."""
    w = s * 0.11
    for i, on in enumerate((True, False, True)):
        x = s * (0.2 + 0.3 * i)
        d.rounded_rectangle((x - w, s * 0.1, x + w, s * 0.9), radius=int(w), outline=WHITE, width=max(1, int(s * 0.05)))
        cy = s * (0.3 if on else 0.7)
        d.ellipse((x - w * 0.6, cy - w * 0.6, x + w * 0.6, cy + w * 0.6), fill=WHITE)


def action_state(d: ImageDraw.ImageDraw, s: int) -> None:
    """A toggle switch."""
    lw = max(1, int(s * 0.07))
    d.rounded_rectangle((s * 0.1, s * 0.3, s * 0.9, s * 0.7), radius=int(s * 0.2), outline=WHITE, width=lw)
    d.ellipse((s * 0.55, s * 0.35, s * 0.85, s * 0.65), fill=WHITE)


def action_command(d: ImageDraw.ImageDraw, s: int) -> None:
    """A power symbol."""
    lw = max(1, int(s * 0.09))
    d.arc((s * 0.15, s * 0.2, s * 0.85, s * 0.9), start=-60, end=240, fill=WHITE, width=lw)
    d.line((s * 0.5, s * 0.08, s * 0.5, s * 0.5), fill=WHITE, width=lw)


def action_sound(d: ImageDraw.ImageDraw, s: int) -> None:
    """A note."""
    lw = max(1, int(s * 0.09))
    d.line((s * 0.62, s * 0.12, s * 0.62, s * 0.68), fill=WHITE, width=lw)
    d.line((s * 0.62, s * 0.12, s * 0.9, s * 0.22), fill=WHITE, width=lw)
    d.ellipse((s * 0.3, s * 0.55, s * 0.68, s * 0.85), fill=WHITE)


def action_dial(d: ImageDraw.ImageDraw, s: int) -> None:
    """A dial with a pointer."""
    lw = max(1, int(s * 0.08))
    d.ellipse((s * 0.12, s * 0.12, s * 0.88, s * 0.88), outline=WHITE, width=lw)
    d.line((s * 0.5, s * 0.5, s * 0.5, s * 0.2), fill=WHITE, width=lw)


def key_placeholder(d: ImageDraw.ImageDraw, s: int) -> None:
    """Dark key with a grey ring: what a key shows before the plugin draws it."""
    rounded(d, s, DARK, 0.15)
    lw = max(1, int(s * 0.03))
    d.ellipse((s * 0.3, s * 0.2, s * 0.7, s * 0.6), outline=(74, 74, 85, 255), width=lw)


def dial_icon(d: ImageDraw.ImageDraw, s: int) -> None:
    """The dial action's icon on the touch strip while unassigned."""
    rounded(d, s, DARK, 0.15)
    lw = max(1, int(s * 0.05))
    d.ellipse((s * 0.2, s * 0.2, s * 0.8, s * 0.8), outline=AMBER, width=lw)
    d.line((s * 0.5, s * 0.5, s * 0.5, s * 0.26), fill=AMBER, width=lw)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save("plugin", plugin_icon, 256)
    save("category", category_icon, 28)
    save("action-state", action_state, 20)
    save("action-command", action_command, 20)
    save("action-sound", action_sound, 20)
    save("action-dial", action_dial, 20)
    save("key", key_placeholder, 72)
    save("dial", dial_icon, 72)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
