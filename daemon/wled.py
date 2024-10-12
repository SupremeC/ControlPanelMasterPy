from enum import unique, Flag, auto
import datetime
import logging
import queue
import random
import threading
import serial
import json
import time
from typing import Dict, Any, NamedTuple, Optional
from typing import List


logger = logging.getLogger("daemon.WLED")


@unique
class CmdType(Flag):
    """CmdType. Not used at the moment. Might be needed if I
    have to implement some kind of Queue"""

    SegmentState = auto()
    Segment1 = auto()
    Segment2 = auto()
    SegmentBrightness = auto()
    SegmentColor = auto()
    SegmentFx = auto()
    WledState = auto()


class SegmentState(NamedTuple):
    """
    Snapshot of the state of an individual segment

    Attributes:
        seg_id (int): ID of segment (zero-based)
        seg_state (bool): is the segment ON or OFF
        seg_brightness (int): 0-255
        led_count (int): Number of LEDs
        led_start (int): index of first LED
        led_stop (int): index of last LED
        fx (int): 0 == no effect running. otherwise the ID of the effect
    """

    seg_id: bool
    seg_state: bool
    seg_brightness: int
    led_count: int
    led_start: int
    led_stop: int
    fx: int


class WledStateSnapshot(NamedTuple):
    """
    Snapshot of the states in WLED at a specific time.
    """

    wled_state: bool
    seg_count: int
    seg_state: list[SegmentState]
    updatedAt: datetime = datetime.datetime.now()


class WLED:
    """Sends commands to an WLED device via a Serial port"""

    def __init__(self, uart_port: str = "/dev/serial0", baud_rate: int = 460800):
        """
        Initialize the WLED instance.

        Args:
            uart_port (str): the serial port of this Raspberry pi.
            baud_rate (int): Baud rate. Needs to be configured
            the same in WLED.
        """
        self.command_queue = queue.Queue(maxsize=10)
        self.lock = threading.Lock()
        self.sending_thread = threading.Thread(
            target=self._send_cmd_from_queue, daemon=True
        )
        self.sending_thread.start()  # Start the sending thread
        self._uart_port = uart_port
        self._baud_rate = baud_rate
        self._ser_timeout = 2
        self._ser = serial.Serial(
            self._uart_port, self._baud_rate, timeout=self._ser_timeout
        )

    def check_serial_connection(self):
        try:
            if not self._ser.is_open:
                self._ser.open()
                time.sleep(0.1)
                if self._ser.is_open():
                    logger.info(f"Established connection on {self._uart_port}.")
                else:
                    logger.info("Failed to establish connection")
        except serial.SerialException as e:
            logger.error(f"Error with the serial connection: {e}")
            try:
                # Attempt to reestablish connection
                ser = serial.Serial(
                    self._uart_port, self._baud_rate, timeout=self._ser_timeout
                )
                time.sleep(0.1)
                logger.info(f"Reestablished connection on {self._uart_port}.")
                return ser
            except serial.SerialException as e:
                logger.info(f"Failed to reestablish connection: {e}")
                return None

    def close_serial_conn(self) -> None:
        logger.info("WLED serial connection closed")
        self._ser.close()

    def set_wled_state(self, on: bool, segment: Optional[int] = None) -> None:
        """Set on/off state for a specific segment, or ALL
        segments if no segmentID is passed in"""
        if segment is not None:
            data_to_send = {"seg": [{"id": segment, "on": on}]}
            self._enqueue_command(data_to_send)
        status = self.read_state()
        for seg in status.seg_state:
            data_to_send = {"seg": [{"id": seg.seg_id, "on": on}]}
            self._enqueue_command(data_to_send)

    def toggle_wled_state(self, segment: Optional[int] = None) -> None:
        if segment is None:
            data_to_send = {"on": "t"}
        else:
            data_to_send = {"seg": [{"id": segment, "on": "t"}]}
        self._enqueue_command(data_to_send)

    def read_state(self) -> WledStateSnapshot:
        data_to_send = {"v": True}
        self._enqueue_command(data_to_send)
        json = self._read_whole_json_message()
        wled_state = json["state"]["on"]
        seg_count = len(json["state"]["seg"])
        segs = []
        for seg in json["state"]["seg"]:
            segs.append(
                SegmentState(
                    seg["id"],
                    seg["on"],
                    seg["bri"],
                    seg["len"],
                    seg["start"],
                    seg["stop"],
                    seg["fx"],
                )
            )

        return WledStateSnapshot(wled_state, seg_count, segs)

    def set_color(self, color: List[int], segment: int) -> None:
        # fx = 0 (Turn off effect)
        if len(color) == 3:
            color = [max(0, min(item, 255)) for item in color]
            # data_to_send = {"seg": [{"id": segment, "fx": 0, "col": [color]}]}
            data_to_send = {
                "seg": [{"id": segment, "col": [color]}],
                "udpn.send": False,
            }
            self._enqueue_command(data_to_send)

    def set_brightness(self, brightness: int, segment: int) -> None:
        # seg.id = Zero-indexed ID of the segment
        # bri. 0 to 255 (Brightness)
        brightness = max(0, min(brightness, 255))
        data_to_send = {"seg": [{"id": segment, "bri": brightness}]}
        self._enqueue_command(data_to_send)

    def next_effect(self, segment: int) -> None:
        self._change_effect("~", segment)

    def previous_effect(self, segment: int) -> None:
        self._change_effect("~-", segment)

    def _change_effect(self, fx: str, segment: int) -> None:
        """
        seg.id = Zero-indexed ID of the segment.
        fx = ID of the effect or ~ to increment, ~- to decrement,
        or "r" for random.
        fxdef = Forces loading of effect defaults (speed, intensity, etc)
        from effect metadata. (Bool)
        """
        data_to_send = {
            "seg": [{"id": segment, "fx": fx, "fxdef": True}],
            "udpn.send": False,
        }
        self._enqueue_command(data_to_send)

    def _enqueue_command(self, command: dict):
        """Thread-safe function to add commands to the queue."""
        with self.lock:
            if self.command_queue.full():
                # Discard the oldest command (first in queue)
                self.command_queue.get()
            self.command_queue.put(command)

    def _send_cmd_from_queue(self):
        """Thread function that sends commands from the queue."""
        while True:
            try:
                # Get command from the queue (blocks until an item is available)
                command = self.command_queue.get()
                self.check_serial_connection()
                json_data = json.dumps(command)
                self._ser.write((json_data + "\n").encode())
                self._ser.flush()
                self.command_queue.task_done()
                time.sleep(0.01)
            except serial.SerialException as e:
                logger.error(f"Error sending JSON command: {e}")

    def _read_whole_json_message(self) -> Dict[str, Any]:
        start_time = time.time()
        received_data = ""
        while True:
            current_time = time.time()  # Get the current time
            elapsed_time = current_time - start_time  # Calculate elapsed time
            received_data = self._read_message()
            if elapsed_time > 1.5 or received_data:
                # Handle received data
                break
        return received_data

    def _read_message(self) -> Dict[str, Any]:
        try:
            # Read data from the ESP32
            if self._ser.in_waiting > 0:
                message = self._ser.readline().decode("utf-8").strip()
                # Parse the message as JSON
                json_data = json.loads(message)
                # json_string = json.dumps(json_data, indent=4)
                # print(f"Received: {json_string}")
                return json_data
        except json.JSONDecodeError:
            print("Received non-JSON data.")
        except Exception as e:
            print(f"Error reading JSON: {e}")
        return None

    def __str__(self):
        """
        Return a string representation of me.

        Returns:
            str: A human-readable string of me.
        """
        return f"WLED(uart_port={self._uart_port}, " f"baud_rate={self._baud_rate}"


