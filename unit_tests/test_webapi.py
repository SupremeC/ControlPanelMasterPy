"""Unit tests for daemon.webapi: the HTTP layer over a fake request().

The fake records which Remote command each route asks for and answers
from a table, so no ControlPanel is involved. One test binds a real
socket (port 0) to check start()/stop()."""

from concurrent.futures import Future
import json
from pathlib import Path
import tempfile
import unittest
import urllib.request

from fastapi.testclient import TestClient

from daemon.config import Config
from daemon.webapi import WebApi


class FakeRequest:
    """request(name, **kwargs) -> Future, answered from `answers`:
    a value, an exception instance, or None for a Future that never
    finishes."""

    def __init__(self, answers: dict | None = None):
        self.answers = answers or {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, command: str, **kwargs) -> Future:
        self.calls.append((command, kwargs))
        future: Future = Future()
        answer = self.answers.get(command, {"ok": True})
        if answer is None:
            return future
        if isinstance(answer, BaseException):
            future.set_exception(answer)
        else:
            future.set_result(answer)
        return future


def make_client(fake: FakeRequest, raise_server_exceptions: bool = True) -> TestClient:
    cfg = Config(
        web_enabled=False,
        web_dir=Path(tempfile.gettempdir()) / "no-such-web-dir",
        web_command_timeout=0.05,
    )
    return TestClient(WebApi(cfg, fake).app, raise_server_exceptions=raise_server_exceptions)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRequest(
            {"state": {"demo": False, "text": {"demo": "Av"}}, "list_sounds": []}
        )
        self.client = make_client(self.fake)

    def test_state(self):
        # act
        response = self.client.get("/api/state")

        # assert
        self.assertEqual(200, response.status_code)
        self.assertEqual("Av", response.json()["text"]["demo"])
        self.assertEqual([("state", {})], self.fake.calls)

    def test_socket_body(self):
        # act
        response = self.client.post("/api/sockets/bed", json={"on": True})

        # assert
        self.assertEqual(200, response.status_code)
        self.assertEqual([("set_socket", {"name": "bed", "on": True})], self.fake.calls)

    def test_socket_actions(self):
        # act
        self.client.post("/api/sockets/drawer/off")
        self.client.post("/api/sockets/drawer/toggle")

        # assert
        self.assertEqual(
            [
                ("set_socket", {"name": "drawer", "on": False}),
                ("toggle_socket", {"name": "drawer"}),
            ],
            self.fake.calls,
        )

    def test_badBody_422(self):
        # act
        response = self.client.post("/api/sockets/bed", json={"on": "ja"})

        # assert
        self.assertEqual(422, response.status_code)
        self.assertEqual([], self.fake.calls)

    def test_unknownSocket_422(self):
        self.assertEqual(422, self.client.post("/api/sockets/garage/on").status_code)
        self.assertEqual([], self.fake.calls)

    def test_getOnActionRoute_notAllowed(self):
        self.assertEqual(405, self.client.get("/api/sockets/bed/toggle").status_code)
        self.assertEqual([], self.fake.calls)

    def test_lampsAndDemo(self):
        # act
        self.client.post("/api/bedlamp/toggle")
        self.client.post("/api/backlight", json={"on": False})
        self.client.post("/api/backlight/toggle")
        self.client.post("/api/leds/on")
        self.client.post("/api/demo", json={"on": True})
        self.client.post("/api/all-off")

        # assert
        self.assertEqual(
            [
                ("bed_lamp_toggle", {}),
                ("set_backlight", {"on": False}),
                ("toggle_backlight", {}),
                ("set_button_leds", {"on": True}),
                ("set_demo", {"on": True}),
                ("all_off", {}),
            ],
            self.fake.calls,
        )

    def test_sounds(self):
        # act
        self.client.get("/api/sounds")
        self.client.post("/api/sounds/btn_5")
        self.client.post("/api/audio/stop")
        self.client.post("/api/audio/mute")
        self.client.post("/api/audio/unmute")
        self.client.post("/api/audio/volume", json={"percent": 40})
        self.client.post("/api/audio/volume/down")
        self.client.post("/api/audio/volume/up?step=10")

        # assert
        self.assertEqual(
            [
                ("list_sounds", {}),
                ("play_sound", {"id": "btn_5"}),
                ("stop_audio", {}),
                ("mute", {}),
                ("unmute", {}),
                ("set_volume", {"percent": 40}),
                ("step_volume", {"delta": -5}),
                ("step_volume", {"delta": 10}),
            ],
            self.fake.calls,
        )

    def test_volume_outOfRange_422(self):
        self.assertEqual(
            422, self.client.post("/api/audio/volume", json={"percent": 101}).status_code
        )
        self.assertEqual(422, self.client.post("/api/audio/volume/up?step=0").status_code)

    def test_strips(self):
        # act
        self.client.post(
            "/api/strips/0", json={"on": True, "brightness": 200, "color": [255, 0, 10]}
        )
        self.client.post("/api/strips/1", json={"effect": "next"})
        self.client.post("/api/strips/1/toggle")
        self.client.post("/api/strips/0/brightness/down")
        self.client.post("/api/strips/0/brightness/up?step=32")
        self.client.post("/api/strips/1/effect/off")

        # assert
        self.assertEqual(
            [
                ("set_strip", {"segment": 0, "on": True, "brightness": 200, "color": [255, 0, 10]}),
                ("set_strip", {"segment": 1, "effect": "next"}),
                ("toggle_strip", {"segment": 1}),
                ("step_brightness", {"segment": 0, "delta": -16}),
                ("step_brightness", {"segment": 0, "delta": 32}),
                ("strip_effect", {"segment": 1, "which": "off"}),
            ],
            self.fake.calls,
        )

    def test_strip_validation_422(self):
        self.assertEqual(422, self.client.post("/api/strips/2/on").status_code)
        self.assertEqual(
            422, self.client.post("/api/strips/0", json={"brightness": 256}).status_code
        )
        self.assertEqual(
            422, self.client.post("/api/strips/0", json={"color": [1, 2]}).status_code
        )
        self.assertEqual(
            422, self.client.post("/api/strips/0", json={"effect": "random"}).status_code
        )
        self.assertEqual([], self.fake.calls)

    def test_placeholderPage_linksToDocs(self):
        # act
        response = self.client.get("/")

        # assert
        self.assertEqual(200, response.status_code)
        self.assertIn("/docs", response.text)
        self.assertEqual(200, self.client.get("/openapi.json").status_code)


