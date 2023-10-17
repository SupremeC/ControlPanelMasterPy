"""_summary_"""
#!/usr/bin/env python

import logging
import threading
import time
from queue import Empty, Full, Queue
import serial
import serial.tools.list_ports

from cobs import cobs  # noqa
from daemon.packet import HWEvent, Packet
from daemon.sliding_window import SlidingWindow


logger = logging.getLogger("daemon.PacketSerial")
consoleHandler = logging.StreamHandler()
logFormatter = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s"
)
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)


class PacketSerial:
    """Wraps serialOverUSB connection to add support for
    async reading and writing of Packets.

    Returns:
        PacketSerial: instance
    """

    @property
    def port(self) -> str:
        """Read the current port name

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
        return False if self._ser is None else self._ser.is_open

    BAUDRATE = 115200
    PACKET_DEVIDER = b"\x00"
    STORE_X_PACKETS_IN_HISTORY = 10

    def __init__(self, rqueue: Queue, squeue: Queue):
        self._port = self.find_port_to_arduino()
        self._ser = None
        self._received_queue = rqueue
        self._send_queue = squeue
        self._rshutdown_flag = threading.Event()
        self._sshutdown_flag = threading.Event()
        self._readserial_thread = None
        self._writeserial_thread = None
        self.last_sent: list[Packet] = []
        self.last_received: list[Packet] = []
        self.throttle: SlidingWindow = SlidingWindow(35, 0.05)

    def set_rate_limit(self, nr_of_packets: int, ptime_unit: float):
        """Sliding Window implementation. Limits the no of packets
        that can be sent during a sliding time frame.

        Args:
            nr_of_packets (int): Max No of packets per time frame
            ptime_unit (float): timeframe length
        """
        self.throttle.limit_per_timeunit = nr_of_packets
        self.throttle.time_unit = ptime_unit

    def find_port_to_arduino(self) -> str:
        """Get the name of the port that is connected to Arduino."""
        port = "ErrorPS.01: Arduino not found"
        ports = serial.tools.list_ports.comports()
        for p in ports:
            logger.info(
                "Found: Port:%s\tName:%s\tmf:%s\tHWID:%s",
                p.device,
                p.name,
                p.manufacturer,
                p.hwid,
            )
            if p.manufacturer is not None and "Arduino" in p.manufacturer:
                port = p.device
        return port

    def open_connection(self) -> None:
        """Tries to open port to establish serialOverUSB connection.

        On success:
            Monitors serial input buffer on new thread
            new Thread sends outgoing packets
        """
        try:
            logger.info("PacketSerial Opening port %s", self.port)
            self._ser = serial.Serial(port=self._port, baudrate=self.BAUDRATE)
            logger.info("Serial port is " + "open" if self._ser.is_open else "closed")
            if self._readserial_thread is None:
                self._readserial_thread = threading.Thread(
                    target=self._start_read_packets
                )
            if not self._readserial_thread.is_alive():
                self._readserial_thread.start()
            if self._writeserial_thread is None:
                self._writeserial_thread = threading.Thread(
                    target=self._start_write_packets
                )
            if not self._writeserial_thread.is_alive():
                self._writeserial_thread.start()
        except Exception as e:
            logger.error(e)
            # raise

    def close_connection(self) -> None:
        """Close serial connection.

        Also shutdowns the 2 threads responsible for
        reading and writing to the port.
        """
        try:
            if self._ser is None:
                return
            self._ser.close()
            logger.info("waiting for serial worker threads to stop...")
            self._rshutdown_flag.set()
            self._sshutdown_flag.set()
            if (
                self._readserial_thread is not None
                and self._readserial_thread.is_alive()
            ):
                self._readserial_thread.join(30)
            if (
                self._writeserial_thread is not None
                and self._readserial_thread.is_alive()
            ):
                self._writeserial_thread.join(30)

            if self._readserial_thread.is_alive():
                raise TimeoutError("_readserial_thread is still alive")
            if self._writeserial_thread.is_alive():
                raise TimeoutError("_writeserial_thread is still alive")
            self._readserial_thread = None
            self._writeserial_thread = None
            logger.info("Worker threads stopped. PacketSerial: port closed")
        except (TimeoutError, RuntimeError) as e:
            logger.error(e)

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
        """Monitors Serial connection for new data.
        Should be run in a dedicated thread.

        When data is read, it is parsed into Packets
        """
        while not self._rshutdown_flag.is_set():
            if self._ser is None:
                logger.error("cannot read Serial when connection=None")
                return
            if not self._ser.is_open:
                logger.error("cannot read Serial when connection is closed")
                return
            try:
                while self._ser.in_waiting > 1:
                    # read until 'devider' (included) and remove
                    # last byte (packet devider byte)
                    rbytes = self._ser.read_until(self.PACKET_DEVIDER)[:-1]
                    p = PacketSerial.decode_packet(rbytes)
                    self._received_queue.put_nowait(p)
                    self._log_packet(p, True)
                time.sleep(0.05)
            except (TimeoutError, Full, cobs.DecodeError) as e:
                logger.error(e)
        self._rshutdown_flag.clear()

    def _start_write_packets(self) -> None:
        """Monitors Send Queue for new data.
        Should be run in a dedicated thread.

        Will send all packets until Queue is empty.
        If throttled <see throttle>, it will sleep and try again
        later.
        """
        while not self._sshutdown_flag.is_set():
            if self._send_queue.qsize() > 0:
                if not self.throttle.ok_to_send():
                    time.sleep(self.throttle.time_unit * 0.4)
                    continue
                try:
                    packet = self._send_queue.get_nowait(block=False)
                    self._send_queue.task_done()
                    if packet is not None:
                        self.__send_packet(packet)
                except Empty:
                    pass
                except (
                    TypeError,
                    serial.SerialTimeoutException,
                    serial.SerialException,
                ) as e:
                    logger.error("Failed to send packet. Error as follows...")
                    logger.error(e)
            else:
                time.sleep(0.1)
        self._sshutdown_flag.clear()

    def __send_packet(self, packet: Packet) -> None:
        if self._ser is None:
            logger.error("cannot send Packet when connection=None")
            return
        if not self._ser.is_open:
            logger.error("cannot send Packet when connection is closed")
            return
        encoded_bytes = PacketSerial.encode_packet(packet)
        self._ser.write(encoded_bytes)
        self._ser.write(self.PACKET_DEVIDER)  # packet divider
        self._log_packet(packet, False)

    def _log_packet(self, packet: Packet, received: bool) -> None:
        """Logs Packet info to log file and stores it in
         a packet history list.

        Args:
            packet (Packet): Packet to log
            received (bool): True if incoming, False if outgoing
        """
        alist = self.last_received if received else self.last_sent
        msg = "packet received: %s" if received else "packet sent: %s"
        alist.append(packet)
        while alist.count() > self.STORE_X_PACKETS_IN_HISTORY:
            del alist[0]
        logger.info(msg, packet)

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
        p = Packet(cobs.decode(b[:-1]))
        return p
