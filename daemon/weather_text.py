"""Swedish text from the weather interpretation. Pure.

facts_sv() is the fact list handed to the AI: complete, plain, one line
per part of the day, so the AI can choose what to say and what it means
for clothes. sentence_sv() is one short sentence for the briefing made
without the AI.

Numbers are written for speech: "minus 3 grader", "klockan 9".
"""

import datetime
from typing import Sequence

from daemon.personal import WEEKDAYS, swedish_date
from daemon.smhi import TIMEZONE
from daemon.smhi_warnings import Level, WeatherWarning
from daemon.weather import (
    DayWeather,
    Intensity,
    Part,
    Precipitation,
    PrecipKind,
    Sky,
    Wind,
)

K = PrecipKind
# (light, moderate, heavy)
_STEADY: dict[PrecipKind, tuple[str, str, str]] = {
    K.RAIN: ("lätt regn", "regn", "kraftigt regn"),
    K.DRIZZLE: ("duggregn",) * 3,
    K.SLEET: ("lätt snöblandat regn", "snöblandat regn", "kraftigt snöblandat regn"),
    K.SNOW: ("lätt snöfall", "snöfall", "kraftigt snöfall"),
    K.WET_SNOW: ("lite blötsnö", "blötsnö", "kraftigt blötsnöfall"),
    K.FREEZING_RAIN: ("underkylt regn",) * 3,
    K.FREEZING_DRIZZLE: ("underkylt duggregn",) * 3,
    K.HAIL: ("hagel",) * 3,
    K.GRAUPEL: ("snöhagel",) * 3,
    K.ICE_PELLETS: ("iskorn",) * 3,
}
_SHOWERS: dict[PrecipKind, tuple[str, str, str]] = {
    K.RAIN: ("lätta regnskurar", "regnskurar", "kraftiga regnskurar"),
    K.SLEET: (
        "lätta skurar av snöblandat regn",
        "skurar av snöblandat regn",
        "kraftiga skurar av snöblandat regn",
    ),
    K.SNOW: ("lätta snöbyar", "snöbyar", "kraftiga snöbyar"),
}
_DEFINITE: dict[PrecipKind, str] = {
    K.RAIN: "regnet",
    K.DRIZZLE: "duggregnet",
    K.SLEET: "det snöblandade regnet",
    K.SNOW: "snöfallet",
    K.WET_SNOW: "blötsnön",
    K.FREEZING_RAIN: "det underkylda regnet",
    K.FREEZING_DRIZZLE: "det underkylda duggregnet",
    K.HAIL: "haglet",
    K.GRAUPEL: "snöhaglet",
    K.ICE_PELLETS: "iskornen",
}
_SKY_DAY = {
    Sky.CLEAR: "sol",
    Sky.NEARLY_CLEAR: "mest sol",
    Sky.HALFCLEAR: "sol och moln",
    Sky.VARIABLE: "växlande sol och moln",
    Sky.CLOUDY: "molnigt",
    Sky.OVERCAST: "mulet",
}
_WIND = {
    Wind.MODERATE: "måttlig vind",
    Wind.FRESH: "frisk vind",
    Wind.STRONG: "hård vind",
    Wind.STORM: "storm",
    Wind.HURRICANE: "orkan",
}
_PART_DEFINITE = {
    "morgon": "morgonen",
    "förmiddag": "förmiddagen",
    "eftermiddag": "eftermiddagen",
    "kväll": "kvällen",
}
_LEVEL = {
    Level.MESSAGE: "meddelande",
    Level.YELLOW: "gul",
    Level.ORANGE: "orange",
    Level.RED: "röd",
}


def facts_sv(
    days: Sequence[DayWeather], warnings: Sequence[WeatherWarning] = ()
) -> str:
    """The weather facts for the AI prompt, '' when there are none."""
    blocks = [_day_block(d) for d in days]
    if warnings and days:
        lines = ["Vädervarningar från SMHI:"]
        lines += [f"- {_warning_line(w, days[0])}" for w in warnings]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def sentence_sv(day: DayWeather, warnings: Sequence[WeatherWarning] = ()) -> str:
    """'Idag blir det 7 till 9 grader och risk för lätt regn på morgonen.'"""
    wet = [p for p in day.parts if p.precip]
    if not wet:
        rain = " och uppehåll"
    else:
        phrase = _precip(_worst(wet).precip)
        if len(wet) == len(day.parts):
            rain = f" och {phrase}"
        else:
            names = [_PART_DEFINITE.get(p.name, p.name) for p in wet]
            rain = f" och {phrase} på {_join(names)}"
    text = f"{_cap(day.label)} blir det {_temps(day.temp_min, day.temp_max)}{rain}."
    if day.slippery:
        text += " Det kan bli halt."
    if warnings:
        w = warnings[0]
        kind = "ett meddelande" if w.level == Level.MESSAGE else f"en {_LEVEL[w.level]} varning"
        text += f" SMHI har {kind} för {_uncap(w.event)}."
    return text


def _day_block(d: DayWeather) -> str:
    lines = [f"Väder {d.label}, {swedish_date(d.day)}:"]
    any_precip = any(p.precip for p in d.parts)
    lines += [f"- {_part_line(p, d, any_precip)}" for p in d.parts]
    lines += [f"- {line}" for line in _day_lines(d, any_precip)]
    return "\n".join(lines)


