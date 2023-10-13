"""Pyro Client"""
from datetime import datetime
import time
import pathlib
import os
import sys
from Pyro5.api import Proxy, config, register_class_to_dict, register_dict_to_class
from testclass import ErrorType, HWEvent, Packet


# serialization
register_dict_to_class("pyro-custom-Packet", Packet.packet_dict_to_class)
register_class_to_dict(Packet, Packet.packet_class_to_dict)



print("First make sure one of the gui servers is running.")
print("Enter the object uri that was printed:")
uri = input().strip()
guiserver = Proxy(uri)


server_answer = guiserver.say_hello()
print("server said--> " + str(server_answer))

response = guiserver.sendmessage()
print("=========================")
print("TYPE==" + str(type(response)))
for p in response:
    print(p)
print("=========================")
"""
time.sleep(0.5)
o = Packet()
o.target = 99
o.val = 9999
o.error = ErrorType.LEDINVALIDVALUE
o.hw_event = HWEvent.I2CBLED
guiserver.acceptmessage(o)
time.sleep(1)
"""

server_answer = guiserver.say_hello()
print("server said--> " + str(server_answer))
print("client stopped")
