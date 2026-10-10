"""What the panel says, in Swedish (GH #14).

Facts come from local templates, the same order every day, so nothing is
made up and the texts become predictable. The wake line's joke comes
from a hand-rated pool (daemon/jokes.py). The text model writes the
clothing advice from the weather facts, and the joke only when the pool
is empty. Its reply is checked locally (JSON, length, Swedish); on
failure the template goes without it, or with the weather sentence.

- Wake line (in bed, after the alarm): greeting, weekday, joke, "clothes
  on, then breakfast". Nothing to remember.
- Overview (check-in before leaving): minutes left, school start, things
  to bring, today's events, clothing advice.
- Countdown: fixed texts, synthesised once and cached on disk.
- Status (AI button): time, minutes left, events, clothing advice.

The OpenAI calls block: run them on the AI job lane.
"""

from collections import deque
from dataclasses import dataclass
import datetime
import hashlib
import io
import logging
import os
from pathlib import Path
import re
import wave

from daemon import agenda
from daemon.agenda import Item, Kind
from daemon.cevent import CEvent
from daemon.config import Config
from daemon.jokes import JokeBox
from daemon.personal import MONTHS, WEEKDAYS, Personal, swedish_date
from daemon.weather import DayWeather

logger = logging.getLogger("daemon.speech")

HOURS = ("tolv", "ett", "två", "tre", "fyra", "fem", "sex", "sju", "åtta", "nio", "tio", "elva")
_CLOCK = {
    0: "{h}",
    5: "fem över {h}",
    10: "tio över {h}",
    15: "kvart över {h}",
    20: "tjugo över {h}",
    25: "fem i halv {n}",
    30: "halv {n}",
    35: "fem över halv {n}",
    40: "tjugo i {n}",
    45: "kvart i {n}",
    50: "tio i {n}",
    55: "fem i {n}",
}

COUNTDOWN = {
    15: "15 minuter kvar.",
    5: "5 minuter kvar. Skor och jacka.",
    0: "Dags att gå. Ha en bra dag!",
}

VOICE_BASE = (
    "Tala svenska med naturligt rikssvenskt uttal. Lugnt tempo och korta "
    "pauser mellan meningarna."
)
VOICE_PLAIN = f"{VOICE_BASE} Vänlig och saklig, som en lugn kompis."


@dataclass(frozen=True)
class Style:
    prompt: str
    """How the joke is written."""
    voice: str
    """How the wake line is read (text-to-speech instructions)."""


STYLES = {
    "torr": Style(
        "Torr, lakonisk humor. Underdriv. Som en snäll robot som själv är lite trött.",
        "Torr och lugn, lite underfundig.",
    ),
    "absurd": Style(
        "Absurd humor: oväntade bilder, saker som beter sig som människor, "
        "till exempel frukosten, kudden eller strumporna.",
        "Allvarlig och lugn, som om det absurda vore helt normalt.",
    ),
    "ordvits": Style(
        "Ordvitsar och ordlekar på svenska.",
        "Glad och finurlig, med en liten paus före poängen.",
    ),
    "sportkommentator": Style(
        "Överdramatisk sportkommentator som kommenterar uppvaknandet som en final.",
        "Som en entusiastisk sportkommentator, men inte skrikig.",
    ),
    "rymdstation": Style(
        "Mission control på en rymdstation: uppvaknandet är en uppskjutning "
        "och frukosten är målet.",
        "Som radio från mission control: lugn, saklig och lite högtidlig.",
    ),
    "pappa": Style(
        "Pappaskämt: så dåliga att de blir roliga.",
        "Varm och lite för nöjd med sitt eget skämt.",
    ),
    "nyhetsuppläsare": Style(
        "Extra nyhetssändning: morgonen och sängen rapporteras som stora "
        "nyheter, med allvarlig nyhetston.",
        "Som en allvarlig nyhetsuppläsare i radio.",
    ),
    "klassiker": Style(
        "Klassiska roliga historier och gåtor: en fråga, sedan poängen.",
        "Varm och finurlig. Läs frågan, gör en tydlig paus, sedan poängen.",
    ),
    "naturfilm": Style(
        "Naturfilmsberättare som viskande beskriver en sovande tonåring som "
        "ett sällsynt djur i sitt bo.",
        "Lugn, låg och fascinerad, som en naturfilmsberättare.",
    ),
}
# Weekday and weather tags on pooled jokes; a joke with tags is only told
# when all of them fit the day.
JOKE_TAGS = (
    "måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag",
    "regn", "snö", "kallt", "varmt", "mörkt", "sol",
)
DEFAULT_STYLE = "torr"

