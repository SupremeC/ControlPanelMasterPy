# saved as greeting-server.py
import threading
import time
from Pyro5.api import expose, Daemon


class MyOwnDaemon:
    """TestDaemon"""

    def __init__(self) -> None:
        # create a pyro daemon with object, running in its own worker thread
        self.pyro_thread = PyroDaemon(self)
        self.pyro_thread.daemon = True
        self.pyro_thread.start()
        self.pyro_thread.started.wait()

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
    def message(self, messagetext):
        """Pyro exposed function"""
        print("fromClient-->" + messagetext)

    @expose
    def sleep(self, duration):
        """Pyro exposed function"""
        print("fromClient--> SLEEP " +str(duration))

    @expose
    def stoopp(self):
        """Pyro exposed function"""
        print("fromClient--> stop ")
        self.pyro_thread.stoop()
        print("Pyro stopped! Whoohoo!")





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