#!/usr/bin/env python
"""The sunrise curve (daemon/sunrise.py) and WLED's frame command.

The curve is tested with fixed colours, so tuning the real ones in
Config does not break the table.
"""

import dataclasses
import unittest
import unittest.mock as mock

from daemon import sunrise
from daemon.config import Config
from daemon.wled import WLED

RED = (255, 20, 0, 0)
AMBER = (255, 100, 0, 0)
WHITE = (255, 140, 40, 255)

CFG = dataclasses.replace(
    Config(),
    sunrise_start_brightness=1,
    sunrise_end_brightness=255,
    sunrise_colour_stops=((0.0, RED), (0.25, AMBER)),
    sunrise_end_rgbw=WHITE,
    sunrise_white_at=0.5,
)


class TestCurve(unittest.TestCase):
    def test_table(self):
        table = [
            (0.0, 1, RED),
            (0.125, 2, (255, 60, 0, 0)),
            (0.25, 4, AMBER),
            (0.5, 16, WHITE),
            (0.75, 64, WHITE),
            (1.0, 255, WHITE),
        ]
        for progress, brightness, rgbw in table:
            with self.subTest(progress=progress):
                self.assertEqual((brightness, rgbw), sunrise.frame(progress, CFG))

    def test_brightnessNeverDrops(self):
        values = [sunrise.frame(i / 1000, CFG).brightness for i in range(1001)]
        self.assertEqual(sorted(values), values)

    def test_outsideRange_isClamped(self):
        self.assertEqual(sunrise.frame(0, CFG), sunrise.frame(-0.5, CFG))
        self.assertEqual(sunrise.frame(1, CFG), sunrise.frame(1.5, CFG))

    def test_endIsExactlyTheConfigEndState(self):
        f = sunrise.frame(1.0)
        self.assertEqual(Config.sunrise_end_brightness, f.brightness)
        self.assertEqual(Config.sunrise_end_rgbw, f.rgbw)


class TestWledFrame(unittest.TestCase):
    def test_setBoth_sendsOneCommandForBothSegments(self):
        # arrange
        wled = WLED()

        # act
        wled.set_both(300, (255, 140, -1, 255), transition=2)

        # assert
        cmd = wled.command_queue.get_nowait()
        self.assertTrue(wled.command_queue.empty())
        self.assertEqual(20, cmd["transition"])
        self.assertEqual([0, 1], [s["id"] for s in cmd["seg"]])
        for seg in cmd["seg"]:
            self.assertEqual(
                {"on": True, "fx": 0, "bri": 255, "col": [[255, 140, 0, 255]]},
                {k: v for k, v in seg.items() if k != "id"},
            )

    def test_setBoth_passesDuringSunrise(self):
        # arrange
        wled = WLED()
        wled._accept_commands = False

        # act
        wled.set_both(10, RED)
        wled.set_brightness(10, 0)

        # assert: only the frame got through
        self.assertEqual(1, wled.command_queue.qsize())

    @mock.patch.object(Config, "sunrise_tick_seconds", 0.01)
    def test_doSunrise_endsAtEndStateAndCallsBack(self):
        # arrange
        wled = WLED()
        frames = []
        wled.set_both = lambda bri, rgbw, transition: frames.append((bri, rgbw))
        done = mock.Mock()

        # act
        wled._do_sunrise(0.1, done)

        # assert
        self.assertEqual(tuple(sunrise.frame(1.0)), frames[-1])
        self.assertGreater(len(frames), 2)
        done.assert_called_once_with()
        self.assertTrue(wled._accept_commands)


if __name__ == "__main__":
    unittest.main()
