#!/usr/bin/env python
"""Generates a pool of short Swedish wake-up jokes to rate by hand (GH #14).
The approved ones go into daemon/jokes.json (gitignored), which the wake
line picks from. Uses OpenAI for real; safe while the daemon runs. Run on
the Pi from the repo root:

    bin/python tools/joke_pool.py --out /home/david/joke_pool.json
    bin/python tools/joke_pool.py --styles naturfilm --rounds 1 --out x.json

Per style it asks for general jokes and for jokes tied to a weekday or
the weather (tagged, see speech.JOKE_TAGS), in parallel, then drops
duplicates. Output: a JSON list of {"id", "style", "tags", "text"}.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daemon.config import Config  # noqa: E402
from daemon.openaiWrapper import OpenAiWrapper  # noqa: E402
from daemon.speech import JOKE_TAGS, MAX_JOKE, STYLES, looks_swedish  # noqa: E402

SYSTEM = (
    "Du är en skicklig svensk komediförfattare. Du skriver repliker som en "
    "röstassistent i en kontrollpanel bredvid sängen säger till en 12-åring "
    "som precis har vaknat och inte vill kliva upp. Allt läses upp av en röst, "
    "så det måste fungera att höra en gång, halvsovande. Svara bara med JSON."
)

RULES = (
    "Vad som gör en bra replik här:\n"
    "- En eller två korta meningar, högst 20 ord. Poängen sist.\n"
    "- En konkret, oväntad bild eller vändning. Inga förklaringar av skämtet.\n"
    "- Om sängen, täcket, kudden, frukosten, morgonen, att vakna, skolan, "
    "veckodagen eller vädret.\n"
    "- Rolig för en 12-åring: inte barnslig, inte elak, inget tjat, inget "
    "\"du måste\", ingen peppning.\n"
    "- Använd \"du\", aldrig ett namn.\n"
    "- Inga påhittade fakta om världen, inga ordvitsar som bara syns i skrift.\n"
    "- Naturlig talad svenska. Varje replik ska vara olik de andra.\n"
    "Tänk ut många fler än du behöver och behåll bara de bästa."
)


def ask_general(ai: OpenAiWrapper, style: str, count: int) -> list[dict]:
    user = (
        f"Stil: {STYLES[style].prompt}\n\n{RULES}\n\n"
        f"Skriv de {count} bästa replikerna i den stilen. De ska passa vilken "
        "morgon som helst.\n"
        'Svara med JSON: {"repliker": ["...", "..."]}'
    )
    reply = ai.chat_json(SYSTEM, user, "high")
    return [{"text": t, "tags": []} for t in reply.get("repliker", []) if isinstance(t, str)]


def ask_tagged(ai: OpenAiWrapper, style: str, count: int) -> list[dict]:
    user = (
        f"Stil: {STYLES[style].prompt}\n\n{RULES}\n\n"
        f"Skriv de {count} bästa replikerna i den stilen som bara passar vissa "
        "morgnar: en viss veckodag eller ett visst väder. Märk varje replik med "
        f"de taggar den kräver, bara från den här listan: {', '.join(JOKE_TAGS)}. "
        "Sprid dem över olika taggar.\n"
        'Svara med JSON: {"repliker": [{"text": "...", "taggar": ["..."]}]}'
    )
    reply = ai.chat_json(SYSTEM, user, "high")
    out = []
    for item in reply.get("repliker", []):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        tags = [t for t in item.get("taggar", []) if t in JOKE_TAGS]
        if tags:
            out.append({"text": item["text"], "tags": tags})
    return out


def _key(text: str) -> str:
    return re.sub(r"[^a-zåäö]", "", text.casefold())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--styles", nargs="+", choices=sorted(STYLES), default=sorted(STYLES))
    parser.add_argument("--general", type=int, default=20, help="general jokes per call")
    parser.add_argument("--tagged", type=int, default=15, help="tagged jokes per call")
    parser.add_argument("--rounds", type=int, default=1, help="calls of each kind per style")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--secrets", default=str(Config.openai_key_file.parent),
        help="directory with the OpenAI key and personal.json",
    )
    args = parser.parse_args()

    secrets = Path(args.secrets)
    cfg = Config(
        openai_key_file=secrets / Config.openai_key_file.name,
        personal_file=secrets / "personal.json",
    )
    ai = OpenAiWrapper(cfg.openai_key_file, cfg.personal_file, cfg)

    jobs = []
    for style in args.styles:
        for _ in range(args.rounds):
            jobs.append((style, ask_general, args.general))
            jobs.append((style, ask_tagged, args.tagged))

    def run(job):
        style, ask, count = job
        try:
            return style, ask(ai, style, count)
        except Exception as e:
            print(f"{style}: {ask.__name__} failed: {e}", file=sys.stderr)
            return style, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, jobs))

    seen, jokes = set(), []
    for style, items in results:
        for item in items:
            text = " ".join(item["text"].split())
            if not text or len(text) > MAX_JOKE or not looks_swedish(text):
                continue
            key = _key(text)
            if key in seen:
                continue
            seen.add(key)
            jokes.append({"id": f"j{len(jokes) + 1:03d}", "style": style,
                          "tags": item["tags"], "text": text})

    Path(args.out).write_text(json.dumps(jokes, ensure_ascii=False, indent=1), encoding="utf-8")
    by_style = {s: sum(j["style"] == s for j in jokes) for s in args.styles}
    print(f"{len(jokes)} jokes in {args.out}: {by_style}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
