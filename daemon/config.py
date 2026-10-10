"""Daemon settings in one place. Paths are relative to the repo root, so
the daemon does not depend on the directory it is started from."""

from dataclasses import dataclass
from pathlib import Path

from daemon.global_variables import root_path

DAEMON_DIR = root_path / "daemon"


@dataclass(frozen=True)
class Config:
    """Settings for ControlPanel and its components."""

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
    google_token_file: Path = DAEMON_DIR / "token.json"
    google_client_secret_file: Path = (
        DAEMON_DIR
        / "client_secret_776060522090-prfipc44cc0ef87rr78rg5773an22uan.apps.googleusercontent.com.json"
    )
