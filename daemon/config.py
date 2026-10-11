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

    # Which calendar events are mentioned (daemon/agenda.py). First
    # guesses, to be tuned: an event that started up to this long ago is
    # still mentioned, and one that lasts longer than the long-event limit
    # (or all day) only in the morning, on its first and last day.
    agenda_started_hours: float = 1
    agenda_long_event_hours: float = 8

    # School days (daemon/checkins.py). Today's first timed event whose
    # title starts with school_title (any case) is when school starts;
    # Axel leaves the travel time before it. Without one, no check-ins.
    school_title: str = "Skola"
    school_travel_minutes: float = 15
    # Spoken this many minutes before leaving; the first one is the
    # overview of the day, the others are fixed countdown texts.
    checkin_minutes: tuple[int, ...] = (30, 15, 5, 0)
    checkin_prepare_lead_minutes: float = 10  # before the overview
    # A check-in this late (daemon restart, event added late) is skipped.
    checkin_grace_minutes: float = 2
    # Check-ins ignore the pot and the master and sound switches.
    checkin_volume: int = 60

    # Night (daemon/night.py). At night_off_at the panel backlight, every
    # LED and the sockets listed (button pins) go off and the LED strips
    # go to a dim red night light; nothing is said. Until night_until a
    # daemon restart does it again and a Mega status resync re-lights
    # nothing. Inputs keep working. The bed lamp (its state is unknown,
    # the relay only pulses its toggle) and the bed socket are left alone.
    night_off_at: datetime.time = datetime.time(22, 30)
    night_until: datetime.time = datetime.time(5, 0)
    night_off_sockets: tuple[int, ...] = (68,)  # the drawer (byr�) socket
    # The same light as the WLED preset "Lowred": both segments on, no
    # effect. Set with WLED.set_both(), like the sunrise frames.
    night_strip_rgbw: tuple[int, int, int, int] = (255, 0, 34, 0)
    night_strip_brightness: int = 40  # 64 was slightly too bright (2026-10-10)
    night_strip_transition: float = 5  # seconds of fade
    night_tick_seconds: float = 30

    # Remote control (daemon/remote.py, the web API). The WLED state is
    # read on the WLED lane (up to 1.5 s) and cached; a state request
    # older than this asks for a fresh read, which a later request sees.
    wled_snapshot_max_age: float = 3  # seconds

    # Web API and page (daemon/webapi.py). LAN only, no auth: the Pi sits
    # on the home WiFi. Off in tests and tools (web_enabled False).
    web_enabled: bool = True
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    web_dir: Path = DAEMON_DIR / "web"  # the page; without it, a link to /docs
    web_command_timeout: float = 3  # seconds the HTTP thread waits for the main loop
    # Idle HTTP connections are kept this long. uvicorn's own 5 s left
    # Windows clients (the Stream Deck plugins) with half-closed sockets.
    web_keep_alive: int = 600  # seconds
    # /api/events: while a page listens, the state is compared this often
    # and sent when it changed; a keep-alive comment goes out every ping.
    web_events_interval: float = 0.5  # seconds
    web_events_ping: float = 15  # seconds
    # /api/say: text-to-speech on the panel (costs an OpenAI call each).
    say_max_chars: int = 200
    say_min_interval: float = 10  # seconds between two calls
    web_say_timeout: float = 45  # HTTP wait for synthesis and playback

    # Preset clips (daemon/presets.py): the ten audio buttons' active
    # clips and their defaults. AudioCtrl uses the same two directories
    # (hardcoded there); keep them in step. Uploads from the page are
    # converted with ffmpeg on the audio lane.
    preset_sounds_dir: Path = DAEMON_DIR / "sounds"
    preset_defaults_dir: Path = DAEMON_DIR / "systemsounds"
    preset_upload_dir: Path = DAEMON_DIR / "tmp_upload"
    preset_upload_max_bytes: int = 20 * 1024 * 1024
    preset_max_seconds: float = 60
    preset_upload_timeout: float = 40  # HTTP wait for probe + convert + replace
    ffmpeg_timeout: float = 30  # seconds for one conversion
    presets_file: Path = DAEMON_DIR / "presets.json"  # button names; gitignored

    # Speech (daemon/speech.py): local Swedish templates, the text model
    # only for the joke and the clothing advice, then text-to-speech. One
    # voice for everything, also the answers to recorded questions
    # (gpt-audio), so it must exist for both. The humour style is a key
    # of speech.STYLES; tools/speech_samples.py lets Axel pick.
    text_model: str = "gpt-5.5"
    tts_model: str = "gpt-4o-mini-tts"
    voice: str = "alloy"
    humour_style: str = "torr"
    # Silence in spoken texts: around the wake line's joke, and at a
    # free-standing dash (before a joke's punchline).
    speech_pause_seconds: float = 1.2
    speech_dash_pause_seconds: float = 1.0
    # Fixed texts (countdown) are synthesised once and kept here.
    speech_cache_dir: Path = DAEMON_DIR / "speech_cache"
    # Hand-rated wake-up jokes (daemon/jokes.py) and when each was told.
    # Gitignored. Without the pool the text model writes the joke.
    jokes_file: Path = DAEMON_DIR / "jokes.json"
    joke_state_file: Path = DAEMON_DIR / "joke_state.json"
    joke_repeat_days: int = 45

    # Weather (SMHI, see daemon/weather.py). Parts of the day in local
    # hours, start to end; a part gets the forecast steps ending after its
    # start and up to its end.
    weather_day_parts: tuple[tuple[str, int, int], ...] = (
        ("morgon", 6, 9),
        ("förmiddag", 9, 12),
        ("eftermiddag", 12, 18),
        ("kväll", 18, 22),
    )
    # Before this time the rest of today is described; from then on the
    # rest of this evening and tomorrow until weather_tomorrow_until.
    weather_evening_from: datetime.time = datetime.time(17, 0)
    weather_tomorrow_until: int = 18  # hour
    # Home is "location" in personal.json; without it, central Stockholm.
    weather_default_location: tuple[float, float] = (59.3293, 18.0686)
    smhi_timeout: float = 10  # seconds per request
    weather_fresh_minutes: float = 30  # refetch an older forecast
    # When SMHI fails, an older forecast is used up to this age.
    weather_stale_hours: float = 6
    # Keeps the forecast fresh and the hourly temperatures complete, so
    # "colder than yesterday" works even on days without a briefing.
    weather_refresh_minutes: float = 60
    # Last forecast and recent hourly temperatures. Gitignored.
    weather_state_file: Path = DAEMON_DIR / "weather_state.json"

    # Secrets live in daemon/ and are gitignored (the repo is public).
    openai_key_file: Path = DAEMON_DIR / "cpanel-openai-service-account.secretkey"
    # Creating a new token.json needs a browser login with the
    # client_secret_*.json file next to it; the daemon only refreshes it.
    google_token_file: Path = DAEMON_DIR / "token.json"
    # Name and birthday of the listener (personal.example.json shows the
    # format). Gitignored: never commit it.
    personal_file: Path = DAEMON_DIR / "personal.json"
