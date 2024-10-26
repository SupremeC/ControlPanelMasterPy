from openaiWrapper import OpenAiWrapper
from gCalender import Calender


cal = Calender()
ai = OpenAiWrapper()
do_alarm = cal.update()
do_alarm = cal.update()
do_alarm = cal.update()
events = cal.events
print(f"Do_alarm: {do_alarm}")
print(f"Events ({len(events)}): {events}")
print("=====================================")

answer = ai.morningBreifing(cal.events)
print(answer.audio.transcript)

with open("dog.mp3", "wb") as f:
    f.write(ai.audio)
