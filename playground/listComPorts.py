#!/usr/bin/env python

import serial.tools.list_ports

def find_port_to_arduino() -> str:
    """Get the name of the port that is connected to Arduino."""
    port = "ErrorPS.01: Arduino not found"
    ports = serial.tools.list_ports.comports()
    print("\tPort\tName\tmf\tHWID")
    for p in ports:
        print(f"{p.name}\{p.name}\t{p.manufacturer}\t{p.hwid}")
        if p.manufacturer is not None and "Arduino" in p.manufacturer:
            print(f"It looks like I should use port {p.device}")
            port = p.device
    return port


if __name__ == '__main__':
    find_port_to_arduino()
