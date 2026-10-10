import base64
from datetime import datetime
import logging
from pathlib import Path
from openai import OpenAI
from .cevent import CEvent
from .config import Config
from .personal import Personal, swedish_date


logger = logging.getLogger("daemon.openaiWrapper")

# gpt-4o-audio-preview was retired (404 model_not_found since Sep 2026).
# gpt-audio-1.5 is OpenAI's named successor for the gpt-4o-audio / gpt-audio line.
OPENAI_AUDIO_MODEL = "gpt-audio-1.5"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"  # reads a fixed text aloud (fallback)
VOICE = "alloy"


class OpenAiWrapper:
    """
    Open AI (chat GPT)
    - account: myOwnEmail

    #### private key token:
    - Read from daemon/cpanel-openai-service-account.secretkey (gitignored)
      on first use, not in the constructor
    """

    audio: bytes | None
    """Raw audio data from last call."""

    def __init__(
        self,
        key_path: Path = Config.openai_key_file,
        personal_path: Path = Config.personal_file,
    ):
        self._key_path = key_path
        self._personal_path = personal_path
        self._client: OpenAI | None = None
        self.audio: bytes = None

    @property
    def client(self) -> OpenAI:
        """OpenAI client, created on first use."""
        if self._client is None:
            self._client = OpenAI(api_key=self._key_path.read_text().strip())
        return self._client

    def morningBreifing(self, events: list[CEvent], weather: str = "") -> str:
        """Calls OpenAI with weather and calender events as input.

        Args:
            events (list[cevent]): Calender events for today
            weather: weather facts, empty when there are none
        returns:
            object: Response object from OpenAI. Contains both text and audio data.
        """
        message = self._send_chat(self._morning_instr(weather, events))
        logger.info("Briefing: %s", message.audio.transcript)
        return message

    def upcomingEvents(self, events: list[CEvent], weather: str = "") -> str:
        """Calls OpenAI with weather and calender events as input. Slightly
        shorter reponse then `morningBreifing` and the initial greeting is not fixed
        to "Good morning".

        Notes:
            Blocking until complete.

        Args:
            events (list): Calender events for today
            weather: weather facts, empty when there are none
        returns:
            object: Response object from OpenAI. Contains both text and audio data.
        """
        return self._send_chat(self._events_instr(weather, events))

    def _send_audio_chat(self, audio: str) -> str:
        """Sends a recorded question (base64 wav) and stores the spoken
        answer in self.audio. Blocking."""
        self.audio = None
        completion = self.client.chat.completions.create(
            model=OPENAI_AUDIO_MODEL,
            modalities=["text", "audio"],
            audio={"voice": VOICE, "format": "mp3"},
            messages=self.build_audio_instr(audio),
        )
        self.audio = base64.b64decode(completion.choices[0].message.audio.data)
        return completion.choices[0].message

    def _send_chat(self, convo_arr) -> str:
        self.audio = None
        completion = None
        completion = self.client.chat.completions.create(
            model=OPENAI_AUDIO_MODEL,
            modalities=["text", "audio"],
            audio={"voice": VOICE, "format": "mp3"},
            messages=convo_arr,
        )
        self.audio = base64.b64decode(completion.choices[0].message.audio.data)
        logger.debug("Received %d bytes of audio", len(self.audio))
        return completion.choices[0].message
        # print(completion.choices[0].message)

    def speak(self, text: str) -> bytes:
        """Reads a fixed text aloud in Swedish (MP3), stores it in
        self.audio and returns it. Blocking."""
        self.audio = None
        response = self.client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=VOICE,
            input=text,
            instructions="Tala svenska, lugnt och vänligt.",
            response_format="mp3",
        )
        self.audio = response.read()
        return self.audio

    def fallback_briefing(self, events: list[CEvent], weather: str = "") -> str:
        """A short Swedish morning text made without the AI: greeting,
        time, the weather sentence and the first event of the day."""
        now = datetime.now()
        name = self._personal().name
        text = f"God morgon{' ' + name if name else ''}! Klockan är {now:%H:%M}."
        if weather:
            text += f" {weather}"
        timed = [e for e in events if e.has_time]
        if timed:
            first = min(timed, key=lambda e: e.start)
            text += f" Idag börjar det med {first.summary} klockan {first.start:%H:%M}."
        elif events:
            text += f" Idag är det {events[0].summary}."
        else:
            text += " Jag hittar inget i kalendern idag."
        return text

    # ---- prompts ----------------------------------------------------------
    # The request goes in the user message. A user message that only says
    # "use your system instructions" makes gpt-audio-1.5 refuse (#16).

    def _personal(self) -> Personal:
        return Personal.load(self._personal_path)

    def _system(self, extra: str = "") -> dict[str, str]:
        now = datetime.now()
        listener = self._personal().describe(now.date())
        content = (
            f"Du är en vänlig röstassistent. Du pratar med {listener} "
            "som bor i Stockholm. Svara alltid på svenska, även om du får "
            "en fråga på ett annat språk. Använd enkla ord och korta meningar. "
            f"Idag är det {swedish_date(now.date())} och klockan är {now:%H:%M}."
        )
        return {"role": "system", "content": f"{content} {extra}".strip()}

    @staticmethod
    def _facts(weather: str, events: list[CEvent]) -> str:
        lines = []
        for e in events:
            when = f"{e.start:%H:%M}" if e.has_time else "hela dagen"
            where = f" ({e.location})" if e.location else ""
            lines.append(f"- {when}: {e.summary}{where}")
        facts = "Dagens händelser:\n" + ("\n".join(lines) or "- inga")
        if weather:
            facts = f"{weather}\n\n{facts}"
        return facts

    def build_audio_instr(self, wav_data: str) -> list[dict]:
        audio = {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": wav_data,
                        "format": "wav",
                    },
                }
            ],
        }
        return [self._system("Svara kort."), audio]

    def _morning_instr(self, weather: str, events: list[CEvent]) -> list[dict]:
        steps = [
            "Säg god morgon till mig.",
            "Säg vilken dag det är.",
            "Berätta kort om vädret och vad det betyder för vilka kläder "
            "jag ska ha." if weather else None,
            "Berätta om dagens händelser i tidsordning. "
            "Är det skola: säg när den börjar.",
            "Avsluta med något uppmuntrande.",
        ]
        numbered = [f"{i}. {t}" for i, t in enumerate(filter(None, steps), 1)]
        request = (
            "God morgon! Ge mig dagens morgonbesked. Högst fem korta meningar, "
            "i den här ordningen:\n" + "\n".join(numbered) + "\n"
            "Hitta inte på något som inte står nedan.\n\n"
            + self._facts(weather, events)
        )
        return [self._system(), {"role": "user", "content": request}]

    def _events_instr(self, weather: str, events: list[CEvent]) -> list[dict]:
        weather_part = (
            "berätta kort om vädret och vad det betyder för kläderna, "
            if weather
            else ""
        )
        request = (
            "Vad händer idag? Svara kort: säg vad klockan är, "
            f"{weather_part}berätta om dagens händelser som inte har varit än, "
            "i tidsordning. Hitta inte på något som inte står nedan.\n\n"
            + self._facts(weather, events)
        )
        return [self._system(), {"role": "user", "content": request}]


if __name__ == "__main__":
    ai = OpenAiWrapper()
    ai.morningBreifing([])
