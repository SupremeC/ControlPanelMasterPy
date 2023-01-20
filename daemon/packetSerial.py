#!/usr/bin/env python

import serial
import logging
import serial.tools.list_ports
from cobs import cobs  # noqa
from daemon import packet

logger = logging.getLogger('daemon.PacketSerial')


class PacketSerial:
    @property
    def port(self):
        return self._port

    @property
    def is_conn_open(self):
        return False if self._ser is None else self._ser.is_open

    def __init__(self):
        self._port = self.find_arduino()
        self._ser = None

    def find_arduino(self, port: str = None) -> str:
        """Get the name of the port that is connected to Arduino."""
        if port is None:
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
            logger.info("PacketSerial Opening port " + self._pserial.port)
            self._ser = serial.Serial(port=self._port, baudrate=115200)
            logger.info("Serial port is " +
                        "open" if self._ser.is_conn_open else "closed")
        except Exception as e:
            logger.error(e)

    def close_connection(self) -> None:
        try:
            if self._ser is None:
                return
            self._ser.close()
        except Exception as e:
            logger.error(e)

    def send_hello(self) -> None:
        pass

    def read_packets(self):
        if self._ser is None:
            logger.error("cannot read Serial when connection=None")
            return
        if not self._ser.is_open:
            logger.error("cannot read Serial when connection is closed")
            return
        try:
            packets = []
            logger.info("reading serial (fake). TODO: remove, dec intvl")
            while self._ser.in_waiting > 1:
                # read until 'devider' (included) and remove
                # last byte (packet devider byte)
                rbytes = self._ser.read_until(b'\x00')[:-1]
                packets.append(packet.Packet.decode_packet(rbytes))
                # packets.append(packet.Packet(cobs.decode(rbytes)))
            return packets
        except Exception as e:
            logger.error(e)

    def send_packet(self, packet: packet.Packet) -> None:
        if self._ser is None:
            logger.error("cannot send Packet when connection=None")
            return
        if not self._ser.is_open:
            logger.error("cannot send Packet when connection is closed")
            return
        encoded_bytes = PacketSerial.encode_packet(packet)
        self._ser.write(encoded_bytes)

    @staticmethod
    def encode_packet(packet: packet.Packet) -> bytes:
        encoded_packet = bytearray(cobs.encode(packet.as_bytes()))
        encoded_packet.extend(b'\x00')  # Add package sequence (divider)
        return bytes(encoded_packet)

    @staticmethod
    def decode_packet(b: bytes) -> packet.Packet:
        p = packet.Packet(cobs.decode(b[:-1]))
        return p