SYSTEM = (
    "Du skriver korta repliker till en röstassistent i en kontrollpanel "
    "bredvid sängen hos {listener} som bor i Stockholm. Allt läses upp, så "
    "skriv som man pratar: korta meningar, inga listor, inga emojis, inga "
    "förkortningar. Tjata aldrig och skriv aldrig \"du måste\". Ingen "
    "överdriven peppning. Hitta aldrig på fakta om världen; använd bara det "
    "som står i meddelandet. Skriv alltid på svenska, aldrig på något annat "
    "språk. Svara bara med ett JSON-objekt."
)

CLOTHES_SHORT_ASK = (
    '"klader_kort": högst fyra ord om vilka kläder som passar idag enligt '
    "vädret, bara det man tar på sig när man går upp, inga ytterkläder "
    '(jacka, mössa, skor), till exempel "långbyxor och tjocktröja" eller '
    '"t-shirt räcker".'
)

# Field limits in characters; a longer reply is rejected.
MAX_JOKE = 160
MAX_CLOTHES_SHORT = 40
MAX_CLOTHES = 180
RECENT_JOKES = 14

_SWEDISH = {
    "och", "det", "du", "är", "en", "ett", "att", "på", "i", "med", "som",
    "för", "idag", "inte", "sen", "till", "har", "din", "dig", "om", "av",
    "så", "nu", "kan", "ska", "men", "den", "vi", "jag", "eller", "ut",
}
_FOREIGN = {
    "the", "and", "you", "your", "it", "el", "los", "las", "que", "es",
    "una", "por", "para", "con", "y", "der", "die", "und",
}


def clock_sv(t: datetime.datetime | datetime.time) -> str:
    """'tio över nio', 'halv sju', 'sex'; other minutes as '9.17'."""
    h, m = t.hour, t.minute
    if m % 5:
        return f"{h}.{m:02d}"
    return _CLOCK[m].format(h=HOURS[h % 12], n=HOURS[(h + 1) % 12])


def join_sv(words: list[str]) -> str:
    """'a', 'a och b', 'a, b och c'"""
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])} och {words[-1]}"


def looks_swedish(text: str) -> bool:
    """Rough check that the model kept to Swedish (it has answered in
    Spanish). Enough Swedish function words, few foreign ones."""
    words = re.findall(r"[a-zåäöéü]+", text.casefold())
    swedish = sum(w in _SWEDISH for w in words)
    foreign = sum(w in _FOREIGN for w in words)
    has_letters = any(c in "åäö" for c in text.casefold())
    return (swedish > 0 or has_letters) and foreign * 3 <= swedish


PCM_RATE = 24000  # OpenAI text-to-speech "pcm": 24 kHz, 16-bit, mono
PAUSE = "‖"  # a pause of speech_pause_seconds in a text to speak
# A free-standing dash ('? – Navigator.') is a pause of
# speech_dash_pause_seconds, not a word. Hyphens inside words stay.
_PAUSE_DASH = re.compile(r"\s*(?:[–—]|(?<=\s)-(?=\s))\s*")


def segments(text: str, pause: float, dash_pause: float) -> list[tuple[str, float]]:
    """(text, silence after it in seconds) for each part of a text: split
    at PAUSE marks and at free-standing dashes. The last part has none."""
    out: list[tuple[str, float]] = []
    for chunk in text.split(PAUSE):
        parts = [p.strip() for p in _PAUSE_DASH.split(chunk)]
        parts = [p for p in parts if p]
        out += [(p, dash_pause) for p in parts[:-1]]
        if parts:
            out.append((parts[-1], pause))
    if out:
        out[-1] = (out[-1][0], 0.0)
    return out


def spoken(text: str) -> str:
    """One text as it is sent to text-to-speech in one piece: pauses
    become '...'."""
    return _PAUSE_DASH.sub("... ", text.replace(PAUSE, "...")).strip()


