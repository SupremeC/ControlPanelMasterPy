"""The web API and page (see WEB_API_PLAN.md in the project folder).

FastAPI served by uvicorn in a daemon thread, LAN only, no auth. Every
request becomes a Remote command (daemon/remote.py) through
ControlPanel.request(), so the main thread stays the only one that
touches the panel. The endpoints are plain `def` functions: FastAPI
runs them in its threadpool, where waiting on the command's Future is
fine. Nothing here imports the panel; the component only gets the
request callable, so the app is testable with a fake.

Errors: an unknown thing is 404, a refused command 409 ("Panelen är
av"), bad input 422 (pydantic) or 400, a main loop that does not answer
in web_command_timeout 504. GET never changes anything: with no auth a
bookmarked or prefetched link must not switch a 230 V socket.
"""

from concurrent.futures import Future, TimeoutError as FutureTimeout
import logging
import threading
from typing import Annotated, Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from daemon.config import Config

logger = logging.getLogger("daemon.web")

THREAD_JOIN_TIMEOUT = 3  # seconds for uvicorn to finish at stop()
START_TIMEOUT = 5  # seconds to wait for the socket at start()

OnOff = Literal["on", "off", "toggle"]
Socket = Literal["bed", "drawer"]
Segment = Annotated[int, Path(ge=0, le=1, description="0 = säng, 1 = fönster")]
Direction = Literal["up", "down"]
Request = Callable[..., Future]  # ControlPanel.request


class OnBody(BaseModel):
    on: bool


class VolumeBody(BaseModel):
    percent: Annotated[int, Field(ge=0, le=100)]


Channel = Annotated[int, Field(ge=0, le=255)]


class StripBody(BaseModel):
    """Any subset; what is given is applied in this order."""

    on: bool | None = None
    brightness: Channel | None = None
    color: Annotated[list[Channel], Field(min_length=3, max_length=3)] | None = None
    effect: Literal["next", "prev", "off"] | None = None


PLACEHOLDER = """<!doctype html><html lang="sv"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kontrollpanelen</title>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:24px">
<h1>Kontrollpanelen</h1>
<p>Sidan är inte installerad än. API:et finns under <a style="color:#fc0"
href="/docs">/docs</a>.</p></body></html>"""


