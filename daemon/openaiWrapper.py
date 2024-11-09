import base64
from datetime import datetime
import logging
from openai import OpenAI
from .cevent import CEvent
from .smhi import SMHI


logger = logging.getLogger("daemon.openaiWrapper")


class OpenAiWrapper:
    """
    Open AI (chat GPT)
    - account: myOwnEmail

    #### private key token:
    - Stored in session variable.
    - Loaded via /etc/profile. see 'sudo nano /etc/profile'
    """

    audio: bytes | None
    """Raw audio data from last call."""

    def __init__(self):
        self.client = OpenAI()
        self.audio: bytes = None

    def morningBreifing(self, events: list[CEvent]) -> str:
        """Calls OpenAI with weather and calender events as input.

        Args:
            events (list[cevent]): Calender events for today
        returns:
            object: Response object from OpenAI. Contains both text and audio data.
        """
        try:
            weather = SMHI.get_weather_descr()
            arr = OpenAiWrapper.__build_morning_instr(weather, events)
            return self._send_chat(arr)
        except Exception as e:
            print(e)
            logger.error(e)
        return ""

    def upcomingEvents(self, events: list[CEvent]) -> str:
        """Calls OpenAI with weather and calender events as input. Slightly
        shorter reponse then `morningBreifing` and the initial greeting is not fixed
        to "Good morning".

        Notes:
            Blocking until complete.

        Args:
            events (list): Calender events for today
        returns:
            object: Response object from OpenAI. Contains both text and audio data.
        """
        try:
            weather = SMHI.get_weather_descr()
            arr = OpenAiWrapper.__build_events_instr(weather, events)
            return self._send_chat(arr)
        except Exception as e:
            print(e)
            logger.error(e)
        return ""

    def _send_audio_chat(self, audio: str) -> str:
        """"""
        self.audio = None
        completion = self.client.chat.completions.create(
            model="gpt-4o-audio-preview",
            modalities=["text", "audio"],
            audio={"voice": "alloy", "format": "mp3"},
            messages=OpenAiWrapper.build_audio_instr(audio),
        )
        self.audio = base64.b64decode(completion.choices[0].message.audio.data)
        return completion.choices[0].message

    def _send_chat(self, convo_arr) -> str:
        self.audio = None
        completion = self.client.chat.completions.create(
            model="gpt-4o-audio-preview",
            modalities=["text", "audio"],
            audio={"voice": "alloy", "format": "mp3"},
            messages=convo_arr,
        )
        self.audio = base64.b64decode(completion.choices[0].message.audio.data)
        return completion.choices[0].message
        # print(completion.choices[0].message)

    @staticmethod
    def build_audio_instr(wav_data: str) -> dict[str, str]:
        now = datetime.now()
        dayOrdinal = OpenAiWrapper.ordinal(now.day)
        today = now.strftime(f"%A, %B {dayOrdinal}")
        timenow = now.strftime("%H:%M")
        sys = {
            "role": "system",
            "content": """You are a positive helful assistant. Todays date is {dt}. Current time is {trn}.
                 Answers should be tailored for an 11-year-old child named Axel""".format(
                dt=today, trn=timenow
            ),
        }
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
        return [sys, audio]

    def __build_events_instr(weather: str, events: list[str]) -> dict[str, str]:
        now = datetime.now()
        timenow = now.strftime("%H:%M")
        OpenAiWrapper.ordinal(now.day)
        syscontent = {
            "role": "system",
            "content": """Generate a positive and friendly greeting to Axel. Include the time which is {trn} right now,
         current weather ({wea}), and upcoming events tailored for an 11-year-old child named Axel.
        # Steps
        1. Start with a friendly, positive, greeting to Axel.
        2. Explain the current weather in Stockholm, Sweden.
        4. Mention all upcoming events, if it is school:mention when it starts.
        Use excitement and positivity in your tone.
        5. Conclude with an encouraging message.

        # Todays Events
        {ev}

        # Output Format

        The response should be fairly short.
        Include "..." Between paragraphs to indicate a pause.
        """.format(
                wea=weather, ev=events, trn=timenow
            ),
        }
        usercontent = {
            "role": "user",
            "content": "Please answer using your system instructions. Thank you.",
        }
        return [syscontent, usercontent]

    def __build_morning_instr(weather: str, events: list[str]) -> dict[str, str]:
        now = datetime.now()
        dayOrdinal = OpenAiWrapper.ordinal(now.day)
        today = now.strftime(f"%A, %B {dayOrdinal}")
        timenow = now.strftime("%H:%M")
        OpenAiWrapper.ordinal(now.day)
        syscontent = {
            "role": "system",
            "content": """Generate a positive and friendly description of: todays date ({dt}),
         current weather ({wea}), and upcoming events tailored for an 11-year-old child named Axel.
        # Steps
        1. Start with a friendly, positive, good morning greeting to Axel.
        2. Describe todays date with a fun fact or something interesting about the day.
        3. Explain the current weather in Stockholm, Sweden.
        4. Mention all upcoming events, if it is school: mention when it starts.
        5. Conclude with an encouraging message or question to engage further.

        the Time right now is {trn}
        # Todays Events
        {ev}

        # Output Format
        The response should be fairly short.
        Include "..." Between paragraphs to indicate a pause.
        """.format(
                dt=today, wea=weather, ev=events, trn=timenow
            ),
        }
        usercontent = {
            "role": "user",
            "content": "Please write me an answer using your system instructions.",
        }
        return [syscontent, usercontent]

    def ordinal(n: int) -> str:
        """derive the ordinal numeral for a given number n"""
        return f"{n:d}{'tsnrhtdd'[(n//10%10!=1)*(n%10<4)*n%10::4]}"


if __name__ == "__main__":
    ai = OpenAiWrapper()
    ai.morningBreifing([])