if __name__ == "__main__":
    wled_instance = WLED()

    def main_menu():
        print("===============")
        print("1: Toggle WLED ON/OFF state")
        print("11: Set WLED state ON")
        print("12: Set WLED state OFF")
        print("2: Get WLED state")
        print("3: Read full state as string")
        print("4: Previous effect")
        print("5: Next effect")
        print("6: Set solid color = Rnd")
        print("7: Rnd brightness")
        print("8: Toggle segment 1 ON/OFF state")
        print("9: Exit()")
        choice = input("prompt")
        if choice == "1":
            wled_instance.toggle_wled_state()
        if choice == "11":
            wled_instance.set_wled_state(True)
        if choice == "12":
            wled_instance.set_wled_state(False)
        if choice == "2":
            result = wled_instance.read_state()
            print(result)
        elif choice == "3":
            data_to_send = {"v": True}
            wled_instance._enqueue_command(data_to_send)
            json_string = wled_instance._read_whole_json_message()
            json_string = json.dumps(json_string, indent=4)
            print(f"Received: {json_string}")
        elif choice == "4":
            wled_instance.previous_effect(1)
        elif choice == "5":
            wled_instance.next_effect(1)
        elif choice == "6":
            wled_instance.set_color(
                [
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255),
                ],
                1,
            )
        elif choice == "7":
            wled_instance.set_brightness(random.randint(0, 255), 1)
        if choice == "8":
            wled_instance.toggle_wled_state(segment=1)
        elif choice == "9":
            exit()

    while True:
        main_menu()
