import serial
import json
import time
from typing import Dict, Any

# Replace '/dev/serial0' with the correct UART1 device if different
UART_PORT = "/dev/serial0"
BAUD_RATE = 460800  # Set the baud rate to match the ESP32

# Open the serial port
ser = serial.Serial(UART_PORT, BAUD_RATE, timeout=1)


# Function to send a JSON message to the ESP32
def send_json_message(data)->None:
    try:
        # Convert Python dictionary to JSON string
        json_data = json.dumps(data)
        # Send JSON string over serial to the ESP32
        ser.write((json_data + "\n").encode())
        #print(f"Sent: {json_data}")
    except Exception as e:
        print(f"Error sending JSON: {e}")


def read_whole_json_message()-> Dict[str, Any]:
    start_time = time.time()
    received_data = ""
    while True:
        current_time = time.time()  # Get the current time
        elapsed_time = current_time - start_time  # Calculate elapsed time
        received_data = read_json_message()
        if elapsed_time > 1.5 or received_data:
            # Handle received data
            break
    return received_data


def read_json_message()-> Dict[str, Any]:
    try:
        # Read data from the ESP32
        if ser.in_waiting > 0:
            message = ser.readline().decode('utf-8').strip()
            # Parse the message as JSON
            json_data = json.loads(message)
            #json_string = json.dumps(json_data, indent=4)
            #print(f"Received: {json_string}")
            return json_data
    except json.JSONDecodeError:
        print("Received non-JSON data.")
    except Exception as e:
        print(f"Error reading JSON: {e}")
    return None

def main_menu():
    print("===============")
    print("1: Toggle ON/OFF state")
    print("2: Loop state X times")
    print("3: Read full state")
    print("4: Previous effect")
    print("5: Next effect")
    print("6: Loop Red")
    print("7: Loop Intensity")
    print("9: Exit()")
    choice = input("prompt")
    if choice == '1':
        toggle_state()
    elif choice == '2':
        loop_state()
    elif choice == '3':
        read_full_state()
    elif choice == '4':
        change_effect("~-")
    elif choice == '5':
        change_effect("~")
    elif choice == '6':
        loop_color()
    elif choice == '7':
        set_intensity()
    elif choice == '9':
        exit()

def toggle_state():
    data_to_send = { "on": "t" }
    send_json_message(data_to_send)
    read_whole_json_message()

def loop_state():
    for x in range(30):
        data_to_send = { "on": "t" }
        send_json_message(data_to_send)
        time.sleep(.05)
        #read_whole_json_message()
def read_full_state():
        data_to_send = { "v": True }
        send_json_message(data_to_send)
        read_whole_json_message()

def change_effect(fx:str)->None:
        # seg.id = Zero-indexed ID of the segment
        # fx = ID of the effect or ~ to increment, ~- to decrement, or "r" for random.
        # fxdef = Forces loading of effect defaults (speed, intensity, etc) from effect metadata. (Bool)
        data_to_send = {"seg":[{"id":1,"fx":fx, "fxdef": True}]}
        send_json_message(data_to_send)

def loop_color()->None:
        # fx = 0 (Turn off effect)
        # bri. 0 to 255 (Brightness)
        for x in range(256):
            data_to_send = {"seg":[{"id":1,"fx":0, "col": [[x, 0, 0]]}]}
            send_json_message(data_to_send)
            time.sleep(.005)

def set_intensity()->None:
        # seg.id = Zero-indexed ID of the segment
        # bri. 0 to 255 (Brightness)5
        5
        5
        5
        for x in range(256):
            data_to_send = {"seg":[{"id":1,"bri":x}]}
            send_json_message(data_to_send)
            time.sleep(.01)


if __name__ == "__main__":
    try:
        # Wait for serial communication to establish
        time.sleep(1)

        while True:
            main_menu()

    except KeyboardInterrupt:
        print("Terminating script.")
    finally:
        print("end of script.")
        ser.close()  # Close the serial port on exit
