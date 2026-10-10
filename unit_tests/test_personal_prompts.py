#!/usr/bin/env python
"""personal.json (name, birthday, computed age) and the Swedish prompts
built from it. No network: the prompts are only built, never sent.
"""

import datetime
import json
from pathlib import Path
import tempfile
import unittest
import unittest.mock as mock

from daemon.cevent import CEvent
from daemon.openaiWrapper import OpenAiWrapper
from daemon.personal import Personal, swedish_date

BIRTHDAY = datetime.date(2014, 6, 30)


def event(summary: str, start: datetime.datetime | None = None, **kw) -> CEvent:
    return CEvent(
        start=start or datetime.datetime(2026, 10, 12),
        summary=summary,
        descr="",
        location=kw.get("location"),
        is_alarm=False,
        has_time=start is not None,
    )


class TestPersonal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "personal.json"

    def test_age_turnsOnTheBirthday(self):
        p = Personal("Kim", BIRTHDAY)
        self.assertEqual(11, p.age(datetime.date(2026, 6, 29)))
        self.assertEqual(12, p.age(datetime.date(2026, 6, 30)))

    def test_describe(self):
        today = datetime.date(2026, 10, 12)
        self.assertEqual("Kim, 12 år,", Personal("Kim", BIRTHDAY).describe(today))
        self.assertEqual("ett barn", Personal().describe(today))

    def test_load(self):
        # arrange
        self.path.write_text(json.dumps({"name": " Kim ", "birthday": "2014-06-30"}))

        # act / assert
        self.assertEqual(Personal("Kim", BIRTHDAY), Personal.load(self.path))

    def test_load_missingFile_isLoggedAndAnonymous(self):
        with self.assertLogs("daemon.personal", "WARNING"):
            self.assertEqual(Personal(), Personal.load(self.path))

    def test_load_badBirthday_isLoggedAndAnonymous(self):
        # arrange
        self.path.write_text(json.dumps({"name": "Kim", "birthday": "30/6"}))

        # act / assert
        with self.assertLogs("daemon.personal", "ERROR"):
            self.assertEqual(Personal(), Personal.load(self.path))

    def test_exampleFileLoads(self):
        example = Path(__file__).resolve().parent.parent / "daemon" / "personal.example.json"
        self.assertTrue(Personal.load(example).birthday)
        self.assertEqual((59.3293, 18.0686), Personal.load(example).location)

    def test_load_location(self):
        self.path.write_text(json.dumps({"location": {"lat": "59.4", "lon": 17.9}}))
        self.assertEqual((59.4, 17.9), Personal.load(self.path).location)

    def test_load_badLocation_isLoggedAndIgnored(self):
        for location in ({"lat": 59.4}, [59.4, 17.9], {"lat": 95, "lon": 17.9}):
            with self.subTest(location=location):
                # arrange
                data = {"name": "Kim", "birthday": "2014-06-30", "location": location}
                self.path.write_text(json.dumps(data))

                # act / assert: name and age survive
                with self.assertLogs("daemon.personal", "ERROR"):
                    self.assertEqual(Personal("Kim", BIRTHDAY), Personal.load(self.path))

    def test_swedishDate(self):
        self.assertEqual("måndag 12 oktober", swedish_date(datetime.date(2026, 10, 12)))


class PromptTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "personal.json"
        path.write_text(json.dumps({"name": "Kim", "birthday": "2014-06-30"}))
        self.ai = OpenAiWrapper(key_path=Path("/nonexistent"), personal_path=path)
        self.events = [
            event("Skola", datetime.datetime(2026, 10, 12, 8, 10), location="Skolan"),
            event("Studiedag"),
        ]


class TestPrompts(PromptTestCase):
    def test_morning_requestIsInTheUserMessage(self):
        # act
        system, user = self.ai._morning_instr("Weather today is cloudy", self.events)

        # assert: the old wording made gpt-audio-1.5 refuse (#16)
        self.assertNotIn("system instructions", user["content"])
        self.assertIn("morgonbesked", user["content"])
        self.assertIn("- 08:10: Skola (Skolan)", user["content"])
        self.assertIn("- hela dagen: Studiedag", user["content"])
        self.assertIn("Weather today is cloudy", user["content"])

    def test_system_isSwedishWithNameAndComputedAge(self):
        # act
        system, _ = self.ai._morning_instr("", [])

        # assert
        age = Personal("Kim", BIRTHDAY).age(datetime.date.today())
        self.assertIn(f"Du pratar med Kim, {age} år, som bor i Stockholm", system["content"])
        self.assertIn("Svara alltid på svenska", system["content"])

    def test_noWeather_isNotMentioned(self):
        _, user = self.ai._morning_instr("", [])
        self.assertNotIn("väder", user["content"].lower())
        self.assertIn("4. Avsluta med något uppmuntrande.", user["content"])
        self.assertIn("- inga", user["content"])

    def test_weather_isAStepWithClothes(self):
        _, user = self.ai._morning_instr("Väder idag, måndag 12 oktober:\n- Morgon", [])
        self.assertIn(
            "3. Berätta kort om vädret och vad det betyder för vilka kläder jag ska ha.",
            user["content"],
        )
        self.assertIn("\n\nVäder idag, måndag 12 oktober:\n- Morgon\n\nDagens händelser:",
                      user["content"])
        self.assertNotIn("engelska", user["content"])

    def test_events_requestIsInTheUserMessage(self):
        _, user = self.ai._events_instr("", self.events)
        self.assertIn("Vad händer idag?", user["content"])
        self.assertNotIn("vädret", user["content"])

    def test_events_withWeather(self):
        _, user = self.ai._events_instr("Väder ikväll", self.events)
        self.assertIn("berätta kort om vädret och vad det betyder för kläderna, ",
                      user["content"])
        self.assertIn("Väder ikväll\n\nDagens händelser:", user["content"])

    def test_recordedQuestion_swedishSystemThenAudio(self):
        system, user = self.ai.build_audio_instr("d2F2")
        self.assertIn("svenska", system["content"])
        self.assertEqual("input_audio", user["content"][0]["type"])


class TestFallback(PromptTestCase):
    def test_greetsTimeAndFirstTimedEvent(self):
        text = self.ai.fallback_briefing(self.events)
        self.assertTrue(text.startswith("God morgon Kim! Klockan är "))
        self.assertIn("Idag börjar det med Skola klockan 08:10.", text)

    def test_noEvents(self):
        self.assertIn("Jag hittar inget i kalendern idag.", self.ai.fallback_briefing([]))

    def test_weatherSentenceAfterTheTime(self):
        text = self.ai.fallback_briefing(self.events, "Idag blir det 7 grader.")
        self.assertRegex(text, r"Klockan är \d\d:\d\d\. Idag blir det 7 grader\. Idag börjar")

    def test_speak_usesTtsAndStoresAudio(self):
        # arrange
        client = mock.Mock()
        client.audio.speech.create.return_value.read.return_value = b"mp3"
        self.ai._client = client

        # act
        audio = self.ai.speak("Hej")

        # assert
        self.assertEqual(b"mp3", audio)
        self.assertEqual(b"mp3", self.ai.audio)
        kwargs = client.audio.speech.create.call_args.kwargs
        self.assertEqual("Hej", kwargs["input"])
        self.assertEqual("mp3", kwargs["response_format"])


if __name__ == "__main__":
    unittest.main()
