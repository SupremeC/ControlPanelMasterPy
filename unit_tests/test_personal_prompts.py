#!/usr/bin/env python
"""personal.json (name, birthday, computed age, bring rules) and the
OpenAI wrapper. No network: the client is a mock.
"""

import datetime
import json
from pathlib import Path
import tempfile
import unittest
import unittest.mock as mock

from daemon.config import Config
from daemon.openaiWrapper import OpenAiWrapper
from daemon.personal import Personal, swedish_date

BIRTHDAY = datetime.date(2014, 6, 30)


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


class TestBring(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "personal.json"

    def load(self, bring) -> Personal:
        self.path.write_text(json.dumps({"name": "Kim", "bring": bring}), encoding="utf-8")
        return Personal.load(self.path)

    def test_weekdayRules_onlyOnSchoolDays(self):
        p = self.load({"weekdays": {"Tisdag": ["gympapåsen"]}})
        tuesday = datetime.date(2026, 10, 13)
        self.assertEqual(["gympapåsen"], p.things_to_bring(tuesday, [], school_day=True))
        self.assertEqual([], p.things_to_bring(tuesday, [], school_day=False))
        self.assertEqual([], p.things_to_bring(tuesday + datetime.timedelta(days=1), [], True))

    def test_keywordRules_matchTitlesAnyCase(self):
        p = self.load({"keywords": {"Scout": "scoutskjortan"}})
        day = datetime.date(2026, 10, 13)
        self.assertEqual(["scoutskjortan"], p.things_to_bring(day, ["SCOUTMÖTE"], False))
        self.assertEqual([], p.things_to_bring(day, ["Fotboll"], False))

    def test_eachThingOnce(self):
        p = self.load({
            "weekdays": {"tisdag": ["gympapåsen"]},
            "keywords": {"idrott": ["gympapåsen", "vattenflaska"]},
        })
        self.assertEqual(
            ["gympapåsen", "vattenflaska"],
            p.things_to_bring(datetime.date(2026, 10, 13), ["Idrottsdag"], True),
        )

    def test_unknownWeekday_isLoggedAndSkipped(self):
        with self.assertLogs("daemon.personal", "ERROR"):
            p = self.load({"weekdays": {"tisdagar": ["x"], "onsdag": ["y"]}})
        self.assertEqual(["y"], p.things_to_bring(datetime.date(2026, 10, 14), [], True))

    def test_brokenRules_areIgnored_restWorks(self):
        with self.assertLogs("daemon.personal", "ERROR"):
            p = self.load(["gympapåsen"])
        self.assertEqual("Kim", p.name)
        self.assertEqual([], p.things_to_bring(datetime.date(2026, 10, 13), [], True))

    def test_exampleFile_hasRules(self):
        example = Path(__file__).resolve().parent.parent / "daemon" / "personal.example.json"
        p = Personal.load(example)
        self.assertEqual(
            ["gympapåsen", "scoutskjortan"],
            p.things_to_bring(datetime.date(2026, 10, 13), ["Scoutmöte"], True),
        )


class TestOpenAiWrapper(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "personal.json"
        path.write_text(json.dumps({"name": "Kim", "birthday": "2014-06-30"}))
        self.ai = OpenAiWrapper(
            key_path=Path("/nonexistent"), personal_path=path, config=Config(voice="marin")
        )
        self.ai._client = mock.MagicMock()

    def test_recordedQuestion_swedishSystemThenAudio(self):
        system, user = self.ai.build_audio_instr("d2F2")
        self.assertIn("svenska", system["content"])
        age = Personal("Kim", BIRTHDAY).age(datetime.date.today())
        self.assertIn(f"Du pratar med Kim, {age} år,", system["content"])
        self.assertEqual("input_audio", user["content"][0]["type"])

    def test_speak_usesTtsWithTheConfiguredVoice(self):
        # arrange
        self.ai._client.audio.speech.create.return_value.read.return_value = b"mp3"

        # act
        audio = self.ai.speak("Hej", "Tala lugnt.")

        # assert
        self.assertEqual(b"mp3", audio)
        self.assertEqual(b"mp3", self.ai.audio)
        kwargs = self.ai._client.audio.speech.create.call_args.kwargs
        self.assertEqual("Hej", kwargs["input"])
        self.assertEqual("marin", kwargs["voice"])
        self.assertEqual("Tala lugnt.", kwargs["instructions"])
        self.assertEqual("mp3", kwargs["response_format"])

    def test_chatJson_parsesTheObject(self):
        # arrange
        create = self.ai._client.chat.completions.create
        create.return_value.choices[0].message.content = '{"skamt": "Hej"}'

        # act
        reply = self.ai.chat_json("system", "user", "medium")

        # assert
        self.assertEqual({"skamt": "Hej"}, reply)
        kwargs = create.call_args.kwargs
        self.assertEqual({"type": "json_object"}, kwargs["response_format"])
        self.assertEqual("medium", kwargs["reasoning_effort"])

    def test_chatJson_notAnObject_raises(self):
        create = self.ai._client.chat.completions.create
        create.return_value.choices[0].message.content = '["Hej"]'
        with self.assertRaises(ValueError):
            self.ai.chat_json("system", "user")

if __name__ == "__main__":
    unittest.main()
