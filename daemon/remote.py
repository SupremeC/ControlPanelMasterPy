"""Remote actions: what the web API (daemon/webapi.py) may do with the
panel, and the state it shows.

Every method runs on the main thread as a Command (daemon/events.py)
handled by ControlPanel.process(), so nothing here blocks: WLED reads,
effects and speech stay on their job lanes. The physical rules (the
master and inputs flips, the sockets' safety flips) are bypassed on
purpose: the point is to switch things off from a phone when the panel
is off. Demo mode is the exception, it needs the master switch on. With
the master switch off only RELAY packets go out, so the dark panel
stays dark.

The commands raise ValueError (refused, with a Swedish message for the
page) or KeyError (no such thing); the web API maps them to 4xx.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from concurrent.futures import Future
from pathlib import Path

from daemon.audio_ctrl import SysAudioEvent as aevent
from daemon.packet import HWEvent, Packet
from daemon.presets import PRESET_PINS, Presets

if TYPE_CHECKING:  # no import cycle: controlpanel_class imports this module
    from daemon.controlpanel_class import ControlPanel

logger = logging.getLogger("daemon.remote")

SOCKETS = {"bed": 66, "drawer": 68}  # button pin; its relay is the slave
SAFETY_FLIPS = {"bed": 41, "drawer": 40}
BED_LAMP_BUTTON = 67
BED_LAMP_PULSE = 0.1  # seconds; same as the panel
STRIPS = {0: "säng", 1: "fönster"}
STRIP_POWER_BUTTONS = {0: 32, 1: 35}
VOLUME_STEP = 5  # percent per dial tick
BRIGHTNESS_STEP = 16  # of 255 per dial tick
BRIGHTNESS_DEFAULT = 128  # when WLED's brightness is not known yet
BRIGHTNESS_COALESCE = 0.1  # seconds between two WLED brightness commands
UNMUTE_DEFAULT = 50  # percent, when nothing was muted before

# Swedish labels for the system sounds (keys of AudioCtrl.systemsounds
# that are SysAudioEvent names). Others fall back to the key itself.
SOUND_LABELS = {
    "btn_pressed": "Knapp ned",
    "btn_released": "Knapp upp",
    "btn_clicked": "Klick",
    "rec_started": "Inspelning startad",
    "rec_stopped": "Inspelning stoppad",
    "rec_could_not_rec": "Kunde inte spela in",
    "effect_applying": "Effekt läggs på",
    "effect_apply_done": "Effekt klar",
    "rec_saved": "Inspelning sparad",
    "volume_change": "Volym",
    "system_off": "Panel av",
    "system_on": "Panel på",
    "ctrls_on": "Reglage på",
    "ctrls_off": "Reglage av",
    "bg_light_on": "Bakgrundsljus på",
    "bg_light_off": "Bakgrundsljus av",
    "audio_on": "Ljud på",
    "audio_off": "Ljud av",
    "relay_on": "Relä på",
    "relay_off": "Relä av",
    "flip_switch": "Vippbrytare",
    "demomode": "Demo",
    "alarm": "Larm",
    "alarm_soft": "Larm (mjukt)",
    "chime_off": "Pling (av)",
    "chime_speak": "Pling (tal)",
    "failed": "Fel",
    "tick": "Tick",
}

COMMANDS = frozenset(
    {
        "state",
        "set_socket",
        "toggle_socket",
        "bed_lamp_toggle",
        "set_backlight",
        "toggle_backlight",
        "set_button_leds",
        "toggle_button_leds",
        "set_demo",
        "toggle_demo",
        "list_sounds",
        "play_sound",
        "stop_audio",
        "set_volume",
        "step_volume",
        "mute",
        "unmute",
        "set_strip",
        "toggle_strip",
        "step_brightness",
        "strip_effect",
        "all_off",
        "presets",
        "set_preset_default",
        "restore_preset",
        "rename_preset",
    }
)


def _on_off(value: bool | None) -> str:
    if value is None:
        return "?"
    return "På" if value else "Av"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _check_int(value: Any, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what} måste vara ett heltal {low}-{high}")
    if not low <= value <= high:
        raise ValueError(f"{what} måste vara {low}-{high}")
    return value


class Remote:
    """The commands. READ_ONLY ones are not logged (the page polls)."""

    READ_ONLY = frozenset({"state", "list_sounds", "presets"})

    def __init__(self, cp: ControlPanel):
        self._cp = cp
        self.store = Presets(cp._config)  # the preset clips and their names
        # Strip values set from here, newer than the WLED snapshot:
        # segment -> {"at": monotonic, "on": bool, "brightness": int, "effect": int}
        self._strip_overlay: dict[int, dict[str, Any]] = {}
        # Brightness coalescing: the value last sent, the value waiting
        # for the next send, and the segments with a send scheduled.
        self._brightness_sent: dict[int, int] = {}
        self._brightness_pending: dict[int, int] = {}
        self._brightness_scheduled: set[int] = set()
        self._muted_volume: int | None = None

    def command(self, name: str) -> Callable[..., Any]:
        """The command's callable. KeyError for an unknown name."""
        if name not in COMMANDS:
            raise KeyError(name)
        return getattr(self, name)

    # ---- state -----------------------------------------------------------

    def state(self) -> dict:
        cp = self._cp
        ctrls = cp._ctrls
        master = bool(ctrls.get_ctrl_by_name("masterSw").state)
        inputs = bool(ctrls.get_ctrl_by_name("InputsSw").state)
        sound = bool(ctrls.get_ctrl_by_name("SoundSw").state)
        backlight = bool(ctrls.get_ctrl_by_name("BacklightRelay").state)
        audio = cp._audioctrl
        volume = int(audio.master_volume)
        sockets = {name: self._socket_state(name) for name in SOCKETS}
        strips = [self._strip_state(segment) for segment in STRIPS]
        alarm = cp.morning.alarm
        return {
            "daemon": {
                "mega_connected": bool(cp._pserial.is_conn_open),
                "night": bool(cp.night.active),
            },
            "switches": {
                "master": master,
                "inputs": inputs,
                "sound": sound,
                "backlight": backlight,
            },
            "sockets": sockets,
            "button_leds": bool(cp.btnLeds),
            "demo": bool(cp.demo_on),
            "audio": {
                "volume": volume,
                "muted": audio.get_volume() <= 0,
                "playing": bool(cp._audio_playing),
                "recording": bool(audio.is_recording()),
            },
            "strips": {"segments": strips},
            "morning": {
                "state": cp.morning.state.name,
                "next_alarm": alarm.isoformat() if alarm else None,
            },
            "text": {
                "panel": _on_off(master),
                "bed_socket": _on_off(sockets["bed"]["on"]),
                "drawer_socket": _on_off(sockets["drawer"]["on"]),
                "backlight": _on_off(backlight),
                "button_leds": _on_off(cp.btnLeds),
                "strip_0": self._strip_text(strips[0]),
                "strip_1": self._strip_text(strips[1]),
                "volume": f"{volume} %",
                "demo": _on_off(cp.demo_on),
                "next_alarm": f"{alarm:%H:%M}" if alarm else "–",
            },
        }

    @staticmethod
    def _strip_text(strip: dict) -> str:
        if strip["on"] is None:
            return "?"
        if not strip["on"]:
            return "Av"
        if strip["brightness"] is None:
            return "På"
        return f"På {round(strip['brightness'] * 100 / 255)} %"

    # ---- sockets and lamps -------------------------------------------------

    def _master_on(self) -> bool:
        return bool(self._cp._ctrls.get_ctrl_by_name("masterSw").state)

    def _send(self, packets: list) -> None:
        """Sends the packets; with the master switch off only the RELAY
        ones, so the dark panel stays dark."""
        if not self._master_on():
            packets = [p for p in packets if p.hw_event == HWEvent.RELAY]
        if packets:
            self._cp.send_packets(packets)

    @staticmethod
    def _socket_pin(name: str) -> int:
        try:
            return SOCKETS[name]
        except KeyError:
            raise ValueError(f"Okänt uttag: {name}") from None

    def _socket_state(self, name: str) -> dict:
        ctrls = self._cp._ctrls
        btn = ctrls.get_slavectrl(self._socket_pin(name))
        safety = ctrls.get_ctrl(SAFETY_FLIPS[name])
        return {"on": bool(btn.state), "safety": bool(safety.state)}

    def set_socket(self, name: str, on: bool) -> dict:
        btn = self._cp._ctrls.get_slavectrl(self._socket_pin(name))
        self._send(btn.set_state(bool(on)))
        self._cp._audioctrl.sysaudio_play(aevent.BTN_CLICKED)
        state = self._socket_state(name)
        return {**state, "text": _on_off(state["on"])}

    def toggle_socket(self, name: str) -> dict:
        return self.set_socket(name, not self._socket_state(name)["on"])

    def bed_lamp_toggle(self) -> dict:
        """Pulses the bed lamp's relay, like the panel does. The lamp has
        its own toggle circuit: its state is unknown."""
        cp = self._cp
        lamp = cp._ctrls.get_slavectrl(BED_LAMP_BUTTON)
        self._send(lamp.set_state(True))
        cp.call_later(BED_LAMP_PULSE, lambda: self._send(lamp.set_state(False)))
        cp._audioctrl.sysaudio_play(aevent.BTN_CLICKED)
        return {"toggled": True}

    def set_backlight(self, on: bool) -> dict:
        """The backlight relay and its indicator, with the panel's sound.
        Not through cp_bg_lights(): two quick calls would toggle every
        LED there (the double-flip feature)."""
        cp = self._cp
        on = bool(on)
        ctrl = cp._ctrls.get_ctrl_by_name("BacklightSw")
        relay = cp._ctrls.get_ctrl_by_name("BacklightRelay")
        relay.set_state(on)
        packets = ctrl.set_state(on)
        packets.append(Packet(HWEvent.RELAY, relay.pin, 0 if on else 1))  # active-low
        self._send(packets)
        cp._audioctrl.sysaudio_play(aevent.BG_LIGHT_ON if on else aevent.BG_LIGHT_OFF)
        return {"on": bool(relay.state), "text": _on_off(relay.state)}

    def toggle_backlight(self) -> dict:
        relay = self._cp._ctrls.get_ctrl_by_name("BacklightRelay")
        return self.set_backlight(not relay.state)

    def set_button_leds(self, on: bool) -> dict:
        """Every button LED on or off, like a long press on button 3.
        Sent whatever the master switch says: that is the request."""
        cp = self._cp
        cp.btnLeds = bool(on)
        cp.send_packets(cp._ctrls.set_all_leds(cp.btnLeds))
        return {"on": cp.btnLeds, "text": _on_off(cp.btnLeds)}

    def toggle_button_leds(self) -> dict:
        return self.set_button_leds(not self._cp.btnLeds)

    def set_demo(self, on: bool) -> dict:
        cp = self._cp
        on = bool(on)
        if on and not self._master_on():
            raise ValueError("Panelen är av. Slå på den först")
        if on != cp.demo_on:
            cp.demo_on = on
            if on:
                cp._audioctrl.sysaudio_play(aevent.DEMOMODE)
                cp._demo_leds = cp._ctrls._get_all_leds()
        return {"on": cp.demo_on, "text": _on_off(cp.demo_on)}

    def toggle_demo(self) -> dict:
        return self.set_demo(not self._cp.demo_on)

    # ---- sounds --------------------------------------------------------------

    def list_sounds(self) -> list[dict]:
        """The preset buttons with a clip, then the system sounds."""
        sounds = []
        for pin in PRESET_PINS:
            if self.store.active_path(pin).is_file():
                sounds.append({"id": f"btn_{pin}", "label": self.store.name(pin)})
        loaded = self._cp._audioctrl.systemsounds or {}
        for key in sorted(loaded):
            if key.upper() in aevent.__members__:
                sounds.append({"id": key, "label": SOUND_LABELS.get(key, key)})
        return sounds

    def play_sound(self, id: str) -> dict:
        cp = self._cp
        audio = cp._audioctrl
        if audio.get_volume() <= 0:
            raise ValueError("Ljudet är avstängt på panelen")
        key = str(id).lower()
        if key.startswith("btn_"):
            try:
                pin = int(key[4:])
            except ValueError:
                raise KeyError(id) from None
            if pin not in PRESET_PINS or not self.store.active_path(pin).is_file():
                raise KeyError(id)
            audio.recsaved_play(pin)
            self._send(cp._ctrls.get_slavectrl(pin).leds[0].blink())
            return {"id": key}
        if key.upper() not in aevent.__members__ or key not in (audio.systemsounds or {}):
            raise KeyError(id)
        audio.sysaudio_play(aevent[key.upper()])
        return {"id": key}

    def stop_audio(self) -> dict:
        """Stops the mixer (clips and system sounds), not speech."""
        self._cp._audioctrl.stop_all_audio()
        return {"playing": False}

    def set_volume(self, percent: int) -> dict:
        percent = _check_int(percent, 0, 100, "Volymen")
        self._cp.audio_volume(percent)
        if percent > 0:
            self._muted_volume = None
        return self._volume_state()

    def step_volume(self, delta: int = VOLUME_STEP) -> dict:
        """A quiet step, for a dial that sends one per tick."""
        audio = self._cp._audioctrl
        delta = _check_int(delta, -100, 100, "Steget")
        audio.set_volume(_clamp(int(audio.master_volume) + delta, 0, 100), sound=False)
        return self._volume_state()

    def mute(self) -> dict:
        audio = self._cp._audioctrl
        if audio.master_volume > 0:
            self._muted_volume = int(audio.master_volume)
            audio.set_volume(0, sound=False)
        return self._volume_state()

    def unmute(self) -> dict:
        audio = self._cp._audioctrl
        volume = self._muted_volume or UNMUTE_DEFAULT
        self._muted_volume = None
        audio.set_volume(volume, sound=False)
        return self._volume_state()

    def _volume_state(self) -> dict:
        audio = self._cp._audioctrl
        volume = int(audio.master_volume)
        return {
            "volume": volume,
            "muted": audio.get_volume() <= 0,
            "text": f"{volume} %",
        }

    # ---- LED strips --------------------------------------------------------

    @staticmethod
    def _segment(segment: Any) -> int:
        if isinstance(segment, bool) or segment not in STRIPS:
            raise ValueError(f"Okänd ljusslinga: {segment}")
        return int(segment)

    def _strip_state(self, segment: int) -> dict:
        """Snapshot values, overlaid with what was set from here since."""
        cp = self._cp
        state = {
            "id": segment,
            "name": STRIPS[segment],
            "on": None,
            "brightness": None,
            "effect": None,
        }
        snapshot = cp.wled_snapshot()
        if snapshot is not None:
            for seg in snapshot.seg_state:
                if seg.seg_id == segment:
                    state.update(
                        on=bool(seg.seg_state),
                        brightness=int(seg.seg_brightness),
                        effect=int(seg.fx),
                    )
        overlay = self._strip_overlay.get(segment)
        if overlay is not None and overlay["at"] > cp.wled_snapshot_at:
            state.update({k: v for k, v in overlay.items() if k != "at"})
        return state

    def _overlay(self, segment: int, **values: Any) -> None:
        entry = self._strip_overlay.setdefault(segment, {})
        entry.update(values)
        entry["at"] = time.monotonic()

    def set_strip(
        self,
        segment: int,
        on: bool | None = None,
        brightness: int | None = None,
        color: list | None = None,
        effect: str | int | None = None,
    ) -> dict:
        """Any of on/off, brightness 0-255, colour [r, g, b] and effect
        "next" / "prev" / "off" for one segment. Queue writes only."""
        cp = self._cp
        segment = self._segment(segment)
        wled = cp.wled_instance
        if on is not None:
            on = bool(on)
            wled.set_wled_state(on, segment)
            self._send(cp._ctrls.get_ctrl(STRIP_POWER_BUTTONS[segment]).set_state(on))
            self._overlay(segment, on=on)
        if brightness is not None:
            brightness = _check_int(brightness, 0, 255, "Ljusstyrkan")
            wled.set_brightness(brightness, segment)
            self._brightness_sent[segment] = brightness
            self._overlay(segment, brightness=brightness)
        if color is not None:
            if not isinstance(color, (list, tuple)) or len(color) != 3:
                raise ValueError("Färgen måste vara [r, g, b]")
            rgb = [_check_int(c, 0, 255, "Färgvärdet") for c in color]
            wled.set_color(rgb, segment)
        if effect is not None:
            if effect == "next":
                wled.next_effect(segment)
            elif effect == "prev":
                wled.previous_effect(segment)
            elif effect in ("off", 0):
                wled._change_effect(0, segment)
                self._overlay(segment, effect=0)
            else:
                raise ValueError(f"Okänd effekt: {effect}")
        cp.invalidate_wled_snapshot()
        return self._strip_state(segment)

    def toggle_strip(self, segment: int) -> dict:
        """Known state: the opposite. Unknown: WLED toggles itself and
        the power button's LED is left as it is."""
        segment = self._segment(segment)
        current = self._strip_state(segment)["on"]
        if current is not None:
            return self.set_strip(segment, on=not current)
        self._cp.wled_instance.toggle_wled_state(segment)
        self._cp.invalidate_wled_snapshot()
        return self._strip_state(segment)

    def strip_effect(self, segment: int, which: str) -> dict:
        return self.set_strip(segment, effect=which)

    def step_brightness(self, segment: int, delta: int = BRIGHTNESS_STEP) -> dict:
        """One dial tick. The first step goes to WLED at once, the ticks
        that follow within BRIGHTNESS_COALESCE are folded into one send,
        so a quick spin is a few commands, not twenty."""
        segment = self._segment(segment)
        delta = _check_int(delta, -255, 255, "Steget")
        current = self._brightness_pending.get(segment)
        if current is None:
            current = self._strip_state(segment)["brightness"]
        if current is None:
            current = BRIGHTNESS_DEFAULT
        target = _clamp(current + delta, 0, 255)
        self._overlay(segment, brightness=target)
        if segment in self._brightness_scheduled:
            self._brightness_pending[segment] = target
        else:
            self._send_brightness(segment, target)
        return {"segment": segment, "brightness": target}

    def _send_brightness(self, segment: int, value: int) -> None:
        self._cp.wled_instance.set_brightness(value, segment)
        self._brightness_sent[segment] = value
        self._brightness_scheduled.add(segment)
        self._cp.call_later(BRIGHTNESS_COALESCE, self._flush_brightness, segment)

    def _flush_brightness(self, segment: int) -> None:
        self._brightness_scheduled.discard(segment)
        target = self._brightness_pending.pop(segment, None)
        if target is None:
            self._cp.invalidate_wled_snapshot()
            return
        if target != self._brightness_sent.get(segment):
            self._send_brightness(segment, target)
        else:
            self._cp.invalidate_wled_snapshot()

    # ---- preset clips ------------------------------------------------------

    @staticmethod
    def _pin(pin: Any) -> int:
        if isinstance(pin, bool) or pin not in PRESET_PINS:
            raise ValueError(f"Okänd knapp: {pin}")
        return int(pin)

    def _blink_saved(self, pin: int) -> None:
        """The panel's own feedback for a saved clip."""
        self._cp._audioctrl.sysaudio_play(aevent.REC_SAVED)
        self._send(self._cp._ctrls.get_slavectrl(pin).leds[0].blink(True))

    def presets(self) -> list[dict]:
        return self.store.status()

    def set_preset_default(
        self, pin: int, path: str, activate: bool = True, source: str | None = None
    ) -> Future:
        """A new default clip from an uploaded file (the web API wrote it
        to the upload dir). The work runs on the audio lane; the returned
        Future ends when the files are in place. Then the panel plays
        REC_SAVED, blinks the button and the source is noted."""
        cp = self._cp
        pin = self._pin(pin)
        upload = Path(path)
        store = self.store
        if upload.resolve().parent != store.upload_dir.resolve() or not upload.is_file():
            raise ValueError("Ingen uppladdad fil")

        def done(result: dict) -> None:
            store.note_default(pin, source)
            self._blink_saved(pin)
            logger.info(
                "remote: preset %s default replaced (%.1f s, from %s%s)",
                pin, result["seconds"], source or "?", "" if result["activate"] else ", not activated",
            )

        def failed(_error: BaseException) -> None:
            cp._audioctrl.sysaudio_play(aevent.FAILED)

        return cp._run_job(
            cp._audio_jobs, "preset-upload", store.install, pin, upload, bool(activate),
            on_done=done, on_error=failed,
        )

    def restore_preset(self, pin: int) -> dict:
        pin = self._pin(pin)
        self.store.restore(pin)  # KeyError without a default
        self._blink_saved(pin)
        return self.store.status_of(pin)

    def rename_preset(self, pin: int, name: str) -> dict:
        pin = self._pin(pin)
        self.store.set_name(pin, name)  # PresetError (a ValueError) on a bad name
        return self.store.status_of(pin)

    # ---- everything off -----------------------------------------------------

    def all_off(self) -> dict:
        """Släck allt: the night-off (LEDs, backlight, drawer socket),
        plus the bed socket, both strips, demo mode and the mixer. The
        bed lamp is left alone (state unknown)."""
        cp = self._cp
        cp._night_off(night_light=False)
        for name in SOCKETS:
            self._send(cp._ctrls.get_slavectrl(SOCKETS[name]).set_state(False))
        for segment in STRIPS:
            cp.wled_instance.set_wled_state(False, segment)
            cp._ctrls.get_ctrl(STRIP_POWER_BUTTONS[segment]).state = False
            self._overlay(segment, on=False)
        cp._audioctrl.stop_all_audio()
        cp.invalidate_wled_snapshot()
        return self.state()
