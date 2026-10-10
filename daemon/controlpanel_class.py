"""ControlPanel_Class"""

from concurrent.futures import Future
from contextlib import ExitStack
import dataclasses
import datetime
import heapq
import itertools
import logging
from queue import Empty, Full, Queue
import random
import time
from typing import Any, Callable, List

from .component import Component
from .config import Config
from .events import (
    CalendarAlarm,
    Command,
    JobDone,
    MorningTest,
    NightTest,
    PlaybackChanged,
)
from .remote import Remote
from .workers import Workers
from .wled import WLED, WledStateSnapshot
from daemon.audio_ctrl import (
    ALARM_FADEOUT_MS,
    AudioCtrl,
    SysAudioEvent as aevent,
    EffectType,
)
from .ctrls import CtrlNotFoundException, HwCtrls, LEDCtrl
from .packet import HWEvent, Packet, BlinkTarget  # noqa
from daemon.packet_serial import PacketSerial
from daemon.openaiWrapper import OpenAiWrapper
from daemon.gCalender import TIMEZONE, Calender
from daemon.morning import MorningRoutine, State as MorningState
from daemon.checkins import Checkins
from daemon.night import NightOff
from daemon.speech import Speech, countdown_text, school_event
from daemon import sunrise
from daemon.weather_service import WeatherReport, WeatherService

logger = logging.getLogger("daemon.ctrlPanel")
# The serial buffer of Arduino is increased to 256 bytes (if it works)
# it was changed in platformio config file in VSCode
# COBS adds an additional stop byte as well as '0' escaping, so lets assume each packet is 10 bytes.
# 256 / 10bytes => 25 packets until buffer is full.
# average arduino loop duration is ~25ms. In theory, that allows us
# to send (1000/25ms)*25packets = 1000 packets per second.
# The writer thread paces packets (one per 50 ms), which is what protects
# the Mega's buffer. This queue is only the Pi-side backlog and must hold
# a whole "all LEDs on/off" burst (57 packets).
MAX_PACKETS_IN_SEND_QUEUE = 200
MAX_EVENT_WAIT = 0.1  # seconds the main loop waits for an event
DEMO_STEP_INTERVAL = 0.1  # seconds between LED toggles in demo mode
BRIEFING_RETRY_DELAY = 60  # seconds before a failed briefing is generated again
MORNING_TEST_LEAD = 120  # seconds from SIGUSR1 to the test alarm
# The test also runs the check-ins, a tenth of the real offsets, with the
# leave time this long after the test alarm.
CHECKIN_TEST_SCALE = 0.1
CHECKIN_TEST_LEAVE = 8 * 60  # seconds after the test alarm
WEATHER_FIRST_REFRESH = 30  # seconds after start; then every weather_refresh_minutes
# Silence between the alarm, the chimes and speech, so they do not melt
# together. The "off" chime waits for the alarm's fade-out plus the gap.
CHIME_GAP = 0.5  # seconds
OFF_CHIME_DELAY = ALARM_FADEOUT_MS / 1000 + CHIME_GAP
BED_LAMP_PULSE = 0.1  # seconds the bed lamp relay is pulsed
EFFECT_BUTTONS = {
    17: EffectType.BITCRUSH,
    18: EffectType.PHASER,
    19: EffectType.REVERSE,
    22: EffectType.TIMESTRETCH,
    23: EffectType.PITCHLOWER,
    24: EffectType.PITCHHIGHER,
    25: EffectType.TIMECOMPRESS,
    26: EffectType.REVERB,
}


