"""Builds the Stream Deck + profile "Panelen" as a .streamDeckProfile
file (a zip of a .sdProfile folder, the format the app exports), so the
whole layout installs with a double-click on any PC that has the
plugin: no key has to be configured by hand.

    python make_profile.py            -> Panelen.streamDeckProfile

Layout (4 x 2 keys, 4 dials; swipe the touch strip to change page):

  Page 1   Säng (uttag)  Byrå (uttag)  Bakgrund      Knapplampor
           Slinga säng   Slinga fönst. Demo          Släck allt
  Page 2   Knapp 2..8 (ljud)                         + Stoppa ljud
  Page 3   Knapp 9..11, Sänglampa, Ljud (tyst), Stoppa ljud
  Dials    Volym | Ljus säng | Ljus fönster | Effekt säng   (every page)
"""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
PLUGIN_UUID = "com.supremec.panelen"
PLUGIN_NAME = "Panelen"
PLUGIN_VERSION = "0.1"
DEVICE_MODEL = "20GBD9901"  # Stream Deck +
PROFILE_NAME = "Panelen"
OUT = HERE / f"{PROFILE_NAME}.streamDeckProfile"

ACTION_NAMES = {"state": "Brytare", "command": "Kommando", "sound": "Ljud", "dial": "Ratt"}


def action(kind: str, settings: dict) -> dict:
    return {
        "ActionID": str(uuid.uuid4()),
        "LinkedTitle": True,
        "Name": ACTION_NAMES[kind],
        "Plugin": {"Name": PLUGIN_NAME, "UUID": PLUGIN_UUID, "Version": PLUGIN_VERSION},
        "Resources": None,
        "Settings": settings,
        "State": 0,
        "States": [{}],
        "UUID": f"{PLUGIN_UUID}.{kind}",
    }


def state(item: str) -> dict:
    return action("state", {"item": item})


def command(name: str) -> dict:
    return action("command", {"command": name})


def sound(pin: int) -> dict:
    return action("sound", {"pin": pin})


def dial(kind: str) -> dict:
    return action("dial", {"kind": kind})


DIALS = {
    "0,0": dial("volume"),
    "1,0": dial("strip_0"),
    "2,0": dial("strip_1"),
    "3,0": dial("effect_0"),
}

PAGES = [
    {
        "0,0": state("bed_socket"),
        "1,0": state("drawer_socket"),
        "2,0": state("backlight"),
        "3,0": state("button_leds"),
        "0,1": state("strip_0"),
        "1,1": state("strip_1"),
        "2,1": state("demo"),
        "3,1": command("all_off"),
    },
    {
        "0,0": sound(2),
        "1,0": sound(3),
        "2,0": sound(4),
        "3,0": sound(5),
        "0,1": sound(6),
        "1,1": sound(7),
        "2,1": sound(8),
        "3,1": command("stop"),
    },
    {
        "0,0": sound(9),
        "1,0": sound(10),
        "2,0": sound(11),
        "3,0": command("bedlamp"),
        "0,1": command("mute"),
        "1,1": command("stop"),
    },
]


def fresh_dials() -> dict:
    """Every page needs its own ActionIDs."""
    return {pos: dial(a["Settings"]["kind"]) for pos, a in DIALS.items()}


def page_manifest(keys: dict) -> dict:
    return {
        "Controllers": [
            {"Type": "Keypad", "Actions": keys},
            {"Type": "Encoder", "Actions": fresh_dials()},
        ],
        "Icon": "",
        "Name": "",
    }


def build() -> Path:
    profile_id = str(uuid.uuid4()).upper()
    page_ids = [str(uuid.uuid4()).upper() for _ in PAGES]
    root = HERE / "build" / f"{profile_id}.sdProfile"
    if root.parent.exists():
        shutil.rmtree(root.parent)
    (root / "Images").mkdir(parents=True)
    manifest = {
        "Device": {"Model": DEVICE_MODEL, "UUID": ""},
        "Name": PROFILE_NAME,
        "Pages": {
            "Current": page_ids[0].lower(),
            "Default": page_ids[0].lower(),
            "Pages": [p.lower() for p in page_ids],
        },
        "Version": "3.0",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for page_id, keys in zip(page_ids, PAGES):
        folder = root / "Profiles" / page_id
        (folder / "Images").mkdir(parents=True)
        (folder / "manifest.json").write_text(
            json.dumps(page_manifest(keys), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(root.rglob("*")):
            arcname = path.relative_to(root.parent).as_posix()
            if path.is_dir():
                z.writestr(arcname + "/", "")
            else:
                z.write(path, arcname)
    return root


if __name__ == "__main__":
    folder = build()
    print(f"wrote {OUT} (from {folder})")
