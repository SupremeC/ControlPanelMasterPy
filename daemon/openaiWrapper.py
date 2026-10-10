import base64
from datetime import datetime
import json
import logging
from pathlib import Path
from openai import OpenAI
from .config import Config
from .personal import Personal, swedish_date


logger = logging.getLogger("daemon.openaiWrapper")

# gpt-4o-audio-preview was retired (404 model_not_found since Sep 2026).
# gpt-audio-1.5 is OpenAI's named successor for the gpt-4o-audio / gpt-audio line.
OPENAI_AUDIO_MODEL = "gpt-audio-1.5"
SPEAK_INSTRUCTIONS = "Tala svenska, lugnt och vänligt."


class OpenAiWrapper:
    """
    Open AI (chat GPT)
    - account: myOwnEmail

    The texts the panel speaks are made in daemon/speech.py; this class
    only talks to OpenAI: a JSON text call, text-to-speech, and the spoken
    answer to a recorded question.

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
        config: Config | None = None,
    ):
        self._key_path = key_path
        self._personal_path = personal_path
        self._cfg = config or Config()
        self._client: OpenAI | None = None
        self.audio: bytes = None

    @property
    def client(self) -> OpenAI:
        """OpenAI client, created on first use."""
        if self._client is None:
            self._client = OpenAI(api_key=self._key_path.read_text().strip())
        return self._client

    def chat_json(self, system: str, user: str, effort: str = "low") -> dict:
        """Asks the text model for a JSON object. Blocking. Raises on
        network errors and on a reply that is not a JSON object."""
        completion = self.client.chat.completions.create(
            model=self._cfg.text_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            reasoning_effort=effort,
        )
        reply = json.loads(completion.choices[0].message.content)
        if not isinstance(reply, dict):
            raise ValueError(f"not a JSON object: {reply!r}")
        return reply

    def speak(
        self, text: str, instructions: str = SPEAK_INSTRUCTIONS, response_format: str = "mp3"
    ) -> bytes:
        """Reads a text aloud (MP3, or "pcm": raw 24 kHz 16-bit mono),
        stores it in self.audio and returns it. Blocking."""
        self.audio = None
        response = self.client.audio.speech.create(
            model=self._cfg.tts_model,
            voice=self._cfg.voice,
            input=text,
            instructions=instructions,
            response_format=response_format,
        )
        self.audio = response.read()
        return self.audio

    def _send_audio_chat(self, audio: str) -> str:
        """Sends a recorded question (base64 wav) and stores the spoken
        answer in self.audio. Blocking."""
        self.audio = None
        completion = self.client.chat.completions.create(
            model=OPENAI_AUDIO_MODEL,
            modalities=["text", "audio"],
            audio={"voice": self._cfg.voice, "format": "mp3"},
            messages=self.build_audio_instr(audio),
        )
        self.audio = base64.b64decode(completion.choices[0].message.audio.data)
        return completion.choices[0].message

    # ---- recorded question ------------------------------------------------

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
