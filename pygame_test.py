"""AudioCtrl"""

import os
import sys
import time
from daemon.audio_ctrl import AudioCtrl, SysAudioEvent
from daemon.audio_effects import EffectType


class AudioCtrlTestMenu:
    """Menu"""

    currentmenu = None

    def rootmenu(self):
        print(
            "1. Start recording\n"
            "2. Stop recording\n"
            "3. Choose effect...\n"
            "4. Assign audio to Btn\n"
            "5. Play SysAudio"
        )
        answer = input("Choose action.'Q' to exit")
        if answer == "1":
            self.app.start_recording()
        elif answer == "2":
            self.app.stop_recording()
        elif answer == "3":
            self.currentmenu = self.effectmenu
        elif answer == "3":
            self.app.save_to_hwswitch(3)
        elif answer == "5":
            self.currentmenu = self.sysAudioMenu
        else:
            sys.exit()

    def __init__(self):
        self.currentmenu = self.rootmenu
        self.app = AudioCtrl()
        self.showmenu()

    def showmenu(self):
        while True:
            # os.system("cls")
            print("")
            print("")
            print("")
            print("==============================")
            self.currentmenu()

    def effectmenu(self):
        for e in EffectType:
            print(f"{e.value}: {e.name}")
        answer = input("Choose EffectType. 'P' to play. 'R' to rootMenu. 'Q' to exit")
        if answer.isdigit():
            print("Applying" + str(EffectType(int(answer))))
            self.app.apply_effect(EffectType(int(answer)))
            time.sleep(0.1)
            while self.app.effects_running:
                print("waiting for effect to finish...")
                time.sleep(0.3)
        elif answer in ["p", "P"]:
            os.system(f"aplay {self.app.current_filepath}")
        elif answer in ["r", "R"]:
            self.currentmenu = self.rootmenu
        elif answer in ["q", "Q"]:
            sys.exit()

    def sysAudioMenu(self):
        for e in SysAudioEvent:
            print(f"{e.value}: {e.name}")
        answer = input("Choose AudioEvent. 'S' to stop. 'Q' to exit")
        if answer.isdigit():
            print("playing" + str(SysAudioEvent(int(answer))))
            self.app.sysaudio_play(SysAudioEvent(int(answer)))
        if answer == "S":
            self.app.stop_all_audio()
        elif answer in ["q", "Q"]:
            sys.exit()


if __name__ == "__main__":
    m = AudioCtrlTestMenu()
