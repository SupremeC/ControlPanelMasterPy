import os
import sys

here = os.path.dirname(__file__)
sys.path.append(os.path.join(here, '..'))

from os import system
import sounddevice as sd
from scipy.io.wavfile import write
from daemon.audio_rec import AudioRec
from time import time, sleep


def display_menu(menu):
    """
    Display a menu where the key identifies the name of a function.
    :param menu: dictionary, key identifies a value which is a function name
    :return:
    """
    print("========================================================")
    for k, function in menu.items():
        print("\t", k, function.__name__)
    print("========================================================")


def record3s_fixedtime():
    print("recording for 3 seconds...")

    fs = 44100  # Sample rate
    seconds = 3  # Duration of recording
    myrecording = sd.rec(int(seconds * fs), samplerate=fs, channels=2)
    sd.wait()  # Wait until recording is finished

    print("recording is finished.") # Simulate function output.
    write('output.wav', fs, myrecording)  # Save as WAV file

    input("Press Enter to Continue\n")
    system('clear')  # clears stdout

def record_overMaxTime():
    ar = AudioRec("test")
    ar.max_rec_time = 8 # seconds
    print("recording over the time limit({}) test".format(ar.max_rec_time))
    ar.set_device(10)
    ar.rec()
    starttime = time()
    while ar.recording:
        print("recording for {} out of {} seconds".format(time() - starttime, ar.max_rec_time))
        sleep(1)
    print("Stopped recording automatically. Thats a good thing")
    ar.stop()
    input("Stopped. Press Enter to Continue\n")
    system('clear')  # clears stdout

def record_variabletime():
    dur = int(input("record for x seconds: "))
    print("dynamic length recording for {} seconds...".format(dur))
    ar = AudioRec()
    ar.set_device(10)
    ar.rec()
    sleep(dur/2)
    print("still sleeping...")
    sleep(dur/2)
    print("stopping...")
    ar.stop()
    input("Stopped. Press Enter to Continue\n")
    system('clear')  # clears stdout

def list_hostapis():
    i = 0
    hosts = []
    for hostapi in sd.query_hostapis():
        print(str(i) + ": " + str(hostapi) + "\n")
        hosts.append(hostapi)
        i = i + 1
    index = input("Select a Hostapi: ")
    update_device_list(int(index))

def update_device_list(hostapi):
    hostapi = sd.query_hostapis(hostapi)
    device_ids = [
        idx
        for idx in hostapi['devices']
        if sd.query_devices(idx)['max_input_channels'] > 0]
    device_list = [
        sd.query_devices(idx)['name'] for idx in device_ids]
    default = hostapi['default_input_device']
    print("device_list:\n")
    for i in range(len(device_ids)):
        print("ID = " + str(device_ids[i]) + ". Name =  " + str(device_list[i]))
    # if default >= 0:
    #    self.device_list.current(self.device_ids.index(default))

def done():
    system('clear')  # clears stdout
    print("Goodbye")
    sys.exit()


def main():
    # Create a menu dictionary where the key is an integer number and the
    # value is a function name.
    system('clear')
    functions_names = [record3s_fixedtime, record_variabletime, record_overMaxTime, list_hostapis, done]
    menu_items = dict(enumerate(functions_names, start=1))

    while True:
        display_menu(menu_items)
        selection = int(
            input("Please enter your selection number: "))  # Get function key
        selected_value = menu_items[selection]  # Gets the function name
        selected_value()  # add parentheses to call the function


if __name__ == "__main__":
    main()
