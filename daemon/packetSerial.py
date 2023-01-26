#!/usr/bin/env python

from typing import List
import serial
import logging
import serial.tools.list_ports
from cobs import cobs  # noqa
from daemon import packet
from queue import Queue, Empty, Full
import time
import signal
import threading


logger = logging.getLogger('daemon.PacketSerial')
consoleHandler = logging.StreamHandler()
logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)

class PacketSerial:
    @property
    def port(self):
        return self._port

    @property
    def is_conn_open(self):
        return False if self._ser is None else self._ser.is_open

    def __init__(self, rqueue: Queue, squeue: Queue):
        self._port = self.find_arduino()
        self._ser = None
        self._received_queue = rqueue
        self._send_queue = squeue
        self._rshutdown_flag = threading.Event()
        self._sshutdown_flag = threading.Event()
        self._readserial_thread = None
        self._writeserial_thread = None

    def find_arduino(self) -> str:
        """Get the name of the port that is connected to Arduino."""
        ports = serial.tools.list_ports.comports()
        for p in ports:
            logger.info(
                "Found: Port:%s\tName:%s\tmf:%s\tHWID:%s", p.device,
                p.name, p.manufacturer, p.hwid)
            if p.manufacturer is not None and "Arduino" in p.manufacturer:
                port = p.device
        return port

    def open_connection(self) -> None:
        try:
            logger.info("PacketSerial Opening port " + self.port)
            self._ser = serial.Serial(port=self._port, baudrate=115200)
            logger.info("Serial port is " +
                        "open" if self._ser.is_open else "closed")
            if self._readserial_thread is None:
                self._readserial_thread = threading.Thread(target=self.start_read_packets)
            if not self._readserial_thread.is_alive():
                self._readserial_thread.start()
            if self._writeserial_thread is None:
                self._writeserial_thread = threading.Thread(target=self.start_write_packets)
            if not self._writeserial_thread.is_alive():
                self._writeserial_thread.start()
        except Exception as e:
            logger.error(e)

    def close_connection(self) -> None:
        try:
            if self._ser is None:
                return
            self._ser.close()
            logger.info("waiting for serial worker threads to stop...")
            self._rshutdown_flag.set()
            self._sshutdown_flag.set()
            if self._readserial_thread is not None: self._readserial_thread.join()
            if self._writeserial_thread is not None: self._writeserial_thread.join()
            logger.info("Worker threads stopped. PacketSerial: port closed")
        except Exception as e:
            logger.error(e)

    def send_hello(self) -> None:
        try:
            packet = packet.Packet(packet.HWEvent.HELLO, 1, 1)
            self._send_queue.put(packet, block=True, timeout=10)
        except Exception as e:
            logger.error(e)
        pass

    def start_read_packets(self) -> None:
        while not self._rshutdown_flag.is_set():
            if self._ser is None:
                logger.error("cannot read Serial when connection=None")
                return
            if not self._ser.is_open:
                logger.error("cannot read Serial when connection is closed")
                return
            try:
                logger.info("reading serial")
                while self._ser.in_waiting > 1:
                    # read until 'devider' (included) and remove
                    # last byte (packet devider byte)
                    rbytes = self._ser.read_until(b'\x00')[:-1]
                    self._received_queue.put_nowait(PacketSerial.decode_packet(rbytes))
            except Exception as e:
                logger.error(e)
        self._rshutdown_flag.clear()

    def start_write_packets(self) -> None:
        while not self._sshutdown_flag.is_set():
            if(self._send_queue.qsize() > 0):
                try:
                    packet = self._send_queue.get_nowait(block=False)
                    if packet != None:
                        self.__send_packet()
                except Empty:
                    pass
                except Exception as e:
                    logger.error(e)
            else:
                time.sleep(0.05)
        self._sshutdown_flag.clear()

    def __send_packet(self, packet: packet.Packet) -> None:
        if self._ser is None:
            logger.error("cannot send Packet when connection=None")
            return
        if not self._ser.is_open:
            logger.error("cannot send Packet when connection is closed")
            return
        encoded_bytes = PacketSerial.encode_packet(packet)
        self._ser.write(encoded_bytes)
        self._ser.write(b'\x00') # packet divider

    @staticmethod
    def encode_packet(packet: packet.Packet) -> bytes:
        return cobs.encode(packet.as_bytes())
        # encoded_packet = bytearray(cobs.encode(packet.as_bytes()))
        # encoded_packet.extend(b'\x00')  # Add package sequence (divider)
        # return bytes(encoded_packet)

    @staticmethod
    def decode_packet(b: bytes) -> packet.Packet:
        p = packet.Packet(cobs.decode(b[:-1]))
        return p