class ControlPanel:
    """Master class (besides controlPanelDaemon of course)

    Everything that changes panel state runs on the main thread, one event
    at a time (see process()). Other threads only post events: the serial
    reader posts Packets, the calendar posts CalendarAlarm, the audio
    monitor posts PlaybackChanged, and background jobs post JobDone.

    The morning routine (daemon/morning.py) gets the calendar's alarm and
    sees every switch input first, even with the master switch off, so
    the alarm always rings and can always be dismissed. The check-ins
    (daemon/checkins.py) speak before leaving for school; what is said
    comes from daemon/speech.py. The night-off (daemon/night.py) turns
    the lights off at 22:30 and keeps a status resync from re-lighting
    them until 05:00. Other threads (the web API) change the panel only
    through request(): a Command handled here by the Remote actions
    (daemon/remote.py).
    """

    demo_on: bool = False

    def __init__(self, config: Config | None = None):
        self._config = config or Config()
        self._last_sent_hello: datetime.datetime = None
        self._last_received_hello: datetime.datetime = None
        self._synced_connection: float | None = None
        self._ctrls: HwCtrls = HwCtrls()
        self._packet_sendqueue: Queue = Queue(MAX_PACKETS_IN_SEND_QUEUE)
        self._events: Queue = Queue()
        self._pserial: PacketSerial = PacketSerial(
            self._events,
            self._packet_sendqueue,
            baudrate=self._config.mega_baud,
            reconnect_interval=self._config.mega_reconnect_interval,
        )
        self._timers: list = []
        self._timer_seq = itertools.count()
        # One thread per lane, so jobs in a lane run in order.
        self._audio_jobs = Workers("audio-job")
        self._ai_jobs = Workers("ai-job")
        self._wled_jobs = Workers("wled-job")
        self._effect_job: Future | None = None
        self._ai_job: Future | None = None
        self._demo_leds: list = []
        self._next_demo_step = 0.0
        self._stopped: bool = False
        self._components_stack = ExitStack()
        self.demo_on: bool = False
        self.btnLeds: bool = True
        self.cal = Calender(
            lambda alarm: self._events.put(CalendarAlarm(alarm)),
            token_file=self._config.google_token_file,
            update_interval=self._config.calendar_update_interval,
            config=self._config,
        )
        self.ai = OpenAiWrapper(
            key_path=self._config.openai_key_file,
            personal_path=self._config.personal_file,
            config=self._config,
        )
        self.speech = Speech(self.ai, self._config)
        self._audioctrl: AudioCtrl = AudioCtrl(
            lambda playing: self._events.put(PlaybackChanged(playing))
        )
        self.wled_instance = WLED(self._config.wled_port, self._config.wled_baud)
        # Used on the AI lane only (blocking HTTP, not thread-safe).
        self.weather = WeatherService(self._config)
        # Written and read only on the AI lane, so jobs see it in order.
        self._briefing_audio: bytes | None = None
        self._briefing_retried = False
        # The test routine (SIGUSR1) replaces the real one while it runs.
        self._morning_cfg = self._config
        self._real_morning = self._new_morning(self._config)
        self.morning = self._real_morning
        # Overview audio per leave time; written and read on the AI lane.
        self._overview_audio: dict[datetime.datetime, bytes] = {}
        self.checkins = Checkins(
            _CheckinActions(self),
            lambda: datetime.datetime.now(TIMEZONE),
            self.call_later,
            self._leave_time,
            self._config,
        )
        self._test_checkins: Checkins | None = None
        self.night = NightOff(
            _NightActions(self),
            lambda: datetime.datetime.now(TIMEZONE),
            self.call_later,
            self._config,
        )
        # Set by the playback monitor's PlaybackChanged events.
        self._audio_playing = False
        # Last WLED state read, when it was asked for, and the read job.
        self._wled_snapshot: WledStateSnapshot | None = None
        self._wled_snapshot_at: float = 0.0
        self._wled_snapshot_job: Future | None = None
        self.remote = Remote(self)

    def _new_morning(self, config: Config) -> MorningRoutine:
        return MorningRoutine(
            _MorningActions(self),
            lambda: datetime.datetime.now(TIMEZONE),
            self.call_later,
            config,
        )

    def post(self, event: Any) -> None:
        """Queues an event for the main thread. Safe from any thread and
        from a signal handler."""
        self._events.put(event)

    def request(self, name: str, **kwargs: Any) -> Future:
        """Runs the Remote command `name` on the main thread. Safe from
        any thread. The Future gets the command's result, or its
        exception: KeyError for an unknown command, ValueError when the
        panel refuses it."""
        future: Future = Future()
        self._events.put(Command(name, kwargs, future))
        return future

    def _run_command(self, cmd: Command) -> None:
        if cmd.name not in Remote.READ_ONLY:
            logger.info("remote: %s %s", cmd.name, cmd.kwargs)
        try:
            result = self.remote.command(cmd.name)(**cmd.kwargs)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("remote: %s refused: %r", cmd.name, e)
            cmd.future.set_exception(e)
            return
        except Exception as e:
            logger.exception("remote: %s failed", cmd.name)
            cmd.future.set_exception(e)
            return
        if isinstance(result, Future):
            result.add_done_callback(lambda done: _pass_on(done, cmd.future))
        else:
            cmd.future.set_result(result)

    def wled_snapshot(self) -> WledStateSnapshot | None:
        """The last WLED state read, or None. When it is older than
        config.wled_snapshot_max_age a fresh read is started on the WLED
        lane; a later call gets it. Never blocks."""
        age = time.monotonic() - self._wled_snapshot_at
        if age > self._config.wled_snapshot_max_age and not self._is_running(
            self._wled_snapshot_job
        ):
            requested_at = time.monotonic()

            def store(snapshot: WledStateSnapshot) -> None:
                self._wled_snapshot = snapshot
                self._wled_snapshot_at = requested_at

            self._wled_snapshot_job = self._run_job(
                self._wled_jobs,
                "wled-snapshot",
                self.wled_instance.read_state,
                on_done=store,
                on_error=lambda _error: None,  # already logged; no sound
            )
        return self._wled_snapshot

    @property
    def wled_snapshot_at(self) -> float:
        """time.monotonic() when the current snapshot was asked for."""
        return self._wled_snapshot_at

    def invalidate_wled_snapshot(self) -> None:
        """After a WLED command: the next wled_snapshot() reads again."""
        self._wled_snapshot_at = 0.0

    def _components(self) -> list[tuple[str, Component]]:
        """Components in start order. The job lanes come last so they
        stop first, before the audio and WLED their jobs use."""
        return [
            ("serial", self._pserial),
            ("wled", self.wled_instance),
            ("audio", self._audioctrl),
            ("calendar", self.cal),
            ("audio jobs", self._audio_jobs),
            ("ai jobs", self._ai_jobs),
            ("wled jobs", self._wled_jobs),
        ]

    def start(self):
        """Starts all components. If one fails to start, the ones
        already started are stopped again and the error is raised."""
        with ExitStack() as stack:
            for name, component in self._components():
                logger.debug("Starting %s", name)
                component.start()
                stack.callback(self._stop_component, name, component)
            self._components_stack = stack.pop_all()
        self.reset()
        self._real_morning.start()
        self.checkins.start()
        self.night.start()
        self.call_later(WEATHER_FIRST_REFRESH, self._weather_refresh)

    def stop(self):
        """Stops all started components in reverse order.
        Safe to call more than once."""
        if self._stopped:
            return
        self._stopped = True
        logger.info("ControlPanel stopping...")
        self.demo_on = False
        self._components_stack.close()
        logger.info("ControlPanel stopped")

    @staticmethod
    def _stop_component(name: str, component: Component) -> None:
        try:
            component.stop()
        except Exception:
            logger.exception("Stopping %s failed", name)

    def process(self, max_wait: float = MAX_EVENT_WAIT) -> None:
        """Handles the next event, then due timers and housekeeping.
        Waits at most max_wait seconds for an event (less if a timer is
        due sooner). Call it in a loop on the main thread."""
        try:
            event = self._events.get(timeout=self._wait_time(max_wait))
        except Empty:
            pass
        else:
            self._dispatch(event)
        self._run_due_timers()
        try:
            self._tick()
        except Exception:
            logger.exception("Housekeeping failed")

    def _dispatch(self, event: Any) -> None:
        """Handles one event. The only place handler errors are caught."""
        try:
            if isinstance(event, Packet):
                self.__act(event)
            elif isinstance(event, JobDone):
                self._job_done(event)
            elif isinstance(event, PlaybackChanged):
                self.speakerLeds(event.playing)
            elif isinstance(event, CalendarAlarm):
                self._real_morning.set_alarm(event.alarm)
            elif isinstance(event, MorningTest):
                self.start_morning_test()
            elif isinstance(event, NightTest):
                logger.info("night test: lights off now")
                self._night_off()
            elif isinstance(event, Command):
                self._run_command(event)
            else:
                logger.warning("Unknown event %r", event)
        except Exception:
            logger.exception("Handling %r failed", event)

    def _tick(self) -> None:
        self._resync_if_needed()
        self._demo_step()
        self._end_morning_test_if_done()
        self._end_checkin_test_if_done()
        if self.time_to_send_hello():
            self._pserial.send_hello()
            self._last_sent_hello = datetime.datetime.now()

    def call_later(self, delay: float, fn: Callable[..., None], *args: Any) -> None:
        """Runs fn(*args) on the main thread after delay seconds."""
        due = time.monotonic() + delay
        heapq.heappush(self._timers, (due, next(self._timer_seq), fn, args))

    def _wait_time(self, max_wait: float) -> float:
        if not self._timers:
            return max_wait
        return max(0.0, min(max_wait, self._timers[0][0] - time.monotonic()))

    def _run_due_timers(self) -> None:
        now = time.monotonic()
        while self._timers and self._timers[0][0] <= now:
            _, _, fn, args = heapq.heappop(self._timers)
            try:
                fn(*args)
            except Exception:
                logger.exception("Timer %s failed", fn)

    def _run_job(
        self,
        lane: Workers,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> Future:
        """Runs fn(*args) on a job lane. When it finishes, on_done(result)
        or on_error(exception) runs on the main thread. Without on_error a
        failure plays the FAILED sound."""
        future = lane.submit(fn, *args)
        future.add_done_callback(
            lambda f: self._events.put(JobDone(name, f, on_done, on_error))
        )
        return future

    def _job_done(self, event: JobDone) -> None:
        if event.future.cancelled():
            return
        error = event.future.exception()
        if error is not None:
            logger.error("Job %s failed", event.name, exc_info=error)
            if event.on_error is not None:
                event.on_error(error)
            else:
                self._audioctrl.sysaudio_play(aevent.FAILED)
            return
        if event.on_done is not None:
            event.on_done(event.future.result())

    @staticmethod
    def _is_running(job: Future | None) -> bool:
        return job is not None and not job.done()

    def _resync_if_needed(self) -> None:
        """Requests the Mega's status once per connection if no BOOTMEGA
        arrived within config.resync_after_connect seconds of connecting."""
        connected_at = self._pserial.connected_at
        if connected_at is None or connected_at == self._synced_connection:
            return
        if time.monotonic() - connected_at < self._config.resync_after_connect:
            return
        self._synced_connection = connected_at
        logger.info("No BOOTMEGA since the Mega connected. Requesting status")
        self.reset()

    def __act(self, packet: Packet) -> None:
        if packet.hw_event == HWEvent.BOOTMEGA:
            logger.info("Received BOOTMEGA packet. Mega was (re)booted")
            self._synced_connection = self._pserial.connected_at
            self.reset()
        elif packet.hw_event == HWEvent.HELLO:
            self._last_received_hello = datetime.datetime.now()
        elif packet.hw_event == HWEvent.RESET:
            logger.info("Received RESET packet. starting reset routine")
            self.reset()
        elif packet.hw_event == HWEvent.STATUS:
            # Status packet. Target == Switch pin.
            logger.debug("Status: pin %d = %d", packet.target, packet.val)
            self._switch_status_changed(packet, no_action=True)
        elif packet.hw_event == HWEvent.SWITCH:
            # A switch has changed status. React
            self._switch_status_changed(packet)
        elif packet.hw_event == HWEvent.UNDEFINED:
            logger.warning("Received undefined package: %s", packet)

    def _switch_status_changed(self, packet: Packet, no_action: bool = False) -> Packet:
        """Handles button logic"""
        try:
            p_tosend = []
            mastersw = self._ctrls.get_ctrl_by_name("masterSw")
            inputsw = self._ctrls.get_ctrl_by_name("InputsSw")
            soundsw = self._ctrls.get_ctrl_by_name("SoundSw")

            # Before the master switch check: the alarm can be dismissed
            # with the panel switched off.
            if not no_action and self.morning.on_input(packet.target, packet.val):
                self._track_main_switches(packet)
                return

            # A status resync at night (daemon restart, Mega reboot) keeps
            # the flip states but re-lights nothing: the backlight stays
            # dark and an aux flip that is up does not blink its button.
            if no_action and self.night.active:
                if packet.target == 14:
                    self._ctrls.get_ctrl_by_name("BacklightSw").state = bool(packet.val)
                    return
                if 38 <= packet.target <= 41 and packet.val == 1:
                    self._ctrls.get_ctrl(packet.target).state = True
                    return

            if packet.target == 12:  # MainSwitch
                mastersw.state = bool(packet.val)
                if mastersw.state:
                    self._audioctrl.sysaudio_play(aevent.SYSTEM_ON)
                else:
                    p_tosend.extend(self._ctrls.set_all_leds(False))
                    # Reads WLED's state first (up to 1.5 s): not on the main thread.
                    self._run_job(
                        self._wled_jobs,
                        "wled-off",
                        self.wled_instance.set_wled_state,
                        False,
                    )
                    self._audioctrl.sysaudio_play(aevent.SYSTEM_OFF)
                    self.send_packets(p_tosend)
                    return
            if packet.target == inputsw.pin:  # Inputs on / off
                p_tosend.extend(inputsw.set_state(bool(packet.val)))
            if packet.target == 14:  # Backlight
                self.cp_bg_lights(packet)
            if packet.target == soundsw.pin:  # Sound on / off
                p_tosend.extend(soundsw.set_state(bool(packet.val)))
                self._audioctrl.enable_sound(bool(packet.val))

            self.send_packets(p_tosend)
            p_tosend.clear()

            if self.demo_on and packet.target not in range(54, 63):  # analog ctrls
                self.demo_on = False
                return
            if not mastersw.state or not inputsw.state:
                return

            if packet.target >= 2 and packet.target <= 11 and packet.val == 1:
                self.send_packets(
                    self._ctrls.get_slavectrl(packet.target).leds[0].blink()
                )
                self._audioctrl.recsaved_play(packet.target)
            if packet.target >= 2 and packet.target <= 11 and packet.val == 100:
                self._audioctrl.save_rec_to_hwswitch(packet.target)
                self.send_packets(
                    self._ctrls.get_slavectrl(packet.target).leds[0].blink(True)
                )
                self._audioctrl.sysaudio_play(aevent.REC_SAVED)
                return
            if packet.target >= 2 and packet.target <= 11 and packet.val == 200:
                # Restore Audio OR Demo
                if packet.target == 3:
                    self.btnLeds = not self.btnLeds
                    self.send_packets(self._ctrls.set_all_leds(self.btnLeds))
                if packet.target == 5:
                    self.demo_on = not self.demo_on
                    if self.demo_on:
                        self._audioctrl.sysaudio_play(aevent.DEMOMODE)
                        self._demo_leds = self._ctrls._get_all_leds()
                else:
                    self._audioctrl.restore_original_audio(packet.target)
                return
            if packet.target in [17, 18, 19, 22, 23, 24, 25, 26]:  # Effect btns
                if self._audioctrl.current_filepath is None:
                    self._audioctrl.sysaudio_play(aevent.FAILED)
                else:
                    self.apply_soundeffect(packet)
                    self.send_packets(
                        Packet(HWEvent.BLINK3ENDHIGH, BlinkTarget.AUDIO_PRESETBTNS, 2)
                    )
                return
            if packet.target == 27 and packet.val:
                self._audioctrl.prepare_recording()
                self._run_job(
                    self._audio_jobs,
                    "rec-start",
                    self._audioctrl.start_recording,
                    on_done=self._recording_started,
                )
                return
            if packet.target == 27 and packet.val == 0:
                self._run_job(
                    self._audio_jobs,
                    "rec-stop",
                    self._audioctrl.stop_recording,
                    on_done=self._recording_stopped,
                )
                return
            if packet.target >= 66 and packet.target <= 69:
                self._set_relays(packet, is_safetyctrl=False)
                return
            if packet.target >= 32 and packet.target <= 37:
                self.ledstrip_control(packet)
                return
            if packet.target >= 38 and packet.target <= 41:
                self._set_relays(packet, is_safetyctrl=True)
                return
            if packet.target >= 54 and packet.target <= 61:  # ledtrip_analog
                # analog controls (A0 == 52, A1=53, ...)
                self.ledstrip_control(packet)
                return
            if packet.target == 62:
                self.audio_volume(
                    self.map_value(val=packet.val, out_min=0, out_max=100)
                )
                return
        except Exception:
            logger.error(packet)
            logger.exception("exception in function switch_status_changed()")
            self._audioctrl.sysaudio_play(aevent.FAILED)
        finally:
            if not no_action:
                self.send_packets(p_tosend)

    def _track_main_switches(self, packet: Packet) -> None:
        """The morning routine used this input: keep the master, inputs
        and sound switch states in step, without their sounds and actions."""
        if packet.target == 12:
            self._ctrls.get_ctrl_by_name("masterSw").state = bool(packet.val)
            return
        for name in ("InputsSw", "SoundSw"):
            ctrl = self._ctrls.get_ctrl_by_name(name)
            if packet.target == ctrl.pin:
                self.send_packets(ctrl.set_state(bool(packet.val)))
                if name == "SoundSw":
                    self._audioctrl.enable_sound(bool(packet.val))

    def apply_soundeffect(self, packet: Packet):
        btn = self._ctrls.get_ctrl(packet.target)
        if self._is_running(self._effect_job):
            logger.warning("An effect is already being applied. NOOP")
        else:
            self._effect_job = self._run_job(
                self._audio_jobs,
                "effect",
                self._audioctrl.render_effect,
                self._audioctrl.current_filepath,
                EFFECT_BUTTONS[packet.target],
                on_done=self._audioctrl.effect_done,
            )
        self.send_packets(btn.leds[0].blink())

    def _recording_started(self, started: bool) -> None:
        if not started:
            self._audioctrl.sysaudio_play(aevent.REC_COULD_NOT_REC)

    def _recording_stopped(self, filename: str | None) -> None:
        self._audioctrl.recording_stopped(filename)
        self._audioctrl.sysaudio_play(aevent.REC_STOPPED)
        ai_ctrl = self._ctrls.get_slavectrl(69)
        self.send_packets(ai_ctrl.leds[0].blink(True))
        self.send_packets(Packet(HWEvent.BLINK3ENDHIGH, BlinkTarget.EFFECT_BTNS, 2))
        self.send_packets(
            Packet(HWEvent.BLINK3ENDHIGH, BlinkTarget.AUDIO_PRESETBTNS, 2)
        )
        self._audioctrl._play_tmp_rec()

    def _demo_step(self) -> None:
        """Toggles a random LED every DEMO_STEP_INTERVAL while demo mode is on."""
        if not self.demo_on or not self._demo_leds:
            return
        now = time.monotonic()
        if now < self._next_demo_step:
            return
        self._next_demo_step = now + DEMO_STEP_INTERVAL
        rnd_item = random.choice(self._demo_leds)
        self.send_packets(rnd_item.set_led_state(not rnd_item.state))

    def cp_bg_lights(self, packet: Packet) -> None:
        """background light ON/OFF"""
        if packet.target == 14:
            ctrl = self._ctrls.get_ctrl_by_name("BacklightSw")
            relay = self._ctrls.get_ctrl_by_name("BacklightRelay")
            if packet.val:
                self._audioctrl.sysaudio_play(aevent.BG_LIGHT_ON)
            else:
                self._audioctrl.sysaudio_play(aevent.BG_LIGHT_OFF)

            relay.set_state(bool(packet.val))
            send = []
            send = ctrl.set_state(packet.val)
            send.append(Packet(HWEvent.RELAY, relay.pin, 1 if packet.val == 0 else 0))
            if ctrl.quick_state_change:
                logger.info(
                    "All non-indicator LEDs ON"
                    if relay.state
                    else "All non-indicator LEDs OFF"
                )
                send.extend(self._ctrls.set_all_nonindicatorleds(relay.state))
            self.send_packets(send)

    def _night_off(self, night_light: bool = True) -> None:
        """Lights off for the night, silently: every LED (and any running
        LED sequence), the backlight and the sockets in night_off_sockets;
        the strips go to the dim red night light unless the morning
        routine owns them. The bed lamp and the bed socket are left
        alone. Not through cp_bg_lights()/_set_relays(): those play.
        With night_light False the strips are not touched (Remote.all_off
        turns them off itself)."""
        cfg = self._config
        self.demo_on = False
        packets = self._ctrls.set_all_leds(False)
        for target in BlinkTarget:
            packets.append(Packet(HWEvent.BLINKFOREVER, target, 0))
        relay = self._ctrls.get_ctrl_by_name("BacklightRelay")
        relay.set_state(False)
        packets.append(Packet(HWEvent.RELAY, relay.pin, 1))  # active-low
        for pin in cfg.night_off_sockets:
            packets.extend(self._ctrls.get_slavectrl(pin).set_state(False))
        self.send_packets(packets)
        if not night_light:
            return
        if self.morning.state in (
            MorningState.SUNRISE, MorningState.WAITING, MorningState.RINGING
        ):
            logger.info("night: the strips belong to the morning routine, left alone")
            return
        self.wled_instance.set_both(
            cfg.night_strip_brightness,
            cfg.night_strip_rgbw,
            transition=cfg.night_strip_transition,
        )

    def audio_volume(self, new_vol: int = None) -> None:
        """Clamps volume to 0-100, and sets master volume"""
        vol = LEDCtrl.clamp(new_vol, 0, 100)
        return self._audioctrl.set_volume(vol)

    def _set_relays(self, packet: Packet, is_safetyctrl: bool = False):
        try:
            if is_safetyctrl:
                flipsw = self._ctrls.get_ctrl(packet.target)
                new_state = bool(packet.val)
                if new_state:
                    self.send_packets(flipsw.slaves[0].leds[0].blink(True))
                    pass
                else:
                    if packet.target == 38:  # Bed lamp
                        lamp = flipsw.slaves[0]
                        self.send_packets(lamp.set_state(True))
                        self.call_later(
                            BED_LAMP_PULSE,
                            lambda: self.send_packets(lamp.set_state(False)),
                        )
                    else:
                        # turn off slave relay
                        self.send_packets(flipsw.slaves[0].set_state(False))
                self._audioctrl.sysaudio_play(aevent.FLIP_SWITCH)
                flipsw.set_state(new_state)
            else:
                btn = self._ctrls.get_slavectrl(packet.target)
                if btn.parent.state:
                    if btn.pin == 69 and self._audioctrl.current_filepath is None:
                        self.ai_talk(btn, False)
                    elif btn.pin == 69 and self._audioctrl.current_filepath is not None:
                        self.ai_talk(btn, True)
                    else:
                        self._audioctrl.sysaudio_play(aevent.BTN_CLICKED)
                        new_state = packet.val if packet.target == 67 else not btn.state
                        self.send_packets(btn.set_state(new_state))

        except Full:
            logger.exception("Sendqueue was full. Packet(s) could not be sent")
            self._audioctrl.sysaudio_play(aevent.FAILED)
        except CtrlNotFoundException:
            logger.exception("Ctrl not found")
            raise

    def ai_talk(self, btn, audio_call: bool) -> None:
        """AI button: asks the recorded question (audio_call) or tells
        today's events. The button blinks until the answer has played."""
        if self._is_running(self._ai_job):
            logger.warning("AI is still busy. Ignoring the AI button")
            return
        self.send_packets(btn.leds[0].blink(forever=True))
        if audio_call:
            job = (self._ask_ai, self._audioctrl.current_filepath)
        else:
            job = (self._tell_upcoming_events,)

        def failed(_error: BaseException) -> None:
            self._audioctrl.sysaudio_play(aevent.FAILED)
            self.send_packets(btn.leds[0].blink_stop())

        self._ai_job = self._run_job(
            self._ai_jobs,
            "ai",
            *job,
            on_done=lambda _result: self.send_packets(btn.leds[0].blink_stop()),
            on_error=failed,
        )

    # ---- morning routine ------------------------------------------------

    def _briefing_prepare(self, retry: bool = False) -> None:
        """Generates the briefing on the AI lane, ahead of time."""
        if not retry:
            self._briefing_retried = False

        def failed(_error: BaseException) -> None:
            # Already logged. Quietly: this runs before the alarm.
            if not self._briefing_retried:
                self._briefing_retried = True
                self.call_later(BRIEFING_RETRY_DELAY, self._briefing_prepare, True)

        self._run_job(
            self._ai_jobs, "briefing-prepare", self._prepare_briefing, on_error=failed
        )

    def _briefing_play(self) -> None:
        """Chime, then the briefing, on the AI lane. Tells the routine
        when it is over, whether it played or not."""
        routine = self.morning
        self._ai_job = self._run_job(
            self._ai_jobs,
            "briefing",
            self._play_briefing,
            on_done=lambda _result: routine.briefing_finished(),
            on_error=lambda _error: routine.briefing_finished(),
        )

    def start_morning_test(self) -> None:
        """Runs the routine compressed: alarm in MORNING_TEST_LEAD seconds,
        a 1 min sunrise and the other times a tenth. The real routine
        keeps following the calendar meanwhile."""
        busy = self._real_morning.state not in (MorningState.IDLE, MorningState.ARMED)
        if self.morning is not self._real_morning or busy:
            logger.warning("morning test: a morning routine is running. Ignored")
            return
        cfg = self._config
        test_cfg = dataclasses.replace(
            cfg,
            sunrise_minutes=1,
            alarm_ramp_seconds=cfg.alarm_ramp_seconds / 10,
            alarm_cycle_seconds=cfg.alarm_cycle_seconds / 10,
            alarm_give_up_minutes=cfg.alarm_give_up_minutes / 10,
            briefing_prepare_lead_minutes=1,
            briefing_delay_seconds=cfg.briefing_delay_seconds / 10,
            rering_after_seconds=cfg.rering_after_seconds / 10,
            late_start_grace_minutes=cfg.late_start_grace_minutes / 10,
        )
        alarm = datetime.datetime.now(TIMEZONE) + datetime.timedelta(
            seconds=MORNING_TEST_LEAD
        )
        logger.info("morning test: alarm at %s, times compressed", f"{alarm:%H:%M:%S}")
        self._morning_cfg = test_cfg
        self.morning = self._new_morning(test_cfg)
        self.morning.start()
        self.morning.set_alarm(alarm)
        if self._test_checkins is None:
            leave = alarm + datetime.timedelta(seconds=CHECKIN_TEST_LEAVE)
            logger.info("check-in test: leave at %s, times compressed", f"{leave:%H:%M:%S}")
            self._test_checkins = Checkins(
                _CheckinActions(self),
                lambda: datetime.datetime.now(TIMEZONE),
                self.call_later,
                lambda: leave,
                cfg,
                scale=CHECKIN_TEST_SCALE,
            )
            self._test_checkins.start()

    def _end_checkin_test_if_done(self) -> None:
        test = self._test_checkins
        if test is not None and test.leave is not None and test.finished():
            test.stop()
            self._test_checkins = None
            logger.info("check-in test: finished")

    def _end_morning_test_if_done(self) -> None:
        test = self.morning
        if test is self._real_morning:
            return
        if test.state != MorningState.IDLE or test.handled_alarm is None:
            return
        test.stop()
        self.morning = self._real_morning
        self._morning_cfg = self._config
        logger.info("morning test: finished")

    # The jobs below run on the AI lane, not on the main thread.

    def _ask_ai(self, wav_path) -> None:
        self.ai._send_audio_chat(AudioCtrl._read_wav_file(wav_path))
        self._audioctrl.play_bytes(self.ai.audio)

    def _weather_refresh(self) -> None:
        """Keeps the forecast fresh on the AI lane. Main thread timer."""
        self._run_job(
            self._ai_jobs,
            "weather-refresh",
            self.weather.refresh,
            on_error=lambda _error: None,  # already logged; no sound
        )
        self.call_later(self._config.weather_refresh_minutes * 60, self._weather_refresh)

    def _weather_report(self) -> WeatherReport | None:
        report = self.weather.report()
        if report:
            logger.info("Weather facts:\n%s", report.facts)
        return report

    def _leave_time(self) -> datetime.datetime | None:
        """Today's leave time: the school event minus the travel time, from
        the last fetch. None without a school event."""
        cfg = self._config
        today = datetime.datetime.now(TIMEZONE).date()
        school = school_event(self.cal.todays_events(), today, cfg.school_title)
        if school is None:
            return None
        return school.start - datetime.timedelta(minutes=cfg.school_travel_minutes)

    def _weather_parts(self) -> tuple[str, str]:
        """(facts for the text model, sentence for the template)."""
        report = self._weather_report()
        return (report.facts, report.sentence) if report else ("", "")

    def _tell_upcoming_events(self) -> None:
        self.cal.fetch()
        facts, sentence = self._weather_parts()
        text = self.speech.status_text(
            datetime.datetime.now(TIMEZONE),
            self.cal.todays_events(),
            self._leave_time(),
            facts,
            sentence,
        )
        self._audioctrl.play_bytes(self.speech.say(text))

    def _generate_briefing(self) -> bytes:
        """The wake line. Without the text model it is the template
        without the joke; it raises only when speech fails."""
        self.cal.fetch()
        report = self._weather_report()
        text, voice = self.speech.wake_line(
            datetime.datetime.now(TIMEZONE),
            report.facts if report else "",
            school_day=self._leave_time() is not None,
            weather_day=report.days[0] if report and report.days else None,
        )
        return self.speech.say(text, voice)

    def _prepare_briefing(self) -> None:
        self._briefing_audio = None
        self._briefing_audio = self._generate_briefing()

    def _play_briefing(self) -> None:
        """The prepared wake line, else one made now, else only the chime."""
        audio, self._briefing_audio = self._briefing_audio, None
        if audio is None:
            try:
                audio = self._generate_briefing()
            except Exception:
                logger.exception("Briefing failed. Only the chime plays")
        # The "off" chime may still be due (OFF_CHIME_DELAY) or playing.
        time.sleep(OFF_CHIME_DELAY + 0.2)
        self._audioctrl.wait_until_quiet()
        time.sleep(CHIME_GAP)
        self._audioctrl.sysaudio_play(aevent.CHIME_SPEAK, block=True)
        if audio is None:
            return
        time.sleep(CHIME_GAP)
        self._audioctrl.play_bytes(audio)

    # ---- check-ins (AI lane) ----------------------------------------------

    def _overview(self, leave: datetime.datetime) -> bytes:
        self.cal.fetch()
        facts, sentence = self._weather_parts()
        cfg = self._config
        text = self.speech.overview_text(
            datetime.datetime.now(TIMEZONE),
            self.cal.todays_events(),
            leave + datetime.timedelta(minutes=cfg.school_travel_minutes),
            max(cfg.checkin_minutes),
            facts,
            sentence,
        )
        return self.speech.say(text)

    def _prepare_checkins(self, leave: datetime.datetime) -> None:
        """The overview, and the countdown texts into the disk cache."""
        self._overview_audio = {leave: self._overview(leave)}
        for minutes in self._config.checkin_minutes[1:]:
            self.speech.cached(countdown_text(minutes))

    def _play_checkin(self, minutes: int, leave: datetime.datetime) -> None:
        """Chime, then the overview (first check-in) or a countdown text,
        at checkin_volume whatever the switches say. Only the chime when
        there is no speech."""
        volume = self._config.checkin_volume
        audio = None
        try:
            if minutes == max(self._config.checkin_minutes):
                audio = self._overview_audio.pop(leave, None) or self._overview(leave)
            else:
                audio = self.speech.cached(countdown_text(minutes))
        except Exception:
            logger.exception("Check-in speech failed. Only the chime plays")
        self._audioctrl.wait_until_quiet()
        self._audioctrl.sysaudio_play(aevent.CHIME_SPEAK, block=True, volume=volume)
        if audio is None:
            return
        time.sleep(CHIME_GAP)
        self._audioctrl.play_bytes(audio, volume=volume)

    def speakerLeds(self, on: bool) -> None:
        self._audio_playing = on
        if on:
            self.send_packets(Packet(HWEvent.BLINKFOREVER, BlinkTarget.SPEAKER_LEDS, 1))
        else:
            self.send_packets(Packet(HWEvent.BLINKFOREVER, BlinkTarget.SPEAKER_LEDS, 0))

    def ledstrip_control(self, packet: Packet):
        """Sends commands (translated from packet) to LED-strip"""
        segmentId = 0 if packet.target in [32, 33, 34, 58, 59, 60, 61] else 1

        if packet.target in [32, 35]:  # on/off/reset
            if packet.val == 100:
                self.wled_instance._change_effect(0, segmentId)
                return
            led_ctrl = self._ctrls.get_ctrl(packet.target)

            def toggle(state) -> None:
                segment_on = state.seg_state[segmentId].seg_state
                self.send_packets(led_ctrl.set_state(not segment_on))
                self.wled_instance.toggle_wled_state(segmentId)

            # read_state() waits up to 1.5 s for WLED: not on the main thread.
            self._run_job(
                self._wled_jobs,
                "wled-state",
                self.wled_instance.read_state,
                on_done=toggle,
            )
            return

        if packet.target in [34, 36]:
            self.wled_instance.previous_effect(segmentId)
            return
        if packet.target in [33, 37]:
            self.wled_instance.next_effect(segmentId)
            return
        if packet.target in [55, 58]:
            self.wled_instance.set_brightness(self.map_value(packet.val), segmentId)
            return
        if packet.target in (54, 56, 57):
            self._ctrls.get_ctrl(packet.target).set_state(self.map_value(packet.val))
            red_ctrl = self._ctrls.get_ctrl(54)
            green_ctrl = self._ctrls.get_ctrl(56)
            blue_ctrl = self._ctrls.get_ctrl(57)
            color = [red_ctrl.state, green_ctrl.state, blue_ctrl.state]
            self.wled_instance.set_color(color, segmentId)
            return
        if packet.target in (59, 60, 61):
            self._ctrls.get_ctrl(packet.target).set_state(self.map_value(packet.val))
            red_ctrl = self._ctrls.get_ctrl(59)
            green_ctrl = self._ctrls.get_ctrl(60)
            blue_ctrl = self._ctrls.get_ctrl(61)
            color = [red_ctrl.state, green_ctrl.state, blue_ctrl.state]
            self.wled_instance.set_color(color, segmentId)
            return

    def map_value(self, val, in_min=0, in_max=1023, out_min=0, out_max=255):
        # Ensure value is within the input range
        val = max(in_min, min(val, in_max))
        # Map the value
        return (val - in_min) * (out_max - out_min) // (in_max - in_min) + out_min

    def send_packets(
        self, packets: List, block: bool = False, timeout: float = None
    ) -> None:
        """Puts the packet(s) into sendQueue.
        It will be picked up ASAP by packetSerial thread"""
        if not hasattr(packets, "__iter__"):
            packets = [packets]
        try:
            for p in packets:
                self._packet_sendqueue.put(p, block, timeout)
        except Full:
            logger.error("SendQueue was full. Packet(s) could not be sent")
            self._audioctrl.sysaudio_play(aevent.FAILED)

    def time_to_send_hello(self) -> bool:
        """Is it time to send hello yet?"""
        return (
            self._last_sent_hello is None
            or (datetime.datetime.now() - self._last_sent_hello).total_seconds()
            > self._config.hello_interval
        )

    def reset(self):
        """
        Resets internal HW ctrls status
        Clears outgoing queue
        Sends request-STATUS msg to Arduino to syncronize
        ctrls between the systems.
        """
        logger.debug("resetting 'controlPanel_class' instance")
        try:
            self._ctrls.reset()
            self.clear_packet_queue()
            # send RequestStatus packet to get ctrls status
            self._packet_sendqueue.put(
                Packet(HWEvent.STATUS, 1, 1), block=True, timeout=1
            )
        except (Full, TimeoutError) as err:
            logger.error(err)
            self._audioctrl.sysaudio_play(aevent.FAILED)
        else:
            logger.debug("reset done")

    def set_panelstatus(self, state: bool):
        """Set MainMaster on/off

        if OFF: Send Packet to turn all LEDs off
        """
        self._mainMasterOn.state = state
        if not state:
            self.send_packets(self._ctrls.set_all_leds(False))

    def clear_packet_queue(self):
        """Clear outgoing Packet queue, duh!"""
        if self._packet_sendqueue.qsize() > 0:
            while not self._packet_sendqueue.empty():
                try:
                    self._packet_sendqueue.get(block=False)
                except Empty:
                    continue
                self._packet_sendqueue.task_done()
            logger.debug("SendQueue is now cleared.")
        else:
            logger.debug("SendQueue is empty. Good")


def _pass_on(done: Future, target: Future) -> None:
    """Copies a finished Future's outcome to target (from any thread)."""
    if done.cancelled():
        target.cancel()
        return
    error = done.exception()
    if error is not None:
        target.set_exception(error)
    else:
        target.set_result(done.result())


class _MorningActions:
    """MorningRoutine's Actions (see daemon/morning.py), done with the
    panel's parts. Called on the main thread; nothing here blocks."""

    def __init__(self, cp: ControlPanel):
        self._cp = cp

    def sunrise_frame(self, progress: float) -> None:
        cfg = self._cp._morning_cfg
        frame = sunrise.frame(progress, cfg)
        self._cp.wled_instance.set_both(*frame, transition=cfg.sunrise_tick_seconds)

    def sunrise_release(self, off: bool = False) -> None:
        if off:
            for segment in (0, 1):
                self._cp.wled_instance.set_wled_state(False, segment)

    def alarm_start(self, level: int) -> None:
        self._cp._audioctrl.alarm_start(level)

    def alarm_set_level(self, level: int) -> None:
        self._cp._audioctrl.alarm_set_level(level)

    def alarm_stop(self) -> None:
        self._cp._audioctrl.alarm_stop()

    def chime(self, kind: str) -> None:
        # After the alarm has faded out, with a short silence.
        event = {"off": aevent.CHIME_OFF}[kind]
        self._cp.call_later(OFF_CHIME_DELAY, self._cp._audioctrl.sysaudio_play, event)

    def volume_override(self, on: bool) -> None:
        self._cp._audioctrl.volume_override(on, self._cp._morning_cfg.alarm_volume)

    def briefing_prepare(self) -> None:
        self._cp._briefing_prepare()

    def briefing_play(self) -> None:
        self._cp._briefing_play()


class _NightActions:
    """NightOff's Actions (see daemon/night.py)."""

    def __init__(self, cp: ControlPanel):
        self._cp = cp

    def lights_off(self) -> None:
        self._cp._night_off()


class _CheckinActions:
    """Checkins' Actions (see daemon/checkins.py): the speech is made and
    played on the AI lane, after any job already there."""

    def __init__(self, cp: ControlPanel):
        self._cp = cp

    def checkin_prepare(self, leave: datetime.datetime) -> None:
        cp = self._cp
        # Quietly: the check-in itself makes the overview again if needed.
        cp._run_job(
            cp._ai_jobs, "checkin-prepare", cp._prepare_checkins, leave,
            on_error=lambda _error: None,
        )

    def checkin_play(self, minutes: int, leave: datetime.datetime) -> None:
        cp = self._cp
        cp._run_job(cp._ai_jobs, "checkin", cp._play_checkin, minutes, leave)


if __name__ == "__main__":
    myCP = ControlPanel()
    myCP.start()
    pass
