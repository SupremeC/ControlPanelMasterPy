#!/usr/bin/env python
"""Swedish weather text (daemon/weather_text.py): golden strings from
hand-made DayWeathers and from the saved real SMHI forecast.
"""

import datetime
import json
from pathlib import Path
import unittest

from daemon.smhi import TIMEZONE, parse_forecast
from daemon.smhi_warnings import Level, WeatherWarning
from daemon.weather import (
    DayWeather,
    Intensity,
    Part,
    Precipitation,
    PrecipKind,
    Sky,
    Wind,
    periods,
    summarize,
)
from daemon.weather_text import facts_sv, sentence_sv

SAMPLE = Path(__file__).resolve().parent / "data" / "smhi_snow1g_2026-10-10.json"
MONDAY = datetime.date(2026, 10, 12)


def local(text: str) -> datetime.datetime:
    naive = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=TIMEZONE)


def precip(kind=PrecipKind.RAIN, intensity=Intensity.MODERATE, showers=False,
           likely=True, mm=2.0) -> Precipitation:
    return Precipitation(kind, intensity, showers, likely, mm)


def part(name="morgon", hours=(6, 9), temp=(8.0, 8.0), feels=None, sky=Sky.OVERCAST,
         fog=False, rain=None, thunder=False, wind=Wind.LIGHT, gust=None,
         day="2026-10-12") -> Part:
    return Part(
        name=name,
        start=local(f"{day} {hours[0]:02}:00"),
        end=local(f"{day} {hours[1]:02}:00"),
        temp_min=temp[0],
        temp_max=temp[1],
        feels_like=feels,
        sky=sky,
        fog=fog,
        precip=rain,
        thunder=thunder,
        wind=wind,
        wind_max=5.0,
        gust=gust,
    )


def day_weather(*parts: Part, label="idag", day=MONDAY, sun=("07:19", "17:49"),
                **kw) -> DayWeather:
    values = dict(
        precip_from=None,
        precip_until=None,
        precip_mm=sum(p.precip.mm for p in parts if p.precip),
        slippery=False,
        temp_change=None,
    )
    values.update(kw)
    return DayWeather(
        label=label,
        day=day,
        parts=parts,
        temp_min=min(p.temp_min for p in parts),
        temp_max=max(p.temp_max for p in parts),
        sunrise=local(f"{day} {sun[0]}") if sun else None,
        sunset=local(f"{day} {sun[1]}") if sun else None,
        **values,
    )


def alert(level=Level.YELLOW, event="Mycket kraftig vind", start="2026-10-12 14:00",
          end="2026-10-12 20:00", certain=True, text="") -> WeatherWarning:
    return WeatherWarning(
        level=level,
        event=event,
        area="Stockholms län",
        start=local(start) if start else None,
        end=local(end) if end else None,
        certain=certain,
        text=text,
        polygons=(),
    )


