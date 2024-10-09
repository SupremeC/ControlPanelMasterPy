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


# pylint: disable=W0611
import sys
import time
import logging
import os
import daemon.setup_logger as setup_logger  # noqa
from daemon.daemon_super_class import DaemonSC
from daemon.controlpanel_class import ControlPanel

logger = logging.getLogger("daemon")


class MyDaemon(DaemonSC):
    """def __init__(self, pidfile):
    super().__init__(pidfile)
    self._controlPanel = None"""

    _control_panel: ControlPanel

    def run(self):
        logger.info("Hello from run(). Process ID:%s", str(os.getpid()))
        self._control_panel = ControlPanel()
        self._control_panel.start()
        logger.debug("Daemon run.init complete")
        while not self.kill_now:
            self._control_panel.process()
            time.sleep(0.1)
        logger.debug("exiting run() method")
        self._control_panel.stop()

    def cleanup(self, signum, signame):
        logger.info("cleanup.Process ID:%s", str(os.getpid()))
        logger.info("Cleaning up because %s(%d) was received", signame, signum)
        self._control_panel.stop()


if __name__ == "__main__":
    daemon = MyDaemon("/tmp/daemon-controlpanel.pid")
    if len(sys.argv) != 0:
        print("no args. Assuming syncronious 'start'")
        daemon.run()
    elif len(sys.argv) == 2:
        if "start" == sys.argv[1]:
            print(f"Starting {sys.argv[0]} Daemon...")
            daemon.start()
        elif "stop" == sys.argv[1]:
            daemon.stop()
            print("Daemon stopped!")
        elif "restart" == sys.argv[1]:
            print("restarting daemon")
            daemon.restart()
        elif "bash" == sys.argv[1]:
            daemon.run()
        else:
            print("Unknown command")
            sys.exit(2)
        sys.exit(0)
    else:
        print(f"usage: {sys.argv[0]} start|stop|restart")
        sys.exit(2)
