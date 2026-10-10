#!/usr/bin/env python
"""daemon/speech.py: Swedish templates, the checked text-model reply and
the speech cache. The OpenAI wrapper is a mock."""

import dataclasses
import datetime
import json
from pathlib import Path
import tempfile
import unittest
import unittest.mock as mock

from daemon.cevent import CEvent
from daemon.config import Config
from daemon.gCalender import TIMEZONE
from daemon.speech import (
    Speech,
    clock_sv,
    countdown_text,
    join_sv,
    looks_swedish,
    school_event,
    spoken,
)


def at(text: str) -> datetime.datetime:
    return TIMEZONE.localize(datetime.datetime.strptime(text, "%Y-%m-%d %H:%M"))


def timed(summary: str, start: str, end: str) -> CEvent:
    return CEvent(at(start), summary, "", None, False, True, at(end))


class TestWords(unittest.TestCase):
    def test_clock(self):
        cases = {
            "09:00": "nio", "09:10": "tio över nio", "09:15": "kvart över nio",
            "08:25": "fem i halv nio", "18:30": "halv sju", "08:35": "fem över halv nio",
            "08:45": "kvart i nio", "12:55": "fem i ett", "00:00": "tolv",
            "13:00": "ett", "09:17": "9.17",
        }
        for text, words in cases.items():
            with self.subTest(text=text):
                t = datetime.datetime.strptime(text, "%H:%M")
                self.assertEqual(words, clock_sv(t))

    def test_join(self):
        self.assertEqual("", join_sv([]))
        self.assertEqual("a", join_sv(["a"]))
        self.assertEqual("a och b", join_sv(["a", "b"]))
        self.assertEqual("a, b och c", join_sv(["a", "b", "c"]))

    def test_looksSwedish(self):
        self.assertTrue(looks_swedish("Frukosten väntar på dig."))
        self.assertTrue(looks_swedish("långbyxor och tjocktröja"))
        self.assertFalse(looks_swedish("El desayuno te espera y es para ti."))
        self.assertFalse(looks_swedish("The breakfast is waiting for you."))

    def test_spoken_dashIsAPause(self):
        cases = {
            "Vad kallar man en alligator som ätit en GPS? – Navigator.":
                "Vad kallar man en alligator som ätit en GPS?... Navigator.",
            "Vilka är alltid aktiva i skogen?– Träna.": "Vilka är alltid aktiva i skogen?... Träna.",
            "Kläderna på – t-shirt – sen frukost.": "Kläderna på... t-shirt... sen frukost.",
            "I vilket land är man aldrig tyst? - I-tal-igen.":
                "I vilket land är man aldrig tyst?... I-tal-igen.",
            "Sov-jet!": "Sov-jet!",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(want, spoken(text))

    def test_countdown(self):
        self.assertEqual("15 minuter kvar.", countdown_text(15))
        self.assertEqual("Dags att gå. Ha en bra dag!", countdown_text(0))
        self.assertEqual("20 minuter kvar.", countdown_text(20))

    def test_schoolEvent_firstTimedWithTheTitle(self):
        events = [
            timed("Skola, utflykt", "2026-10-12 10:00", "2026-10-12 14:00"),
            timed("skola", "2026-10-12 09:10", "2026-10-12 15:00"),
            timed("Skolavslutning", "2026-10-13 08:00", "2026-10-13 09:00"),
            timed("Scout", "2026-10-12 08:00", "2026-10-12 09:00"),
        ]
        found = school_event(events, datetime.date(2026, 10, 12), "Skola")
        self.assertEqual(at("2026-10-12 09:10"), found.start)
        self.assertIsNone(school_event(events, datetime.date(2026, 10, 14), "Skola"))


class SpeechTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        personal = self.dir / "personal.json"
        personal.write_text(json.dumps({
            "name": "Kim",
            "birthday": "2014-06-30",
            "bring": {"weekdays": {"tisdag": ["gympapåsen"]},
                      "keywords": {"scout": ["scoutskjortan"]}},
        }), encoding="utf-8")
        self.cfg = Config(
            personal_file=personal,
            speech_cache_dir=self.dir / "cache",
            jokes_file=self.dir / "jokes.json",
            joke_state_file=self.dir / "joke_state.json",
        )
        self.ai = mock.Mock()
        self.speech = Speech(self.ai, self.cfg)


class TestWakeLine(SpeechTestCase):
    def test_jokeAndClothes(self):
        # arrange
        self.ai.chat_json.return_value = {
            "skamt": "Kudden har begärt semester", "klader_kort": "Långbyxor och tröja"
        }

        # act
        text = self.speech.wake_text(at("2026-10-13 06:45"), "Väder idag", school_day=True)

        # assert
        self.assertEqual(
            "God morgon, Kim. Tisdag. Kudden har begärt semester. "
            "Kläderna på – långbyxor och tröja – sen frukost.",
            text,
        )
        system, user, effort = self.ai.chat_json.call_args.args
        self.assertIn("Kim, 12 år som bor i Stockholm", system)
        self.assertIn("svenska", system)
        self.assertIn("tisdag 13 oktober, skoldag", user)
        self.assertIn("Väder:\nVäder idag", user)
        self.assertEqual("medium", effort)

    def test_noWeather_noClothesHint(self):
        self.ai.chat_json.return_value = {"skamt": "Nu kör vi", "klader_kort": "t-shirt"}
        text = self.speech.wake_text(at("2026-10-13 06:45"))
        self.assertTrue(text.endswith("Nu kör vi. Kläderna på, sen frukost."))
        self.assertIn("Väder: saknas.", self.ai.chat_json.call_args.args[1])

    def test_modelFails_templateWithoutJoke(self):
        # arrange
        self.ai.chat_json.side_effect = RuntimeError("no network")

        # act
        with self.assertLogs("daemon.speech", "WARNING"):
            text = self.speech.wake_text(at("2026-10-13 06:45"), "Väder")

        # assert: two tries
        self.assertEqual("God morgon, Kim. Tisdag. Kläderna på, sen frukost.", text)
        self.assertEqual(2, self.ai.chat_json.call_count)

    def test_foreignReply_isRejectedThenRetried(self):
        # arrange
        self.ai.chat_json.side_effect = [
            {"skamt": "El desayuno te espera y es para ti", "klader_kort": ""},
            {"skamt": "Frukosten väntar på dig", "klader_kort": ""},
        ]

        # act
        with self.assertLogs("daemon.speech", "WARNING"):
            text = self.speech.wake_text(at("2026-10-13 06:45"))

        # assert
        self.assertIn("Frukosten väntar på dig.", text)

    def test_tooLongJoke_isRejected(self):
        self.ai.chat_json.return_value = {"skamt": "och " * 50, "klader_kort": ""}
        with self.assertLogs("daemon.speech", "WARNING"):
            text = self.speech.wake_text(at("2026-10-13 06:45"))
        self.assertEqual("God morgon, Kim. Tisdag. Kläderna på, sen frukost.", text)

    def test_recentJokes_areNotRepeated(self):
        self.ai.chat_json.return_value = {"skamt": "Sängen har gjort sitt", "klader_kort": ""}
        self.speech.wake_text(at("2026-10-13 06:45"))
        self.speech.wake_text(at("2026-10-14 06:45"))
        self.assertIn("Sängen har gjort sitt", self.ai.chat_json.call_args.args[1])


class TestWakeLineFromPool(SpeechTestCase):
    def test_poolJoke_inItsOwnStyle_modelOnlyForClothes(self):
        # arrange
        (self.dir / "jokes.json").write_text(json.dumps([
            {"id": "j1", "style": "naturfilm", "tags": [], "text": "Här ser vi tonåringen i sitt bo"},
        ]), encoding="utf-8")
        self.ai.chat_json.return_value = {"klader_kort": "långbyxor och tröja"}

        # act
        text, voice = self.speech.wake_line(at("2026-10-13 06:45"), "Väder idag")

        # assert
        self.assertEqual(
            "God morgon, Kim. Tisdag. Här ser vi tonåringen i sitt bo. "
            "Kläderna på – långbyxor och tröja – sen frukost.",
            text,
        )
        self.assertIn("naturfilmsberättare", voice)
        user = self.ai.chat_json.call_args.args[1]
        self.assertNotIn("skamt", user)
        self.assertIn("klader_kort", user)

    def test_poolJoke_noWeather_noModelCall(self):
        (self.dir / "jokes.json").write_text(json.dumps([
            {"id": "j1", "style": "torr", "tags": [], "text": "Sängen har gjort sitt."},
        ]), encoding="utf-8")
        text, _ = self.speech.wake_line(at("2026-10-13 06:45"))
        self.assertIn("Sängen har gjort sitt. Kläderna på, sen frukost.", text)
        self.ai.chat_json.assert_not_called()

    def test_noPool_modelWritesTheJoke(self):
        self.ai.chat_json.return_value = {"skamt": "Frukosten väntar på dig", "klader_kort": ""}
        with self.assertLogs("daemon.jokes", "INFO"):
            text, voice = self.speech.wake_line(at("2026-10-13 06:45"))
        self.assertIn("Frukosten väntar på dig.", text)
        self.assertIn("Torr", voice)


class TestOverview(SpeechTestCase):
    def test_full(self):
        # arrange
        self.ai.chat_json.return_value = {"klader": "Ta regnjackan, det regnar på eftermiddagen"}
        events = [
            timed("Skola", "2026-10-13 09:10", "2026-10-13 15:00"),
            timed("Scoutmöte", "2026-10-13 18:00", "2026-10-13 19:30"),
        ]

        # act
        text = self.speech.overview_text(
            at("2026-10-13 08:25"), events, at("2026-10-13 09:10"), 30, "Väder", "Mening."
        )

        # assert: school not repeated as an activity
        self.assertEqual(
            "30 minuter tills du går. Skolan börjar klockan tio över nio. "
            "Ta med gympapåsen och scoutskjortan. Idag: Scoutmöte klockan sex. "
            "Ta regnjackan, det regnar på eftermiddagen.",
            text,
        )
        self.assertEqual("low", self.ai.chat_json.call_args.args[2])

    def test_noModel_weatherSentence(self):
        self.ai.chat_json.side_effect = RuntimeError("no network")
        with self.assertLogs("daemon.speech", "WARNING"):
            text = self.speech.overview_text(
                at("2026-10-14 08:25"), [], at("2026-10-14 09:10"), 30,
                "Väder", "Idag blir det 7 grader."
            )
        self.assertEqual(
            "30 minuter tills du går. Skolan börjar klockan tio över nio. "
            "Idag blir det 7 grader.",
            text,
        )

    def test_longEvents_onFirstDay(self):
        lov = CEvent(at("2026-10-12 00:00"), "Läger", "", None, False, False,
                     at("2026-10-15 00:00"))
        text = self.speech.overview_text(at("2026-10-12 08:25"), [lov], at("2026-10-12 09:10"), 30)
        self.assertIn("Idag: Läger börjar, till och med onsdag.", text)
        self.ai.chat_json.assert_not_called()  # no weather facts


class TestStatus(SpeechTestCase):
    def test_beforeLeaving(self):
        events = [
            timed("Skola", "2026-10-13 09:10", "2026-10-13 15:00"),
            timed("Bouldering", "2026-10-13 07:00", "2026-10-13 07:30"),
        ]
        text = self.speech.status_text(
            at("2026-10-13 08:20"), events, at("2026-10-13 08:55"), "", "Mulet."
        )
        self.assertEqual(
            "Klockan är tjugo över åtta. 35 minuter tills du går. "
            "Idag: Skola klockan tio över nio. Mulet.",
            text,
        )

    def test_nothingLeft(self):
        text = self.speech.status_text(at("2026-10-13 20:00"), [], at("2026-10-13 08:55"))
        self.assertEqual("Klockan är åtta. Inget mer i kalendern idag.", text)


class TestCache(SpeechTestCase):
    def test_synthesisedOnce(self):
        # arrange
        self.ai.speak.return_value = b"mp3"

        # act
        first = self.speech.cached("15 minuter kvar.")
        second = Speech(self.ai, self.cfg).cached("15 minuter kvar.")

        # assert
        self.assertEqual(b"mp3", first)
        self.assertEqual(b"mp3", second)
        self.ai.speak.assert_called_once()

    def test_otherVoice_isAnotherFile(self):
        self.ai.speak.return_value = b"mp3"
        self.speech.cached("Hej.")
        other = dataclasses.replace(self.cfg, voice="marin")
        Speech(self.ai, other).cached("Hej.")
        self.assertEqual(2, self.ai.speak.call_count)


if __name__ == "__main__":
    unittest.main()