class TestFacts(unittest.TestCase):
    def test_wholeBlock(self):
        d = day_weather(
            part(temp=(-1.4, 0.6), feels=-6.0, sky=Sky.CLEAR, rain=precip(
                PrecipKind.SNOW, Intensity.LIGHT, likely=False, mm=0.4), wind=Wind.FRESH,
                gust=15.0),
            part("förmiddag", (9, 12), temp=(1.0, 3.0), sky=Sky.HALFCLEAR),
            part("eftermiddag", (12, 18), temp=(3.0, 4.4), sky=Sky.VARIABLE, fog=False),
            part("kväll", (18, 22), temp=(0.0, 2.0), sky=Sky.CLEAR, fog=True),
            precip_until=local("2026-10-12 09:00"),
            slippery=True,
            temp_change=-5,
        )
        self.assertEqual(
            "Väder idag, måndag 12 oktober:\n"
            "- Morgon, klockan 6-9: Minus 1 till 1 grader, känns som minus 6 grader i "
            "vinden. Sol, risk för lätt snöfall. Frisk vind, byar upp till 15 m/s.\n"
            "- Förmiddag, klockan 9-12: 1 till 3 grader. Sol och moln, uppehåll.\n"
            "- Eftermiddag, klockan 12-18: 3 till 4 grader. Växlande sol och moln, uppehåll.\n"
            "- Kväll, klockan 18-22: 0 till 2 grader. Klart, dimma, uppehåll.\n"
            "- Risk för lätt snöfall fram till ungefär klockan 9.\n"
            "- Lägst minus 1 och högst 4 grader.\n"
            "- Risk för halka.\n"
            "- 5 grader kallare än igår.\n"
            "- Solen går upp 07:19 och ner 17:49.",
            facts_sv([d]),
        )

    def test_noDays_isEmpty(self):
        self.assertEqual("", facts_sv([], [alert()]))

    def test_daylightSky(self):
        # December: the middle of the morning (07:30) is before sunrise
        dark, light = part(sky=Sky.CLEAR), part("förmiddag", (9, 12), sky=Sky.CLEAR)
        text = facts_sv([day_weather(dark, light, sun=("08:43", "14:48"))])
        self.assertIn("Morgon, klockan 6-9: 8 grader. Klart.", text)
        self.assertIn("Förmiddag, klockan 9-12: 8 grader. Sol.", text)

    def test_precipitationPhrases(self):
        cases = [
            (precip(), "regn"),
            (precip(intensity=Intensity.HEAVY, showers=True), "kraftiga regnskurar"),
            (precip(PrecipKind.SNOW, Intensity.HEAVY, showers=True), "kraftiga snöbyar"),
            (precip(PrecipKind.SLEET, Intensity.LIGHT, showers=True),
             "lätta skurar av snöblandat regn"),
            (precip(PrecipKind.DRIZZLE, Intensity.LIGHT), "duggregn"),
            (precip(PrecipKind.FREEZING_RAIN, showers=True), "underkylt regn"),
            (precip(PrecipKind.HAIL, likely=False), "risk för hagel"),
        ]
        for rain, phrase in cases:
            with self.subTest(phrase=phrase):
                text = facts_sv([day_weather(part(rain=rain))])
                self.assertIn(f"8 grader. Mulet, {phrase}.", text)

    def test_thunderAndGustWithoutWind(self):
        text = facts_sv([day_weather(part(thunder=True, gust=13.4))])
        self.assertIn("Mulet, risk för åska. Byar upp till 13 m/s.", text)

    def test_timeline(self):
        cases = [
            (dict(precip_from=local("2026-10-12 14:00")), precip(),
             "Regnet börjar ungefär klockan 14."),
            (dict(precip_until=local("2026-10-12 09:00")), precip(PrecipKind.SNOW),
             "Snöfallet slutar ungefär klockan 9."),
            (dict(precip_from=local("2026-10-12 14:00")), precip(likely=False),
             "Risk för regn från ungefär klockan 14."),
            (dict(precip_until=local("2026-10-12 09:00")), precip(PrecipKind.SLEET),
             "Det snöblandade regnet slutar ungefär klockan 9."),
        ]
        for kw, rain, line in cases:
            with self.subTest(line=line):
                text = facts_sv([day_weather(part(rain=rain), part("kväll", (18, 22)), **kw)])
                self.assertIn(f"- {line}\n", text)

    def test_amountAndDry(self):
        wet = facts_sv([day_weather(part(rain=precip(mm=12.6)))])
        self.assertIn("- Totalt ungefär 13 mm nederbörd.", wet)
        dry = facts_sv([day_weather(part(), part("kväll", (18, 22)))])
        self.assertIn("- Uppehåll hela dagen.", dry)
        self.assertNotIn("uppehåll", dry)  # not repeated per part
        self.assertNotIn("Lägst", dry)  # 8 to 8

    def test_eveningAndTomorrow(self):
        tonight = day_weather(part("kväll", (18, 22)), label="ikväll", temp_change=4)
        tomorrow = day_weather(part(day="2026-10-13"), label="imorgon",
                               day=MONDAY + datetime.timedelta(days=1), temp_change=-3)
        text = facts_sv([tonight, tomorrow])
        self.assertIn("Väder ikväll, måndag 12 oktober:\n- Kväll, klockan 18-22", text)
        self.assertIn("- Uppehåll hela kvällen.\n- 4 grader varmare än igår.\n\n", text)
        self.assertNotIn("Solen går ner", text.split("\n\n")[0])  # set before 18
        self.assertIn("Väder imorgon, tisdag 13 oktober:", text)
        self.assertIn("- 3 grader kallare än idag.", text)

    def test_eveningBeforeSunset(self):
        tonight = day_weather(part("eftermiddag", (17, 18)), label="ikväll")
        self.assertIn("- Solen går ner 17:49.", facts_sv([tonight]))

    def test_noSunTimes(self):
        self.assertNotIn("Solen", facts_sv([day_weather(part(), sun=None)]))


