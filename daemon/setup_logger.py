"""Configures built-in logger"""

import sys
import logging

# Third-party loggers and the most they may log. At DEBUG, openai logs
# whole request bodies, including the base64 recordings sent to it.
QUIET_LOGGERS = {
    "openai": logging.WARNING,
    "httpcore": logging.WARNING,
    "httpx": logging.INFO,  # one "HTTP Request: POST ... 200 OK" line per call
    "googleapiclient": logging.WARNING,
    "pydub": logging.WARNING,
    "urllib3": logging.WARNING,
    # The web API: webapi.py logs its own start line; access logging is off.
    "uvicorn": logging.WARNING,
    "uvicorn.error": logging.WARNING,
    "uvicorn.access": logging.WARNING,
}


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
    for name, quiet_level in QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(quiet_level)