def _part_line(p: Part, d: DayWeather, any_precip: bool) -> str:
    temps = _temps(p.temp_min, p.temp_max)
    if p.feels_like is not None:
        temps += f", känns som {_deg(p.feels_like)} grader i vinden"
    sky = [
        _sky(p, d),
        "dimma" if p.fog else None,
        _precip(p.precip) if p.precip else ("uppehåll" if any_precip else None),
        "risk för åska" if p.thunder else None,
    ]
    gust = f"byar upp till {round(p.gust)} m/s" if p.gust is not None else None
    wind = ", ".join(s for s in (_WIND.get(p.wind), gust) if s)
    sentences = [temps, ", ".join(s for s in sky if s), wind]
    head = f"{_cap(p.name)}, klockan {p.start.hour}-{p.end.hour}"
    return f"{head}: " + ". ".join(_cap(s) for s in sentences if s) + "."


def _day_lines(d: DayWeather, any_precip: bool) -> list[str]:
    lines = []
    wet = [p for p in d.parts if p.precip]
    if d.precip_from and wet:
        lines.append(_starts(wet[0].precip, d.precip_from.hour))
    if d.precip_until and wet:
        lines.append(_stops(wet[-1].precip, d.precip_until.hour))
    if len(d.parts) > 1 and round(d.temp_min) != round(d.temp_max):
        lines.append(f"Lägst {_deg(d.temp_min)} och högst {_deg(d.temp_max)} grader.")
    whole = "hela kvällen" if d.label == "ikväll" else "hela dagen"
    if not any_precip:
        lines.append(f"Uppehåll {whole}.")
    elif d.precip_mm >= 1:
        lines.append(f"Totalt ungefär {round(d.precip_mm)} mm nederbörd.")
    if d.slippery:
        lines.append("Risk för halka.")
    if d.temp_change:
        than = "idag" if d.label == "imorgon" else "igår"
        warmer = "varmare" if d.temp_change > 0 else "kallare"
        lines.append(f"{abs(d.temp_change)} grader {warmer} än {than}.")
    if d.sunrise and d.sunset:
        if d.label == "ikväll":
            if d.sunset > d.parts[0].start:
                lines.append(f"Solen går ner {d.sunset:%H:%M}.")
        else:
            lines.append(f"Solen går upp {d.sunrise:%H:%M} och ner {d.sunset:%H:%M}.")
    return lines


def _starts(p: Precipitation, hour: int) -> str:
    if not p.likely:
        return f"Risk för {_phrase(p)} från ungefär klockan {hour}."
    return f"{_cap(_DEFINITE[p.kind])} börjar ungefär klockan {hour}."


def _stops(p: Precipitation, hour: int) -> str:
    if not p.likely:
        return f"Risk för {_phrase(p)} fram till ungefär klockan {hour}."
    return f"{_cap(_DEFINITE[p.kind])} slutar ungefär klockan {hour}."


def _warning_line(w: WeatherWarning, d: DayWeather) -> str:
    level = "Meddelande" if w.level == Level.MESSAGE else f"{_cap(_LEVEL[w.level])} varning"
    begun = w.start is None or w.start <= d.parts[0].start
    start = "redan nu" if begun else f"från {_when(w.start, d)}"
    end = f"till {_when(w.end, d)}" if w.end else "tills vidare"
    text = f"{level}: {w.event}, {start} {end}."
    if not w.certain:
        text += " Osäker."
    if w.text:
        text += f" {w.text}"
    return text


def _when(t: datetime.datetime, d: DayWeather) -> str:
    """'klockan 14', 'tisdag klockan 14' within a week, else with the date."""
    t = t.astimezone(TIMEZONE)
    clock = "midnatt" if t.hour == 0 else f"klockan {t.hour}"
    days = (t.date() - d.day).days
    if days == 0:
        return clock
    if 0 < days < 7:
        return f"{WEEKDAYS[t.weekday()]} {clock}"
    return f"{swedish_date(t.date())} {clock}"


def _sky(p: Part, d: DayWeather) -> str | None:
    if p.sky is None:
        return None
    middle = p.start + (p.end - p.start) / 2
    daylight = d.sunrise is not None and d.sunrise <= middle <= d.sunset
    return _SKY_DAY[p.sky] if daylight else p.sky.value


def _precip(p: Precipitation) -> str:
    phrase = _phrase(p)
    return phrase if p.likely else f"risk för {phrase}"


def _phrase(p: Precipitation) -> str:
    table = _SHOWERS if p.showers and p.kind in _SHOWERS else _STEADY
    return table[p.kind][p.intensity - Intensity.LIGHT]


def _worst(parts: list[Part]) -> Part:
    return max(parts, key=lambda p: (p.precip.likely, p.precip.intensity))


def _temps(low: float, high: float) -> str:
    if round(low) == round(high):
        return f"{_deg(low)} grader"
    return f"{_deg(low)} till {_deg(high)} grader"


def _deg(t: float) -> str:
    r = round(t)
    return f"minus {-r}" if r < 0 else str(r)


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " och " + words[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _uncap(s: str) -> str:
    return s[:1].lower() + s[1:]
