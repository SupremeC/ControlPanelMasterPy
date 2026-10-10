"""Daemon settings in one place. Paths are relative to the repo root, so
the daemon does not depend on the directory it is started from."""

from dataclasses import dataclass
import logging
from pathlib import Path

from daemon.global_variables import root_path

DAEMON_DIR = root_path / "daemon"


@dataclass(frozen=True)
class Config:
    """Settings for ControlPanel and its components."""

    # DEBUG adds every status packet and recording step.
    log_level: int = logging.INFO

    # Arduino Mega over USB. The port is found by manufacturer name.
    mega_baud: int = 115200
    mega_reconnect_interval: float = 5  # seconds between port retries
    hello_interval: float = 120  # seconds between HELLO packets
    # A Mega with its own power supply keeps running when the USB cable is
    # unplugged, so a reconnect does not always produce a BOOTMEGA. If none
    # arrives this long after a (re)connect, ask the Mega for its status.
    # A rebooting Mega needs about 10 s before it sends BOOTMEGA.
    resync_after_connect: float = 15  # seconds

    # WLED on the Pi's UART. The baud rate must match WLED's setting.
    wled_port: str = "/dev/serial0"
    wled_baud: int = 460800

    calendar_update_interval: float = 60  # seconds

    # Secrets live in daemon/ and are gitignored (the repo is public).
    openai_key_file: Path = DAEMON_DIR / "cpanel-openai-service-account.secretkey"
    # Creating a new token.json needs a browser login with the
    # client_secret_*.json file next to it; the daemon only refreshes it.
    google_token_file: Path = DAEMON_DIR / "token.json"