def countdown_text(minutes: int) -> str:
    return COUNTDOWN.get(minutes, f"{minutes} minuter kvar.")


def school_event(events: list[CEvent], day: datetime.date, title: str) -> CEvent | None:
    """Today's first timed event whose title starts with `title`."""
    prefix = title.strip().casefold()
    starts = [
        e
        for e in events
        if e.has_time and e.start.date() == day
        and e.summary.strip().casefold().startswith(prefix)
    ]
    return min(starts, key=lambda e: e.start, default=None)


def is_school(event: CEvent, title: str) -> bool:
    return event.summary.strip().casefold().startswith(title.strip().casefold())


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text[-1:] in ".!?" else f"{text}."


def _until(day: datetime.date, today: datetime.date) -> str:
    if (day - today).days < 7:
        return WEEKDAYS[day.weekday()]
    return f"den {day.day} {MONTHS[day.month - 1]}"


def describe(item: Item, today: datetime.date) -> str:
    """One event as it is said after 'Idag:'."""
    e = item.event
    name = e.summary.strip()
    if item.kind == Kind.UPCOMING:
        return f"{name} klockan {clock_sv(e.start)}"
    if item.kind == Kind.STARTED:
        return f"{name}, som började klockan {clock_sv(e.start)}"
    if item.kind == Kind.ONGOING:
        return f"{name}, till klockan {clock_sv(e.end)}"
    if item.kind == Kind.FIRST_DAY:
        return f"{name} börjar, till och med {_until(item.last_day, today)}"
    if item.kind == Kind.LAST_DAY:
        return f"sista dagen med {name}"
    return name  # WHOLE_DAY


@dataclass(frozen=True)
class AiLines:
    joke: str = ""
    clothes_short: str = ""
    clothes: str = ""