def build_app(request: Request, config: Config | None = None) -> FastAPI:
    """The FastAPI app over `request` (ControlPanel.request or a fake)."""
    cfg = config or Config()
    app = FastAPI(
        title="Kontrollpanelen",
        description="Fjärrkontroll för panelen på hemmanätet. Ingen inloggning.",
        docs_url="/docs",
        redoc_url=None,
    )

    def run(command: str, **kwargs: Any) -> Any:
        """Runs the Remote command on the main thread and waits for it."""
        try:
            return request(command, **kwargs).result(cfg.web_command_timeout)
        except FutureTimeout:
            raise HTTPException(504, "Panelen svarar inte") from None
        except KeyError as e:
            what = e.args[0] if e.args else command
            raise HTTPException(404, f"Finns inte: {what}") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        except TypeError as e:
            raise HTTPException(400, str(e)) from None

    def switch(set_cmd: str, toggle_cmd: str, action: OnOff, **kwargs: Any) -> Any:
        if action == "toggle":
            return run(toggle_cmd, **kwargs)
        return run(set_cmd, on=(action == "on"), **kwargs)

    # ---- state ------------------------------------------------------------

    @app.get("/api/state", tags=["status"])
    def state() -> dict:
        """Everything the page shows. `text` holds Swedish labels for a
        Stream Deck key."""
        return run("state")

    # ---- sockets and lamps --------------------------------------------------

    @app.post("/api/sockets/{name}", tags=["uttag"])
    def set_socket(name: Socket, body: OnBody) -> dict:
        return run("set_socket", name=name, on=body.on)

    @app.post("/api/sockets/{name}/{action}", tags=["uttag"])
    def socket_action(name: Socket, action: OnOff) -> dict:
        return switch("set_socket", "toggle_socket", action, name=name)

    @app.post("/api/bedlamp/toggle", tags=["lampor"])
    def bed_lamp_toggle() -> dict:
        """Pulses the bed lamp's switch. Its state is unknown."""
        return run("bed_lamp_toggle")

    @app.post("/api/backlight", tags=["lampor"])
    def set_backlight(body: OnBody) -> dict:
        return run("set_backlight", on=body.on)

    @app.post("/api/backlight/{action}", tags=["lampor"])
    def backlight_action(action: OnOff) -> dict:
        return switch("set_backlight", "toggle_backlight", action)

    @app.post("/api/leds", tags=["lampor"])
    def set_leds(body: OnBody) -> dict:
        """Every button LED."""
        return run("set_button_leds", on=body.on)

    @app.post("/api/leds/{action}", tags=["lampor"])
    def leds_action(action: OnOff) -> dict:
        return switch("set_button_leds", "toggle_button_leds", action)

    # ---- demo ----------------------------------------------------------------

    @app.post("/api/demo", tags=["panel"])
    def set_demo(body: OnBody) -> dict:
        """Needs the master switch on (409 otherwise)."""
        return run("set_demo", on=body.on)

    @app.post("/api/demo/{action}", tags=["panel"])
    def demo_action(action: OnOff) -> dict:
        return switch("set_demo", "toggle_demo", action)

    @app.post("/api/all-off", tags=["panel"])
    def all_off() -> dict:
        """Släck allt: lights, sockets, strips, demo and sounds. The bed
        lamp is left alone."""
        return run("all_off")

    # ---- sounds ------------------------------------------------------------------

    @app.get("/api/sounds", tags=["ljud"])
    def list_sounds() -> list[dict]:
        """The preset buttons (btn_2 ... btn_11) with a clip, then the
        system sounds."""
        return run("list_sounds")

    @app.post("/api/sounds/{id}", tags=["ljud"])
    def play_sound(id: str) -> dict:
        """409 when the panel's sound switch is off or the volume is 0."""
        return run("play_sound", id=id)

    @app.post("/api/audio/stop", tags=["ljud"])
    def stop_audio() -> dict:
        """Stops clips and system sounds, not speech."""
        return run("stop_audio")

    @app.post("/api/audio/mute", tags=["ljud"])
    def mute() -> dict:
        return run("mute")

    @app.post("/api/audio/unmute", tags=["ljud"])
    def unmute() -> dict:
        return run("unmute")

    @app.post("/api/audio/volume", tags=["ljud"])
    def set_volume(body: VolumeBody) -> dict:
        """Software volume in percent. The panel's pot takes over the
        next time it is turned."""
        return run("set_volume", percent=body.percent)

    @app.post("/api/audio/volume/{direction}", tags=["ljud"])
    def step_volume(
        direction: Direction, step: Annotated[int, Query(ge=1, le=100)] = 5
    ) -> dict:
        """One dial tick, silent."""
        return run("step_volume", delta=step if direction == "up" else -step)

    # ---- LED strips --------------------------------------------------------------

    @app.post("/api/strips/{segment}", tags=["ljusslingor"])
    def set_strip(segment: Segment, body: StripBody) -> dict:
        """Segment 0 is the bed strip, 1 the window strip."""
        return run("set_strip", segment=segment, **body.model_dump(exclude_none=True))

    @app.post("/api/strips/{segment}/{action}", tags=["ljusslingor"])
    def strip_action(segment: Segment, action: OnOff) -> dict:
        return switch("set_strip", "toggle_strip", action, segment=segment)

    @app.post("/api/strips/{segment}/brightness/{direction}", tags=["ljusslingor"])
    def step_brightness(
        segment: Segment,
        direction: Direction,
        step: Annotated[int, Query(ge=1, le=255)] = 16,
    ) -> dict:
        """One dial tick (0-255). Quick ticks are folded into one WLED
        command per 100 ms."""
        return run(
            "step_brightness", segment=segment, delta=step if direction == "up" else -step
        )

    @app.post("/api/strips/{segment}/effect/{which}", tags=["ljusslingor"])
    def strip_effect(segment: Segment, which: Literal["next", "prev", "off"]) -> dict:
        return run("strip_effect", segment=segment, which=which)

    # ---- the page --------------------------------------------------------------

    if cfg.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(cfg.web_dir), html=True), name="web")
    else:

        @app.get("/", include_in_schema=False, response_class=HTMLResponse)
        def placeholder() -> str:
            return PLACEHOLDER

    return app


class WebApi:
    """Component: uvicorn in a daemon thread. The constructor only
    builds the app; start() binds the port."""

    def __init__(self, config: Config, request: Request):
        self._cfg = config
        self.app = build_app(request, config)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        config = uvicorn.Config(
            self.app,
            host=self._cfg.web_host,
            port=self._cfg.web_port,
            loop="asyncio",
            http="h11",
            lifespan="off",
            log_config=None,  # the daemon's logging stays as it is
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        # Not on the main thread, so uvicorn installs no signal handlers.
        self._thread = threading.Thread(target=self._run, name="web", daemon=True)
        self._thread.start()
        if self._wait_started():
            logger.info("Web API on http://%s:%s", self._cfg.web_host, self.port)
        else:
            logger.error("Web API did not start on port %s", self._cfg.web_port)

    def _run(self) -> None:
        try:
            self._server.run()
        except Exception:
            logger.exception("Web API stopped")

    def _wait_started(self) -> bool:
        deadline = threading.Event()
        for _ in range(int(START_TIMEOUT / 0.05)):
            if self._server.started or not self._thread.is_alive():
                break
            deadline.wait(0.05)
        return bool(self._server.started)

    @property
    def port(self) -> int | None:
        """The bound port once started (web_port, or the one picked for 0)."""
        server = self._server
        if server is None or not server.started:
            return None
        try:
            return server.servers[0].sockets[0].getsockname()[1]
        except (IndexError, AttributeError, OSError):
            return self._cfg.web_port

    def stop(self) -> None:
        """Safe before start() and more than once."""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        self._server.should_exit = True
        thread.join(THREAD_JOIN_TIMEOUT)
        if thread.is_alive():
            logger.warning("Web API is still busy at shutdown")
        else:
            logger.info("Web API stopped")
