"""Daemon settings in one place. Paths are relative to the repo root, so
the daemon does not depend on the directory it is started from."""

from dataclasses import dataclass
import datetime
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

    # Google Calendar. An event with this title (any case) and a time of
    # day is the wake-up alarm; without one there is no alarm.
    alarm_title: str = "wakeUpAlarm"
    calendar_update_interval: float = 60  # seconds between checks
    # Events are refetched often from this local time until today's alarm
    # has rung, so a moved or deleted alarm is seen in time; seldom otherwise.
    calendar_refetch_near_from: datetime.time = datetime.time(4, 0)
    calendar_refetch_near: float = 15 * 60  # seconds
    calendar_refetch_far: float = 2 * 60 * 60  # seconds
    # From this local time the log says whether tomorrow has an alarm.
    alarm_check_at: datetime.time = datetime.time(21, 0)

    # Morning routine
    sunrise_minutes: int = 30
    sunrise_tick_seconds: float = 2  # between frames; WLED fades in between
    # Sunrise light (see daemon/sunrise.py). Colours are RGBW; W is the
    # strips' own white LED. The end values are tuned on the real strips
    # with tools/sunrise_demo.py.
    sunrise_start_brightness: int = 1
    sunrise_end_brightness: int = 255
    # (progress, RGBW) stops before the end colour. WLED gamma-corrects
    # colours, so a mid value like G=100 shows as nearly 0: the stops
    # need higher values than they look. W comes in late and gently
    # because the white LED outshines RGB.
    sunrise_colour_stops: tuple[tuple[float, tuple[int, int, int, int]], ...] = (
        (0.0, (255, 30, 0, 0)),  # deep red
        (0.15, (255, 100, 0, 0)),  # red-orange
        (0.30, (255, 150, 10, 20)),  # orange, W starts
        (0.45, (255, 160, 30, 90)),  # amber
        (0.55, (255, 150, 40, 170)),
    )
    sunrise_end_rgbw: tuple[int, int, int, int] = (255, 140, 40, 255)  # warm white
    sunrise_white_at: float = 0.7  # share of the sunrise until warm white
    # Alarm sound, in percent of full software volume. The amp knob is
    # fixed, so this is the whole volume chain. The alarm ignores the pot
    # and the sound switch; it starts quiet and ramps up.
    alarm_volume: int = 70
    alarm_start_volume: int = 10
    alarm_ramp_seconds: float = 90
    # Not dismissed: every cycle is louder by the step, up to 100 %, until
    # the routine gives up (the lights stay on).
    alarm_cycle_seconds: float = 120
    alarm_cycle_step: int = 10
    alarm_give_up_minutes: float = 15
    # After the alarm is dismissed
    briefing_prepare_lead_minutes: float = 10  # before the alarm
    briefing_delay_seconds: float = 300  # unless the AI button comes first
    briefing_timeout_seconds: float = 300  # stop waiting for it to finish
    rering_after_seconds: float = 600  # without a second input
    rering_max: int = 2
    # Input this soon after dismissing is the same press (moment buttons
    # send press and release), not proof of being awake.
    activity_min_gap_seconds: float = 5
    # An alarm missed by up to this much (daemon restart) still rings.
    late_start_grace_minutes: int = 15

    # Secrets live in daemon/ and are gitignored (the repo is public).
    openai_key_file: Path = DAEMON_DIR / "cpanel-openai-service-account.secretkey"
    # Creating a new token.json needs a browser login with the
    # client_secret_*.json file next to it; the daemon only refreshes it.
    google_token_file: Path = DAEMON_DIR / "token.json"
