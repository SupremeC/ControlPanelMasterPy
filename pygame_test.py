"""AudioCtrl"""

from daemon.audio_ctrl import AudioCtrl, SysAudioEvent


if __name__ == "__main__":
    app = AudioCtrl()
    while True:
        print("==============================")
        for e in SysAudioEvent:
            print(f"{e.value}: {e.name}")
        answer = input("Choose AudioEvent. 'S' to stop. 'Q' to exit")
        if answer.isdigit():
            print("playing" + str(SysAudioEvent(int(answer))))
            app.sysaudio_play(SysAudioEvent(int(answer)))
        if answer == "S":
            app.stop_all_audio()
        elif answer in ["q", "Q"]:
            exit()
        print("==============================")