class TestWarnings(unittest.TestCase):
    def facts(self, *warnings):
        return facts_sv([day_weather(part())], warnings).split("\n\n")[1]

    def test_lines(self):
        cases = [
            (alert(), "Gul varning: Mycket kraftig vind, från klockan 14 till klockan 20."),
            (alert(Level.ORANGE, end="2026-10-13 00:00"),
             "Orange varning: Mycket kraftig vind, från klockan 14 till tisdag midnatt."),
            (alert(Level.RED, start="2026-10-11 22:00", end=None),
             "Röd varning: Mycket kraftig vind, redan nu tills vidare."),
            (alert(start=None, end="2026-10-30 06:00"),
             "Gul varning: Mycket kraftig vind, redan nu till fredag 30 oktober klockan 6."),
            (alert(certain=False, text="Byar 25 m/s."),
             "Gul varning: Mycket kraftig vind, från klockan 14 till klockan 20. "
             "Osäker. Byar 25 m/s."),
            (alert(Level.MESSAGE, event="Brandrisk"),
             "Meddelande: Brandrisk, från klockan 14 till klockan 20."),
        ]
        for w, line in cases:
            with self.subTest(line=line):
                self.assertEqual(f"Vädervarningar från SMHI:\n- {line}", self.facts(w))


class TestSentence(unittest.TestCase):
    def test_cases(self):
        rain, snow = precip(likely=False, intensity=Intensity.LIGHT), precip(PrecipKind.SNOW)
        cases = [
            (day_weather(part(), part("kväll", (18, 22), temp=(5.0, 6.0))),
             "Idag blir det 5 till 8 grader och uppehåll."),
            (day_weather(part(rain=rain), part("förmiddag", (9, 12)),
                         part("kväll", (18, 22), rain=snow)),
             "Idag blir det 8 grader och snöfall på morgonen och kvällen."),
            (day_weather(part(rain=snow), slippery=True, label="imorgon"),
             "Imorgon blir det 8 grader och snöfall. Det kan bli halt."),
            (day_weather(part(temp=(-3.4, -0.4))),
             "Idag blir det minus 3 till 0 grader och uppehåll."),
        ]
        for d, text in cases:
            with self.subTest(text=text):
                self.assertEqual(text, sentence_sv(d))

    def test_mostSevereWarning(self):
        text = sentence_sv(day_weather(part()), [alert(Level.ORANGE), alert()])
        self.assertTrue(text.endswith(" SMHI har en orange varning för mycket kraftig vind."))


class TestRealSample(unittest.TestCase):
    def test_mondayMorning(self):
        forecast = parse_forecast(json.loads(SAMPLE.read_text(encoding="utf-8")))
        (period,) = periods(local("2026-10-12 06:35"))
        d = summarize(forecast, period, 59.3293, 18.0686, {h: 12.0 for h in range(24)})
        self.assertEqual(
            "Väder idag, måndag 12 oktober:\n"
            "- Morgon, klockan 6-9: 8 grader, känns som 5 grader i vinden. "
            "Mulet, risk för lätt regn. Måttlig vind.\n"
            "- Förmiddag, klockan 9-12: 8 grader, känns som 5 grader i vinden. "
            "Mulet, uppehåll. Måttlig vind.\n"
            "- Eftermiddag, klockan 12-18: 8 till 9 grader. Mulet, uppehåll. Måttlig vind.\n"
            "- Kväll, klockan 18-22: 7 grader. Mulet, uppehåll. Måttlig vind.\n"
            "- Risk för lätt regn fram till ungefär klockan 9.\n"
            "- Lägst 7 och högst 9 grader.\n"
            "- Totalt ungefär 1 mm nederbörd.\n"
            "- 3 grader kallare än igår.\n"
            "- Solen går upp 07:18 och ner 17:49.",
            facts_sv([d]),
        )
        self.assertEqual(
            "Idag blir det 7 till 9 grader och risk för lätt regn på morgonen.",
            sentence_sv(d),
        )


if __name__ == "__main__":
    unittest.main()
