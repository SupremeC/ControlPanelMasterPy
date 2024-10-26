import base64
from datetime import datetime
import logging
from openai import OpenAI
from cevent import CEvent
from smhi import SMHI


logger = logging.getLogger("daemon.openaiWrapper")


class OpenAiWrapper:
    audio: bytes

    def __init__(self):
        self.client = OpenAI()
        self.audio: bytes = None

    def morningBreifing(self, events: list[CEvent]) -> str:
        try:
            weather = SMHI.get_weather_descr()
            arr = OpenAiWrapper.__build_morning_instr(weather, events)
            print(arr)
            print(
                "====================================================================="
            )
            return self._send_chat(arr)
        except Exception as e:
            print(e)
            logger.error(e)
        return ""

    def chat(self, user_message: str) -> str:
        pass

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

    def build_std_instr() -> dict[str, str]:
        return {
            "role": "system",
            "content": """You are a helful assistant. 
                 Answers should be tailored for an 11-year-old child named Axel""",
        }

    def __build_morning_instr(weather: str, events: list[str]) -> dict[str, str]:
        now = datetime.now()
        dayOrdinal = OpenAiWrapper.ordinal(now.day)
        today = now.strftime(f"%A, %B {dayOrdinal}")
        timenow = now.strftime("%H:%M")
        OpenAiWrapper.ordinal(now.day)
        syscontent = {
            "role": "system",
            "content": """Generate a warm and friendly description of: todays date ({dt}), 
         current weather ({wea}), and upcoming events tailored for an 11-year-old child named Axel. 
         The language should be engaging, informative, yet simple enough for a young audience to understand.

        # Steps

        1. Start with a friendly, positive, good morning greeting to Axel.
        2. Describe todays date with a fun fact or something interesting about the day.
        3. Explain the current weather in Stockholm, Sweden, with vivid descriptions that a child might relate to.
        4. Mention all upcoming events, if it is school:mention when it starts. 
        Use excitement and positivity in your tone.
        5. Conclude with an encouraging message or question to engage further.

        the Time right now is {trn}
        # Todays Events
        {ev}

        # Output Format

        The response should be fairly short, around 700 characters.
        Include "..." Between paragraphs to indicate a pause.

        # Notes

        - Use simple language and maintain a cheerful, enthusiastic tone throughout.
        - Include relatable examples or comparisons in the weather description.
        """.format(
                dt=today, wea=weather, ev=events, trn=timenow
            ),
        }
        usercontent = {
            "role": "user",
            "content": "Please write me an answer using your system instructions. Thank you.",
        }
        return [syscontent, usercontent]

    def ordinal(n: int) -> str:
        """derive the ordinal numeral for a given number n"""
        return f"{n:d}{'tsnrhtdd'[(n//10%10!=1)*(n%10<4)*n%10::4]}"


if __name__ == "__main__":
    ai = OpenAiWrapper()
    ai.morningBreifing([])