class TestErrors(unittest.TestCase):
    def test_keyError_404(self):
        client = make_client(FakeRequest({"play_sound": KeyError("btn_99")}))
        response = client.post("/api/sounds/btn_99")
        self.assertEqual(404, response.status_code)
        self.assertEqual("Finns inte: btn_99", response.json()["detail"])

    def test_valueError_409(self):
        client = make_client(FakeRequest({"set_demo": ValueError("Panelen är av")}))
        response = client.post("/api/demo/on")
        self.assertEqual(409, response.status_code)
        self.assertEqual("Panelen är av", response.json()["detail"])

    def test_typeError_400(self):
        client = make_client(FakeRequest({"state": TypeError("bad")}))
        self.assertEqual(400, client.get("/api/state").status_code)

    def test_timeout_504(self):
        client = make_client(FakeRequest({"state": None}))
        response = client.get("/api/state")
        self.assertEqual(504, response.status_code)
        self.assertEqual("Panelen svarar inte", response.json()["detail"])

    def test_otherError_500(self):
        client = make_client(
            FakeRequest({"state": RuntimeError("boom")}), raise_server_exceptions=False
        )
        self.assertEqual(500, client.get("/api/state").status_code)


class TestStaticPage(unittest.TestCase):
    def test_pageServedFromWebDir(self):
        # arrange
        web_dir = Path(tempfile.mkdtemp())
        (web_dir / "index.html").write_text("<h1>Kontrollpanelen</h1>", encoding="utf-8")
        (web_dir / "app.js").write_text("// js", encoding="utf-8")
        cfg = Config(web_enabled=False, web_dir=web_dir)
        client = TestClient(WebApi(cfg, FakeRequest()).app)

        # act / assert
        self.assertIn("Kontrollpanelen", client.get("/").text)
        self.assertEqual("// js", client.get("/app.js").text)
        self.assertEqual(404, client.get("/nope.css").status_code)
        self.assertEqual(200, client.get("/api/state").status_code)  # API first


class TestLifecycle(unittest.TestCase):
    def test_stopBeforeStart_noop(self):
        api = WebApi(Config(web_enabled=False), FakeRequest())
        api.stop()
        api.stop()
        self.assertIsNone(api.port)

    def test_startServesAndStops(self):
        # arrange: port 0 = any free port, loopback only
        cfg = Config(
            web_enabled=False,
            web_host="127.0.0.1",
            web_port=0,
            web_dir=Path(tempfile.gettempdir()) / "no-such-web-dir",
        )
        api = WebApi(cfg, FakeRequest({"state": {"demo": True}}))
        self.addCleanup(api.stop)

        # act
        api.start()
        port = api.port
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=3) as r:
            body = json.load(r)
        api.stop()

        # assert
        self.assertIsNotNone(port)
        self.assertTrue(body["demo"])
        self.assertFalse(api._thread and api._thread.is_alive())
        self.assertIsNone(api._thread)


if __name__ == "__main__":
    unittest.main()
