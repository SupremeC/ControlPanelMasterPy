# saved as greeting-server.py
import threading
import time
import datetime
from array import array
from typing import List
from Pyro5.api import expose, Daemon, config, register_class_to_dict, register_dict_to_class
from testclass import ErrorType, HWEvent, Packet


class MyOwnDaemon:
    """TestDaemon"""

    def __init__(self) -> None:
        # create a pyro daemon with object, running in its own worker thread
        self.pyro_thread = PyroDaemon(self)
        self.pyro_thread.daemon = True
        self.pyro_thread.start()
        self.pyro_thread.started.wait()

        # serialization
        register_dict_to_class("pyro-custom-Packet", Packet.packet_dict_to_class)
        register_class_to_dict(Packet, Packet.packet_class_to_dict)

        #print stuff
        print("Pyro server started. Using Pyro worker thread.")
        print("Use the command line client to send messages.")
        print(f"Pyro object uri = {self.pyro_thread.uri}")


    def run(self):
        """MainLoop"""
        while True:
            self.control_panelprocess()
            time.sleep(.1)

    def control_panelprocess(self) -> None:
        """simulate work"""
        time.sleep(.2)

    @expose
    def say_hello(self) -> str:
        """Pyro exposed function"""
        return "Well hello there stranger!"

    @expose
    def sendmessage(self) -> List[Packet]:
        """Pyro exposed function"""
        ps = []
        for i in range(1,4):
            o = Packet()
            o.created -= datetime.timedelta(weeks=52*26)
            o.target = 42
            o.val = 42123
            o.hw_event = HWEvent.BOOTMEGA
            o.error = ErrorType.INVALIDPWMBOARD
            ps.append(o)
        return ps
    
    @expose
    def acceptmessage(self, o: Packet) -> None:
        """Pyro exposed function"""
        print("type of response object:", type(o))
        #print(f"No={o.target}, name={o.val}, Created={o.created}, err={o.error}, hwevent={o.hw_event}")
        print(o)



class PyroDaemon(threading.Thread):
    """runs Pyro in its own thread"""
    def __init__(self, owner):
        threading.Thread.__init__(self)
        self.uri = None
        self.owner = owner
        self.started = threading.Event()

    def run(self) -> None:
        self.pyro_daemon = Daemon()
        self.uri = self.pyro_daemon.register(self.owner, "pyrogui.message2")
        self.started.set()
        self.pyro_daemon.requestLoop()

    def stoop(self) -> None:
        self.pyro_daemon.shutdown()
        self.pyro_daemon.close()




def main():
    """execution entry point"""
    my_daemon = MyOwnDaemon()

    # enter the mainloop
    my_daemon.run()



if __name__ == "__main__":
    main()


























""" class GreetingMaker(object):
    @expose
    def get_fortune(self, name):
        return "Hello, {0}. Here is your fortune message:\n" \
               "Behold the warranty -- the bold print giveth and the fine print taketh away.".format(name)

Pyro5.Daemon.serveSimple({
    GreetingMaker: 'Greeting',
}, host="0.0.0.0", port=9090, ns=False, verbose=True) """