from enum import unique, Flag, auto
import datetime
import logging
import queue
import threading
import numpy as np
import serial
import json
import time
from typing import Callable, Dict, Any, NamedTuple, Optional
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

    THREAD_JOIN_TIMEOUT = 2  # seconds
    RECONNECT_INTERVAL = 5  # seconds

    def __init__(self, uart_port: str = "/dev/serial0", baud_rate: int = 460800):
        """
        Initialize the WLED instance. Opens nothing; see start().

        Args:
            uart_port (str): the serial port of this Raspberry pi.
            baud_rate (int): Baud rate. Needs to be configured
            the same in WLED.
        """
        self.command_queue = queue.Queue(maxsize=10)
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self.sunrise_thread = None
        self.sending_thread = None
        self._uart_port = uart_port
        self._baud_rate = baud_rate
        self._accept_commands: bool = True
        self._ser_timeout = 2
        self._ser: serial.Serial | None = None
        self._next_open_attempt = 0.0

    def start(self) -> None:
        """Opens the UART and starts the sender thread. If the UART
        cannot be opened, the sender retries when it has a command."""
        if self.sending_thread is not None:
            return
        self._stop_event.clear()
        self._open_port()
        self.sending_thread = threading.Thread(
            target=self._send_cmd_from_queue, name="wled-send", daemon=True
        )
        self.sending_thread.start()

    def stop(self) -> None:
        """Stops the sunrise and sender threads, then closes the UART.
        Safe to call more than once, and before start()."""
        self._stop_event.set()
        for thread in (self.sunrise_thread, self.sending_thread):
            if thread is not None and thread.is_alive():
                thread.join(self.THREAD_JOIN_TIMEOUT)
                if thread.is_alive():
                    logger.error("%s is still alive", thread.name)
        self.sending_thread = None
        if self._ser is not None:
            self._close_port()
            logger.info("WLED serial connection closed")

    def _open_port(self) -> bool:
        """Opens the UART unless it is already open. After a failure the
        next attempt waits RECONNECT_INTERVAL seconds. True if open."""
        if self._ser is not None:
            return True
        if time.monotonic() < self._next_open_attempt:
            return False
        try:
            self._ser = serial.Serial(
                self._uart_port, self._baud_rate, timeout=self._ser_timeout
            )
        except (serial.SerialException, OSError) as e:
            logger.error("Opening WLED port %s failed: %s", self._uart_port, e)
            self._next_open_attempt = time.monotonic() + self.RECONNECT_INTERVAL
            return False
        logger.info("WLED port %s open (%d baud)", self._uart_port, self._baud_rate)
        return True

    def _close_port(self) -> None:
        ser, self._ser = self._ser, None
        try:
            ser.close()
        except (serial.SerialException, OSError):
            logger.exception("Closing WLED port failed")

    def set_wled_state(self, on: bool, segment: Optional[int] = None) -> None:
        """Set on/off state for a specific segment, or ALL
        segments if no segmentID is passed in"""
        if segment is not None:
            data_to_send = {"bri": 255, "seg": [{"id": segment, "on": on}]}
            self._enqueue_command(data_to_send)
            return
        status = self.read_state()
        for seg in status.seg_state:
            data_to_send = {"bri": 255, "seg": [{"id": seg.seg_id, "on": on}]}
            self._enqueue_command(data_to_send)

    def toggle_wled_state(self, segment: Optional[int] = None) -> None:
        if segment is None:
            data_to_send = {"on": "t", "bri": 255}
        else:
            data_to_send = {"bri": 255, "seg": [{"id": segment, "on": "t"}]}
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

    def do_sunrise(
        self, dur_sec: int = 20 * 60, p_callback: Callable[[], None] = None
    ) -> None:
        """
        Gradually increasing intensity while fading color from red to yellow.
        This function returns immediately,as the sunrise effect is performed in a
        child thread.

        :param dur_sec: Duration of the Sunrise effect in seconds
        :type dur_sec: int
        :param p_callback: Function to be called once the effect is complete
        :type p_callback: Callable[[], None]
        """
        if self.sunrise_thread is not None and self.sunrise_thread.is_alive():
            return
        self.sunrise_thread = threading.Thread(
            target=self._do_sunrise,
            kwargs=dict(dur_sec=dur_sec, p_callback=p_callback),
            name="wled-sunrise",
            daemon=True,
        )
        self.sunrise_thread.start()  # Start the sending thread

    def _do_sunrise(self, dur_sec: int, p_callback: Callable[[], None] = None) -> None:
        # User is not allowed to use WLED until Sunrise effect is complete
        self._accept_commands = False

        start_bri = 5
        start_color = [255, 34, 3, 1]  # dark red
        end_bri = 200
        end_color = [250, 196, 3, 64]  # light yellow
        steps = 600

        # Turn down brightness before we begin doing sunrise
        data_to_send = {
            "on": True,
            "seg": [
                {"id": 0, "on": True, "fx": 0, "bri": 1, "col": [start_color]},
                {"id": 1, "on": True, "fx": 0, "bri": 1, "col": [start_color]},
            ],
        }
        self._enqueue_command(data_to_send, True)

        steps_s = dur_sec / steps
        for i in range(steps):
            color = WLED.color_transform(start_color, end_color, i / steps)
            color = [int(item) for item in color]
            bri = ((end_bri - start_bri) / steps) * i
            data_to_send = {
                "on": True,
                "bri": 255,
                "seg": [
                    {
                        "id": 0,
                        "on": True,
                        "fx": 0,
                        "bri": int(bri),
                        "col": [color],
                    },
                    {
                        "id": 1,
                        "on": True,
                        "fx": 0,
                        "bri": int(bri),
                        "col": [color],
                    },
                ],
            }
            self._enqueue_command(data_to_send, True)
            if self._stop_event.wait(steps_s):
                self._accept_commands = True
                return
        self._accept_commands = True
        if p_callback is not None:
            p_callback()

    @staticmethod
    def color_transform(fromcolor, tocolor, percent: float):
        """Transforms a color to target color

        :param fromcolor:  color is rgbw between (0, 0, 0, 0)
        :param tocolor:  color is rgbw between (0, 0, 0, 0)
        :param percent: from 0.0 to 1.0
        :type percent: float
        :return: transformed color
        :rtype: NDArray[floating[Any]]"""
        percent = max(0, min(percent, 1))
        fromcolor = np.array(fromcolor)
        tocolor = np.array(tocolor)
        vector = tocolor - fromcolor
        return fromcolor + vector * percent

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

    def _enqueue_command(self, command: dict, lock_override: bool = False) -> None:
        """Thread-safe function to add commands to the queue."""
        if not self._accept_commands and not lock_override:
            return
        with self.lock:
            if self.command_queue.full():
                # Discard the oldest command (first in queue)
                self.command_queue.get()
            self.command_queue.put(command)

    def _send_cmd_from_queue(self):
        """Thread function that sends commands from the queue."""
        while not self._stop_event.is_set():
            try:
                # Wake up regularly to notice the stop event
                command = self.command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.command_queue.task_done()
            if not self._open_port():
                logger.debug("WLED port not open. Dropped %s", command)
                continue
            try:
                json_data = json.dumps(command)
                self._ser.write((json_data + "\n").encode())
                self._ser.flush()
                self._stop_event.wait(0.01)
            except (serial.SerialException, OSError) as e:
                logger.error("Error sending JSON command: %s", e)
                self._close_port()

    def _read_whole_json_message(self) -> Dict[str, Any]:
        start_time = time.time()
        received_data = ""
        while True:
            current_time = time.time()  # Get the current time
            elapsed_time = current_time - start_time  # Calculate elapsed time
            received_data = self._read_message()

            if elapsed_time > 1.5 or received_data:
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
            logger.warning("Received non-JSON data from WLED")
        except Exception as e:
            logger.error("Error reading JSON from WLED: %s", e)
        return None

    def __str__(self):
        """
        Return a string representation of me.

        Returns:
            str: A human-readable string of me.
        """
        return f"WLED(uart_port={self._uart_port}, " f"baud_rate={self._baud_rate}"
