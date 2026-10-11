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

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
import json
import logging
import os
import pathlib
import queue
import re
import tempfile
import threading
from typing import Annotated, Any, AsyncIterator, Callable, Literal

import anyio
from fastapi import FastAPI, File, Form, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.datastructures import MutableHeaders
import uvicorn

from daemon.config import Config
from daemon.presets import NAME_MAX

SAY_MAX_CHARS = 200  # the route's hard limit; Config.say_max_chars may be lower

logger = logging.getLogger("daemon.web")

THREAD_JOIN_TIMEOUT = 3  # seconds for uvicorn to finish at stop()
START_TIMEOUT = 5  # seconds to wait for the socket at start()

UPLOAD_CHUNK = 64 * 1024
OnOff = Literal["on", "off", "toggle"]
Socket = Literal["bed", "drawer"]
Pin = Annotated[int, Path(ge=2, le=11, description="audio button 2-11")]
Segment = Annotated[int, Path(ge=0, le=1, description="0 = säng, 1 = fönster")]
Direction = Literal["up", "down"]
RequestFn = Callable[..., Future]  # ControlPanel.request


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


class NameBody(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=NAME_MAX)]


class SayBody(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=SAY_MAX_CHARS)]


class EventStream(Response):
    """A server-sent-events response that always closes its generator.
    Starlette's StreamingResponse leaves the generator suspended when the
    client has gone and send() raises, so its finally (the unsubscribe)
    would only run at garbage collection or shutdown."""

    media_type = "text/event-stream"

    def __init__(self, generator: AsyncIterator[str]):
        super().__init__(
            content=None,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        # The base class declares content-length 0 for an empty body; a
        # stream has no length (uvicorn then uses chunked encoding).
        self.raw_headers = [(k, v) for k, v in self.raw_headers if k != b"content-length"]
        self._generator = generator

    async def __call__(self, scope, receive, send) -> None:
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            async for chunk in self._generator:
                await send(
                    {"type": "http.response.body", "body": chunk.encode(), "more_body": True}
                )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await self._generator.aclose()


class ResponseHeaders:
    """ASGI middleware adding two headers.

    - Outside /api/: Cache-Control: no-cache, so a phone asks for app.js
      again on every load (the ETag makes that cheap).
    - On /api/ (not the event stream): Connection: close. uvicorn drops
      an idle keep-alive connection after a few seconds while a Windows
      client keeps its end; the Stream Deck plugins then sent their next
      request into a half-closed socket and waited forever, which froze
      the key. One connection per request costs nothing on the LAN.

    A plain ASGI middleware, not Starlette's BaseHTTPMiddleware: that one
    runs the app in its own task and hides client disconnects from
    /api/events."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path == "/api/events":
            header = None
        elif path.startswith("/api/"):
            header = ("Connection", "close")
        else:
            header = ("Cache-Control", "no-cache")
        if header is None:
            await self.app(scope, receive, send)
            return

        async def send_with_header(message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[header[0]] = header[1]
            await send(message)

        await self.app(scope, receive, send_with_header)


class StateBroadcast:
    """Fan-out of state snapshots (JSON text) to the /api/events clients.
    publish() runs on the main thread; each client reads its own queue
    on the web side. A client that cannot keep up misses a snapshot and
    gets the next one."""

    QUEUE_SIZE = 8

    def __init__(self):
        self._lock = threading.Lock()
        self._queues: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(self.QUEUE_SIZE)
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._queues)

    def publish(self, payload: str) -> None:
        with self._lock:
            targets = list(self._queues)
        for q in targets:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


PLACEHOLDER = """<!doctype html><html lang="sv"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kontrollpanelen</title>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:24px">
<h1>Kontrollpanelen</h1>
<p>Sidan är inte installerad än. API:et finns under <a style="color:#fc0"
href="/docs">/docs</a>.</p></body></html>"""


def build_app(
    request: RequestFn,
    config: Config | None = None,
    broadcast: StateBroadcast | None = None,
) -> FastAPI:
    """The FastAPI app over `request` (ControlPanel.request or a fake)."""
    cfg = config or Config()
    broadcast = broadcast or StateBroadcast()
    app = FastAPI(
        title="Kontrollpanelen",
        description="Fjärrkontroll för panelen på hemmanätet. Ingen inloggning.",
        docs_url="/docs",
        redoc_url=None,
    )

    def run(command: str, timeout: float | None = None, **kwargs: Any) -> Any:
        """Runs the Remote command on the main thread and waits for it."""
        try:
            return request(command, **kwargs).result(timeout or cfg.web_command_timeout)
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

    @app.get(
        "/api/events",
        tags=["status"],
        responses={200: {"content": {"text/event-stream": {}}, "description": "The stream"}},
    )
    async def events(http_request: Request) -> Response:
        """Server-sent events: `event: state` with the same JSON as
        /api/state, first at once and then whenever it changes, plus a
        comment line every few seconds to keep the connection alive. A
        client that left is noticed at the next comment, at the latest."""
        q = broadcast.subscribe()

        async def stream() -> AsyncIterator[str]:
            logger.debug("events: client %s connected", http_request.client)
            try:
                try:
                    first = await asyncio.wait_for(
                        asyncio.wrap_future(request("state")), cfg.web_command_timeout
                    )
                    yield f"event: state\ndata: {json.dumps(first, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": no state yet\n\n"
                while not await http_request.is_disconnected():
                    try:
                        payload = await anyio.to_thread.run_sync(q.get, True, cfg.web_events_ping)
                    except queue.Empty:
                        logger.debug("events: ping to %s", http_request.client)
                        yield ": ping\n\n"
                        continue
                    yield f"event: state\ndata: {payload}\n\n"
            finally:
                broadcast.unsubscribe(q)
                logger.debug("events: client %s gone", http_request.client)

        return EventStream(stream())

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

    @app.post("/api/say", tags=["ljud"])
    def say(body: SayBody) -> dict:
        """Speaks the text on the panel (text-to-speech; one OpenAI call).
        At most one every say_min_interval seconds; 409 while the panel
        is muted. Answers when the speech has been played."""
        return run("say", timeout=cfg.web_say_timeout, text=body.text)

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

    # ---- test triggers (the signals' siblings) ---------------------------------

    @app.post("/api/test/morning", tags=["test"])
    def morning_test() -> dict:
        """The morning routine compressed, alarm in two minutes (SIGUSR1)."""
        return run("morning_test")

    @app.post("/api/test/night", tags=["test"])
    def night_test() -> dict:
        """The night-off now (SIGUSR2)."""
        return run("night_test")

    # ---- preset clips ----------------------------------------------------------

    @app.get("/api/presets", tags=["knappljud"])
    def presets() -> list[dict]:
        """The ten audio buttons: name, whether a default exists, and
        whether the active clip is the default or a recording."""
        return run("presets")

    @app.get("/api/presets/{pin}/audio", tags=["knappljud"])
    def preset_audio(pin: Pin, which: Literal["active", "default"] = "active"):
        """The clip itself (WAV), for listening on the phone."""
        base = cfg.preset_sounds_dir if which == "active" else cfg.preset_defaults_dir
        path = base / f"btn_{pin}.wav"
        if not path.is_file():
            raise HTTPException(404, "Inget klipp")
        return FileResponse(
            path,
            media_type="audio/wav",
            filename=f"knapp{pin}-{which}.wav",
            headers={"Cache-Control": "no-cache"},
        )

    @app.put("/api/presets/{pin}/default", tags=["knappljud"])
    def upload_default(
        pin: Pin,
        request: Request,
        file: UploadFile = File(..., description="any audio format; ffmpeg converts it"),
        activate: bool = Form(True, description="also make it the active clip"),
    ) -> dict:
        """A new default clip for the button. 413 over
        preset_upload_max_bytes, 409 when it is not audio or too long."""
        limit = cfg.preset_upload_max_bytes
        too_big = HTTPException(413, f"Filen är för stor (max {max(1, limit // (1024 * 1024))} MB)")
        # The header counts the multipart framing too; the exact check is on the bytes.
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > limit + UPLOAD_CHUNK:
            raise too_big
        cfg.preset_upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = pathlib.PurePath(file.filename or "").suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            suffix = ".bin"
        fd, tmp = tempfile.mkstemp(prefix="upload-", suffix=suffix, dir=cfg.preset_upload_dir)
        written = 0
        with os.fdopen(fd, "wb") as out:
            while chunk := file.file.read(UPLOAD_CHUNK):
                written += len(chunk)
                if written > limit:
                    break
                out.write(chunk)
        if written > limit:
            os.remove(tmp)
            raise too_big
        return run(
            "set_preset_default",
            timeout=cfg.preset_upload_timeout,
            pin=pin,
            path=tmp,
            activate=activate,
            source=file.filename,
        )

    @app.post("/api/presets/{pin}/restore", tags=["knappljud"])
    def restore_preset(pin: Pin) -> dict:
        """The default becomes the active clip again (404 without one)."""
        return run("restore_preset", pin=pin)

    @app.patch("/api/presets/{pin}", tags=["knappljud"])
    def rename_preset(pin: Pin, body: NameBody) -> dict:
        return run("rename_preset", pin=pin, name=body.name)

    # ---- the page --------------------------------------------------------------

    app.add_middleware(ResponseHeaders)

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

    def __init__(self, config: Config, request: RequestFn):
        self._cfg = config
        self.broadcast = StateBroadcast()  # ControlPanel publishes state changes here
        self.app = build_app(request, config, self.broadcast)
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
