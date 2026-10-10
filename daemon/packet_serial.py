"""_summary_"""

import logging
import threading
from queue import Empty, Full, Queue
import serial
import serial.tools.list_ports

from cobs import cobs  # noqa
from daemon.packet import HWEvent, Packet
from daemon.sliding_window import SlidingWindow


logger = logging.getLogger("daemon.PacketSerial")


class PacketSerial:
    """Wraps serialOverUSB connection to add support for
    async reading and writing of Packets.

    start() tries to open the port once, then a reader thread keeps
    retrying every RECONNECT_INTERVAL seconds until the Mega shows up,
    and reconnects if the USB connection is lost. Outgoing packets are
    dropped while the Mega is not connected.

    Returns:
        PacketSerial: instance
    """

    @property
    def port(self) -> str | None:
        """Name of the port the Mega was last found on, or None.

        Returns:
            str: Port name
        """
        return self._port

    @property
    def is_conn_open(self) -> bool:
        """is port opened

        Returns:
            bool: Is the damn port open or not
        """
        ser = self._ser
        return False if ser is None else ser.is_open

    BAUDRATE = 115200
    PACKET_DEVIDER = b"\x00"
    STORE_X_PACKETS_IN_HISTORY = 10
    THREAD_JOIN_TIMEOUT = 2  # seconds
    RECONNECT_INTERVAL = 5  # seconds
    READ_TIMEOUT = 1  # seconds, so read_until() never blocks forever

    def __init__(self, rqueue: Queue, squeue: Queue):
        self._port = None
        self._ser = None
        self._received_queue = rqueue
        self._send_queue = squeue
        self._stop_event = threading.Event()
        self._readserial_thread = None
        self._writeserial_thread = None
        self._reported_missing = False
        self.last_sent: list[Packet] = []
        self.last_received: list[Packet] = []
        self.throttle: SlidingWindow = SlidingWindow(55, 0.05)

    def set_rate_limit(self, nr_of_packets: int, ptime_unit: float):
        """Sliding Window implementation. Limits the no of packets
        that can be sent during a sliding time frame.

        Args:
            nr_of_packets (int): Max No of packets per time frame
            ptime_unit (float): timeframe length
        """
        self.throttle.limit_per_timeunit = nr_of_packets
        self.throttle.time_unit = ptime_unit

    @staticmethod
    def find_port_to_arduino() -> str | None:
        """Get the name of the port that is connected to Arduino, or None."""
        for p in serial.tools.list_ports.comports():
            if p.manufacturer is not None and "Arduino" in p.manufacturer:
                return p.device
        return None

    def start(self) -> None:
        """Tries to open the port, then starts the reader thread (which
        keeps reconnecting) and the writer thread."""
        if self._readserial_thread is not None:
            return
        self._stop_event.clear()
        self._open_port()
        self._readserial_thread = threading.Thread(
            target=self._start_read_packets, name="serial-read", daemon=True
        )
        self._writeserial_thread = threading.Thread(
            target=self._start_write_packets, name="serial-write", daemon=True
        )
        self._readserial_thread.start()
        self._writeserial_thread.start()

    def stop(self) -> None:
        """Stops the reader and writer threads, then closes the port.
        Safe to call more than once, and before start().
        """
        self._stop_event.set()
        for thread in (self._readserial_thread, self._writeserial_thread):
            if thread is not None and thread.is_alive():
                thread.join(self.THREAD_JOIN_TIMEOUT)
                if thread.is_alive():
                    logger.error("%s is still alive", thread.name)
        self._readserial_thread = None
        self._writeserial_thread = None
        if self._ser is not None:
            self._close_port()
            logger.info("PacketSerial: port closed")

    def _open_port(self) -> bool:
        """Finds the Mega and opens its port. Logs a missing Mega only
        once, not on every retry. Returns True if the port is open."""
        port = self.find_port_to_arduino()
        if port is None:
            if not self._reported_missing:
                logger.warning(
                    "Arduino not found. Retrying every %g s", self.RECONNECT_INTERVAL
                )
                self._reported_missing = True
            return False
        try:
            self._ser = serial.Serial(
                port=port, baudrate=self.BAUDRATE, timeout=self.READ_TIMEOUT
            )
        except (serial.SerialException, OSError) as e:
            if not self._reported_missing:
                logger.error("Opening %s failed: %s. Retrying", port, e)
                self._reported_missing = True
            return False
        self._port = port
        self._reported_missing = False
        logger.info("PacketSerial: port %s open", port)
        return True

    def _close_port(self) -> None:
        ser, self._ser = self._ser, None
        try:
            ser.close()
        except (serial.SerialException, OSError):
            logger.exception("Closing serial port failed")

    def send_hello(self) -> None:
        """Sends a Hello packet to ArduinoMega. Hopefully
        we also get response sometime later, indicating
        that the ArduinoMega is powered up and connection
        is established.
        """
        try:
            packet = Packet(HWEvent.HELLO, 1, 1)
            self._send_queue.put(packet, block=True, timeout=10)
        except (Full, ValueError) as e:
            logger.error("ah crap. QueueSize=%d", self._send_queue.qsize())
            d = self._send_queue.queue
            for a in d:
                logger.debug(a)
            logger.error("ah crap. QueueSize=%d", self._send_queue.qsize())
            logger.error(e)

    def _start_read_packets(self) -> None:
        """Keeps the connection open and monitors it for new data.
        Should be run in a dedicated thread.

        When data is read, it is parsed into Packets
        """
        while not self._stop_event.is_set():
            if self._ser is None and not self._open_port():
                self._stop_event.wait(self.RECONNECT_INTERVAL)
                continue
            try:
                self._read_available_packets()
            except (serial.SerialException, OSError) as e:
                logger.error("Serial connection lost: %s", e)
                self._close_port()
                continue
            except (Full, cobs.DecodeError) as e:
                logger.error("invalid packet: %s", e)
            except Exception:
                logger.exception("Unexpected error while reading packets")
            self._stop_event.wait(0.05)

    def _read_available_packets(self) -> None:
        ser = self._ser
        while ser.in_waiting > 1:
            # read until 'devider' (included) and remove
            # last byte (packet devider byte)
            rbytes = ser.read_until(self.PACKET_DEVIDER)[:-1]
            p = PacketSerial.decode_packet(rbytes)
            if p.hw_event != HWEvent.LOOPDURATION and p.hw_event != HWEvent.NOOP:
                self._received_queue.put_nowait(p)
                self._log_packet(p, True)

    def _start_write_packets(self) -> None:
        """Monitors Send Queue for new data.
        Should be run in a dedicated thread.

        Will send all packets until Queue is empty.
        If throttled <see throttle>, it will wait and try again
        later.
        """
        while not self._stop_event.is_set():
            if self._send_queue.qsize() > 0:
                if not self.throttle.ok_to_send():
                    self._stop_event.wait(self.throttle.time_unit * 0.4)
                    continue
                try:
                    packet = self._send_queue.get_nowait()
                    self._send_queue.task_done()
                    if packet is not None:
                        self.__send_packet(packet)
                    self._stop_event.wait(0.05)
                except Empty:
                    pass
                except (TypeError, serial.SerialException, OSError) as e:
                    logger.error("Failed to send packet: %s", e)
            else:
                self._stop_event.wait(0.1)

    def __send_packet(self, packet: Packet) -> None:
        ser = self._ser
        if ser is None or not ser.is_open:
            logger.debug("Mega not connected. Dropped %s", packet)
            return
        encoded_bytes = PacketSerial.encode_packet(packet)
        ser.write(encoded_bytes)
        ser.write(self.PACKET_DEVIDER)  # packet divider
        self._log_packet(packet, False)

    def _log_packet(self, packet: Packet, received: bool) -> None:
        """Logs Packet info to log file and stores it in
         a packet history list.

        Args:
            packet (Packet): Packet to log
            received (bool): True if incoming, False if outgoing
        """
        alist = self.last_received if received else self.last_sent
        msg = "packet_received: %s" if received else "packet sent: %s"
        alist.append(packet)
        while len(alist) > self.STORE_X_PACKETS_IN_HISTORY:
            del alist[0]
        # logger.info(msg, packet)

    @staticmethod
    def encode_packet(packet: Packet) -> bytes:
        """Encode a Packet as byte array.
            Note: Packade devider(b'\x00') is not included.

        Args:
            packet (Packet): The packet to encode as bytes

        Returns:
            bytes: iterable array of bytes
        """
        return cobs.encode(packet.as_bytes())
        # encoded_packet = bytearray(cobs.encode(packet.as_bytes()))
        # encoded_packet.extend(b'\x00')  # Add package sequence (divider)
        # return bytes(encoded_packet)

    @staticmethod
    def decode_packet(b: bytes) -> Packet:
        """Decodes byte array and then parses it into
        a Packet instance.

        Args:
            b (bytes): the bytes to decode and parse

        Returns:
            Packet: The decoded Packet
        """
        # p = Packet(cobs.decode(b[:-1]))
        p = Packet(cobs.decode(b))
        return p