class Speech:
    def __init__(self, ai, config: Config | None = None):
        """ai: OpenAiWrapper (chat_json, speak)."""
        self._ai = ai
        self._cfg = config or Config()
        self._recent_jokes: deque[str] = deque(maxlen=RECENT_JOKES)
        self._jokes = JokeBox(
            self._cfg.jokes_file, self._cfg.joke_state_file, self._cfg.joke_repeat_days
        )

    # ---- texts ------------------------------------------------------------

    def personal(self) -> Personal:
        return Personal.load(self._cfg.personal_file)

    def style(self) -> Style:
        style = STYLES.get(self._cfg.humour_style)
        if style is None:
            logger.warning("Unknown humour style %r, using %s", self._cfg.humour_style, DEFAULT_STYLE)
            style = STYLES[DEFAULT_STYLE]
        return style

    def wake_line(
        self,
        now: datetime.datetime,
        weather_facts: str = "",
        school_day: bool = False,
        weather_day: DayWeather | None = None,
    ) -> tuple[str, str]:
        """The wake line and how to read it (text-to-speech instructions):
        today's joke from the rated pool in its own style, else one from
        the text model in the configured style."""
        joke = self._jokes.next(now.date(), weather_day)
        if joke is None:
            style = self.style()
            return self.wake_text(now, weather_facts, school_day, style), self.wake_voice(style)
        style = STYLES.get(joke.style, self.style())
        text = self.wake_text(now, weather_facts, school_day, style, joke=joke.text)
        return text, self.wake_voice(style)

    def wake_text(
        self,
        now: datetime.datetime,
        weather_facts: str = "",
        school_day: bool = False,
        style: Style | None = None,
        joke: str | None = None,
    ) -> str:
        """'God morgon, Kim. Tisdag. ‖ <joke> ‖ Kläderna på, tjocktröja, sen
        frukost.' (‖ is a pause.) Without `joke` the text model writes one."""
        name = self.personal().name
        lines = self._wake_lines(
            now.date(), weather_facts, school_day, style or self.style(), want_joke=joke is None
        )
        if joke is not None:
            lines = AiLines(joke=joke, clothes_short=lines.clothes_short)
        parts = [f"God morgon{', ' + name if name else ''}. {WEEKDAYS[now.weekday()].capitalize()}."]
        if lines.joke:
            parts.append(_sentence(lines.joke))
            self._recent_jokes.append(lines.joke)
        if lines.clothes_short:
            short = lines.clothes_short.rstrip(".!")
            parts.append(f"Kläderna på, {short[:1].lower()}{short[1:]}, sen frukost.")
        else:
            parts.append("Kläderna på, sen frukost.")
        return f" {PAUSE} ".join(parts)

    def overview_text(
        self,
        now: datetime.datetime,
        events: list[CEvent],
        school_start: datetime.datetime,
        minutes_left: int,
        weather_facts: str = "",
        weather_sentence: str = "",
    ) -> str:
        """Before leaving: minutes left (the check-in's own number, since
        the text is made ahead), school start, things to bring, today's
        other events, clothing advice."""
        today = now.date()
        parts = [f"{minutes_left} minuter tills du går." if minutes_left > 0 else "Dags att gå."]
        parts.append(f"Skolan börjar klockan {clock_sv(school_start)}.")
        bring = self.personal().things_to_bring(
            today, [e.summary for e in events], school_day=True
        )
        if bring:
            parts.append(f"Ta med {join_sv(bring)}.")
        title = self._cfg.school_title
        items = [
            i
            for i in agenda.select(events, now, self._cfg, morning=True)
            if not is_school(i.event, title)
        ]
        if items:
            parts.append(f"Idag: {join_sv([describe(i, today) for i in items])}.")
        clothes = self._clothes(weather_facts, "idag", today) or weather_sentence
        if clothes:
            parts.append(_sentence(clothes))
        return " ".join(parts)

    def status_text(
        self,
        now: datetime.datetime,
        events: list[CEvent],
        leave: datetime.datetime | None = None,
        weather_facts: str = "",
        weather_sentence: str = "",
    ) -> str:
        """AI button: time, minutes until leaving, events, clothing advice."""
        parts = [f"Klockan är {clock_sv(now)}."]
        if leave is not None and leave > now:
            minutes = round((leave - now).total_seconds() / 60)
            parts.append(f"{minutes} minuter tills du går.")
        items = agenda.select(events, now, self._cfg, morning=False)
        if items:
            parts.append(f"Idag: {join_sv([describe(i, now.date()) for i in items])}.")
        else:
            parts.append("Inget mer i kalendern idag.")
        clothes = self._clothes(weather_facts, "enligt vädret", now.date()) or weather_sentence
        if clothes:
            parts.append(_sentence(clothes))
        return " ".join(parts)

    # ---- the text model -----------------------------------------------------

    def _system(self, today: datetime.date) -> str:
        return SYSTEM.format(listener=self.personal().describe(today).rstrip(","))

    def _wake_lines(
        self,
        day: datetime.date,
        weather_facts: str,
        school_day: bool,
        style: Style,
        want_joke: bool = True,
    ) -> AiLines:
        if not want_joke:
            return AiLines(clothes_short=self._clothes_short(day, weather_facts))
        name = self.personal().name or "lyssnaren"
        weather = f"Väder:\n{weather_facts}" if weather_facts else "Väder: saknas."
        avoid = ""
        if self._recent_jokes:
            avoid = "\nUpprepa inte de här tidigare skämten: " + " | ".join(self._recent_jokes)
        user = (
            f"Fakta:\n- Idag: {swedish_date(day)}{', skoldag' if school_day else ''}\n"
            f"{weather}\n\n"
            "Skriv två saker:\n"
            f'"skamt": en rolig replik, en eller två korta meningar och högst 20 '
            f"ord, som får {name} att vilja kliva upp. {style.prompt} Om "
            "morgonen, sängen, frukosten, veckodagen eller vädret. Inte elak. "
            "Hälsningen och veckodagen sägs redan före repliken: upprepa dem "
            "inte. Hellre en tydlig poäng än en stämning.\n"
            f"{CLOTHES_SHORT_ASK} Tom sträng om vädret saknas."
            f"{avoid}\n\n"
            'Svara på svenska med JSON: {"skamt": "...", "klader_kort": "..."}'
        )
        reply = self._ask(
            day, user, {"skamt": MAX_JOKE, "klader_kort": MAX_CLOTHES_SHORT}, effort="medium"
        )
        if reply is None:
            return AiLines()
        short = reply["klader_kort"] if weather_facts else ""
        return AiLines(joke=reply["skamt"], clothes_short=short)

    def _clothes_short(self, day: datetime.date, weather_facts: str) -> str:
        """A few words on what to put on when getting up, '' without
        weather or when the model fails."""
        if not weather_facts:
            return ""
        user = (
            f"Väder:\n{weather_facts}\n\n{CLOTHES_SHORT_ASK}\n\n"
            'Svara på svenska med JSON: {"klader_kort": "..."}'
        )
        reply = self._ask(day, user, {"klader_kort": MAX_CLOTHES_SHORT})
        return reply["klader_kort"] if reply else ""

    def _clothes(self, weather_facts: str, when: str, day: datetime.date) -> str:
        """One sentence of clothing advice, '' without weather or when the
        model fails (the caller then uses the weather sentence)."""
        if not weather_facts:
            return ""
        user = (
            f"Väder:\n{weather_facts}\n\n"
            f'Skriv "klader": en mening, högst 20 ord, om vad som passar att ha '
            f"på sig {when} och varför, till exempel när regnet kommer. Nämn bara "
            "det som spelar roll.\n\n"
            'Svara på svenska med JSON: {"klader": "..."}'
        )
        reply = self._ask(day, user, {"klader": MAX_CLOTHES})
        return reply["klader"] if reply else ""

    def _ask(
        self, day: datetime.date, user: str, fields: dict[str, int], effort: str = "low"
    ) -> dict | None:
        """The model's reply with every field a checked string, or None
        after two failed tries."""
        for attempt in (1, 2):
            try:
                reply = self._ai.chat_json(self._system(day), user, effort)
                checked = _check(reply, fields)
                if checked is not None:
                    return checked
                logger.warning("Text model reply rejected (try %d): %r", attempt, reply)
            except Exception as e:
                logger.warning("Text model failed (try %d): %s", attempt, e)
        return None

    # ---- speech -------------------------------------------------------------

    def say(self, text: str, instructions: str = VOICE_PLAIN) -> bytes:
        """Text-to-speech, MP3. Blocking; raises on failure."""
        logger.info("Speaking: %s", text)
        parts = segments(
            text, self._cfg.speech_pause_seconds, self._cfg.speech_dash_pause_seconds
        )
        if len(parts) <= 1:
            return self._ai.speak(spoken(text), instructions)
        # One request per part, joined with real silence: the voice's own
        # pauses (for '...') are too short to follow a joke half asleep.
        pcm = bytearray()
        for part, silence in parts:
            chunk = self._ai.speak(part, instructions, response_format="pcm")
            pcm += chunk[: len(chunk) // 2 * 2]
            pcm += bytes(round(PCM_RATE * silence) * 2)
        return _wav(bytes(pcm))

    def wake_voice(self, style: Style | None = None) -> str:
        return f"{VOICE_BASE} {(style or self.style()).voice}"

    def cached(self, text: str, instructions: str = VOICE_PLAIN) -> bytes:
        """A fixed text from the disk cache, synthesised on first use."""
        cfg = self._cfg
        key = "|".join((cfg.tts_model, cfg.voice, instructions, text))
        path = Path(cfg.speech_cache_dir) / (
            hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".mp3"
        )
        try:
            return path.read_bytes()
        except FileNotFoundError:
            pass
        audio = self._ai.speak(spoken(text), instructions)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(audio)
        os.replace(tmp, path)
        logger.info("Cached speech %s: %s", path.name, text)
        return audio


def _wav(pcm: bytes) -> bytes:
    """OpenAI's raw PCM (24 kHz, 16-bit, mono) as a WAV file."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(PCM_RATE)
        w.writeframes(pcm)
    return out.getvalue()


def _check(reply: dict, fields: dict[str, int]) -> dict | None:
    """Every field present as a string within its limit, and the whole
    reply Swedish. Empty strings are allowed."""
    out = {}
    for name, limit in fields.items():
        value = reply.get(name, "")
        if not isinstance(value, str):
            return None
        value = " ".join(value.split())
        if len(value) > limit:
            return None
        out[name] = value
    text = " ".join(out.values())
    if text and not looks_swedish(text):
        return None
    return out
