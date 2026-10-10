"""Configures built-in logger"""

import sys
import logging


def configure_logging(level: int = logging.DEBUG) -> None:
    """Sends all log records to stdout (journald under systemd).
    Call once, from main()."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s\t%(levelname)s\t%(funcName)10s()\t%(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
