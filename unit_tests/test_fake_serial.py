#!/usr/bin/env python
"""ControlPanel driven through a fake Mega connection, plus Config wiring.

Every component that touches hardware is replaced (FakeSerial for the
Mega, mocks for audio, WLED and the calendar), so start() is safe here.
Never call start() on a ControlPanel with its real components.
"""

from pathlib import Path
from queue import Empty, Queue
import time
import unittest
import unittest.mock as mock

from daemon.config import Config
from daemon.controlpanel_class import ControlPanel
from daemon.global_variables import root_path
from daemon.packet import HWEvent, Packet


class FakeSerial:
    """Stands in for PacketSerial: it 'connects' on start(), receive()
    posts a packet the way the reader thread does, and sent() returns what
    ControlPanel queued for the Mega."""

    def __init__(self, events: Queue, sendqueue: Queue):
        self._events = events
        self._sendqueue = sendqueue
        self.connected_at = None

    def start(self) -> None:
        self.connected_at = time.monotonic()

    def stop(self) -> None:
        pass

    def send_hello(self) -> None:
        self._sendqueue.put(Packet(HWEvent.HELLO, 1, 1))

    def receive(self, packet: Packet) -> None:
        self._events.put(packet)

    def sent(self) -> list[Packet]:
        packets = []
        while True:
            try:
                packets.append(self._sendqueue.get_nowait())
            except Empty:
                return packets


class TestControlPanelWithFakeSerial(unittest.TestCase):
    def setUp(self):
        cp = ControlPanel(Config(resync_after_connect=0.3, hello_interval=1000))
        self.mega = FakeSerial(cp._events, cp._packet_sendqueue)
        cp._pserial = self.mega
        cp._audioctrl = mock.Mock()
        cp.wled_instance = mock.Mock()
        cp.cal = mock.Mock()
        cp.weather = mock.Mock()
        cp.start()
        self.addCleanup(cp.stop)
        self.cp = cp

    def run_loop(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.cp.process(max_wait=0.02)

    @staticmethod
    def status_requests(packets: list[Packet]) -> int:
        return sum(1 for p in packets if p.hw_event == HWEvent.STATUS)

    def test_start_requestsStatusAndSaysHello(self):
        # act
        self.run_loop(0.05)

        # assert
        sent = self.mega.sent()
        self.assertEqual(1, self.status_requests(sent))
        self.assertIn(HWEvent.HELLO, [p.hw_event for p in sent])

    def test_bootMega_requestsStatusAndNoResyncLater(self):
        # arrange
        self.run_loop(0.05)
        self.mega.sent()

        # act
        self.mega.receive(Packet(HWEvent.BOOTMEGA, 0, 1))
        self.run_loop(0.5)

        # assert: one request for the BOOTMEGA, none from the resync timer
        self.assertEqual(1, self.status_requests(self.mega.sent()))

    def test_noBootMega_resyncRequestsStatus(self):
        # arrange
        self.run_loop(0.05)
        self.mega.sent()

        # act
        with self.assertLogs("daemon.ctrlPanel", "INFO") as logs:
            self.run_loop(0.5)

        # assert
        self.assertEqual(1, self.status_requests(self.mega.sent()))
        self.assertTrue(any("No BOOTMEGA" in line for line in logs.output))

    def test_statusReplies_updateSwitchStates(self):
        # act
        self.mega.receive(Packet(HWEvent.STATUS, 12, 1))
        self.mega.receive(Packet(HWEvent.STATUS, 15, 1))
        self.run_loop(0.05)

        # assert
        self.assertTrue(self.cp._ctrls.get_ctrl_by_name("masterSw").state)
        self.assertTrue(self.cp._ctrls.get_ctrl_by_name("InputsSw").state)

    def test_masterSwitchOff_turnsLedsOffAndWled(self):
        # arrange
        self.mega.receive(Packet(HWEvent.STATUS, 12, 1))
        self.run_loop(0.05)
        self.mega.sent()

        # act
        self.mega.receive(Packet(HWEvent.SWITCH, 12, 0))
        self.run_loop(0.2)

        # assert
        sent = self.mega.sent()
        self.assertTrue(sent, "LED-off packets expected")
        self.assertTrue(all(p.val == 0 for p in sent if p.hw_event == HWEvent.LED))
        self.cp.wled_instance.set_wled_state.assert_called_once_with(False)


class TestConfig(unittest.TestCase):
    def test_secretPaths_areUnderTheRepoRoot(self):
        # act
        cfg = Config()

        # assert
        for path in (cfg.openai_key_file, cfg.google_token_file):
            self.assertTrue(path.is_absolute())
            self.assertEqual(root_path / "daemon", path.parent)

    def test_controlPanel_passesConfigToComponents(self):
        # arrange
        cfg = Config(
            mega_baud=9600,
            mega_reconnect_interval=2,
            wled_port="/dev/fake",
            wled_baud=115200,
            calendar_update_interval=30,
            openai_key_file=Path("/x/key"),
            google_token_file=Path("/x/token.json"),
        )

        # act
        cp = ControlPanel(cfg)

        # assert
        self.assertEqual(9600, cp._pserial.BAUDRATE)
        self.assertEqual(2, cp._pserial.RECONNECT_INTERVAL)
        self.assertEqual("/dev/fake", cp.wled_instance._uart_port)
        self.assertEqual(115200, cp.wled_instance._baud_rate)
        self.assertEqual(30, cp.cal.UPDATE_INTERVAL)
        self.assertEqual(Path("/x/token.json"), cp.cal._token_file)
        self.assertEqual(Path("/x/key"), cp.ai._key_path)


if __name__ == "__main__":
    unittest.main()
