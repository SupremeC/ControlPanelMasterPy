#!/usr/bin/env python

"""
ControlPanel Daemon. Runs in the foreground under systemd (service_cp).
Opens a connection to ArduinoMega via SerialUSB.

SIGTERM/SIGINT only set a stop event. The main loop then exits and
ControlPanel.stop() runs once, on the main thread.

SIGUSR1 runs the morning routine compressed, alarm 2 min from now:
    sudo systemctl kill -s USR1 service_cp


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

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # before pygame is imported

from daemon.config import Config  # noqa: E402
from daemon.setup_logger import configure_logging  # noqa: E402
from daemon.controlpanel_class import ControlPanel  # noqa: E402
from daemon.events import MorningTest  # noqa: E402

logger = logging.getLogger("daemon")


def main() -> int:
    """Runs the control panel until SIGTERM/SIGINT. Returns the exit code."""
    config = Config()
    configure_logging(config.log_level)
    stop_event = threading.Event()

    def on_signal(signum, _frame):
        logger.info("Received %s. Stopping", signal.Signals(signum).name)
        stop_event.set()

    control_panel = None

    def on_usr1(_signum, _frame):
        if control_panel is not None:
            control_panel.post(MorningTest())

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGUSR1, on_usr1)

    logger.info("Starting. Process ID:%s", os.getpid())
    try:
        control_panel = ControlPanel(config)
        control_panel.start()
        logger.debug("Daemon init complete")
        while not stop_event.is_set():
            control_panel.process()  # waits up to 0.1 s for an event
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
