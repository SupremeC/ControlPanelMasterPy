import os
import sys
import time
from daemon.gCalender import Calender


class CalenderMenu:
    """Menu"""

    currentmenu = None

    def rootmenu(self):
        print(
            "1. Authenticate (create token)\n"
            "2. Get events from Calender\n"
        )
        answer = input("Choose action.'Q' to exit")
        if answer == "1":
            self.app.refresh_tokens()
        elif answer == "2":
            self.app.get_todays_events()
        else:
            sys.exit()

    def __init__(self):
        self.currentmenu = self.rootmenu
        self.app = Calender(None, None)
        self.showmenu()

    def showmenu(self):
        while True:
            # os.system("cls")
            print("")
            print("")
            print("")
            print("==============================")
            self.currentmenu()


if __name__ == "__main__":
    m = CalenderMenu()
