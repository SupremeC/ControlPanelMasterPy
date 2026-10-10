#!/usr/bin/env python

"""
ControlPanel Daemon. Runs in the foreground under systemd (service_cp).
Opens a connection to ArduinoMega via SerialUSB.

SIGTERM/SIGINT only set a stop event. The main loop then exits and
ControlPanel.stop() runs once, on the main thread.


Related links:
=================================
# https://github.com/bakercp/PacketSerial
# https://pythonhosted.org/cobs/


"""


import signal
import sys
import threading
import logging
import os
import daemon.setup_logger as setup_logger  # noqa
from daemon.controlpanel_class import ControlPanel

logger = logging.getLogger("daemon")

LOOP_INTERVAL = 0.1  # seconds


def main() -> int:
    """Runs the control panel until SIGTERM/SIGINT. Returns the exit code."""
    stop_event = threading.Event()

    def on_signal(signum, _frame):
        logger.info("Received %s. Stopping", signal.Signals(signum).name)
        stop_event.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    logger.info("Starting. Process ID:%s", os.getpid())
    control_panel = None
    try:
        control_panel = ControlPanel()
        control_panel.start()
        logger.debug("Daemon init complete")
        while not stop_event.is_set():
            control_panel.process()
            stop_event.wait(LOOP_INTERVAL)
    except Exception:
        logger.exception("Daemon crashed")
        return 1
    finally:
        if control_panel is not None:
            control_panel.stop()
    logger.info("Daemon stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
