#!/usr/bin/env python

"""
ControlPanel Daemon. Runs in the background.
Opens a connection to ArduinoMega via SerialUSB.


Commands:
=================================
# controlPanelDaemon.py start
# controlPanelDaemon.py stop
# controlPanelDaemon.py restart


Writes to:
=================================
# /tmp/daemon-controlpanel.pid
# ./logs.log


Related links:
=================================
# https://github.com/bakercp/PacketSerial
# https://pythonhosted.org/cobs/


"""


import sys
import time
import logging
import os
import setup_logger # noqa
from daemonSuperClass import Daemon
from controlPanel_class import ControlPanel

logger = logging.getLogger('daemon')


class MyDaemon(Daemon):
    """    def __init__(self, pidfile):
            super().__init__(pidfile)
            self._controlPanel = None"""

    def run(self):
        logger.info("Hello from run(). Process ID:" + str(os.getpid()))
        self._controlPanel = ControlPanel()
        self._controlPanel.start()
        logger.debug("Daemon run.init complete")
        while not self.kill_now:
            self._controlPanel.process()
            time.sleep(1)
        logger.debug("exiting run() method")

    def cleanup(self, signum, signame):
        logger.info("cleanup.Process ID:" + str(os.getpid()))
        logger.info("Cleaning up because %s(%d) was received", signame, signum)
        self._controlPanel.stop()


if __name__ == "__main__":
    daemon = MyDaemon('/tmp/daemon-controlpanel.pid')
    if len(sys.argv) == 2:
        if 'start' == sys.argv[1]:
            print("Starting %s Daemon..." % sys.argv[0])
            daemon.start()
        elif 'stop' == sys.argv[1]:
            daemon.stop()
            print("Daemon stopped!")
        elif 'restart' == sys.argv[1]:
            print("restarting daemon")
            daemon.restart()
        else:
            print("Unknown command")
            sys.exit(2)
        sys.exit(0)
    else:
        print("usage: %s start|stop|restart" % sys.argv[0])
        sys.exit(2)
