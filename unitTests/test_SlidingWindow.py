#!/usr/bin/env python

import unittest  # noqa
from time import time, sleep
from daemon.slidingWindowClass import SlidingWindow


class Test_SlidingWindow(unittest.TestCase):
    """
    This UnitTest aims to verify that the system provides
    fractions of Seconds when calling time()

    I doubt this test actually works as intended.
    """

    packets_to_send: int = 100
    packets_per_window: int = 30
    time_window: float = 1

    def test_Time_precisionIsInMillis(self):
        # arrange
        a = time()
        sleep(0.00001)
        b = time()

        self.assertTrue(b > a)

    def test_sendPackets_lowRate(self):
        throttle = SlidingWindow(self.packets_per_window, self.time_window)
        sleep_dur = (self.time_window / self.packets_per_window) * 3
        r = []
        for i in range(self.packets_to_send):
            r.append(throttle.ok_to_send())
            sleep(sleep_dur)
        self.assertTrue(all(r))

        pass

    def test_sendPackets_okRate(self):
        throttle = SlidingWindow(self.packets_per_window, self.time_window)
        sleep_dur = (self.time_window / self.packets_per_window) * 1
        r = []
        for i in range(self.packets_to_send):
            r.append(throttle.ok_to_send())
            sleep(sleep_dur)

        success = 0
        failed = 0
        for x in r:
            if x:
                success += 1
            else:
                failed += 1

        self.assertTrue(
            all(r), f"Expected all {len(r)} to succeed but {failed} failed."
        )
        pass

    def test_sendPackets_wayToHighRate(self):
        throttle = SlidingWindow(self.packets_per_window, self.time_window)
        throttle._pre_count = 0
        sleep_dur = (self.time_window / self.packets_per_window) * 0.1
        buff = []
        for i in range(self.packets_to_send):
            buff.append(throttle.ok_to_send())
            sleep(sleep_dur)

        successCount = 0
        failedCount = 0
        for x in buff:
            if x:
                successCount += 1
            else:
                failedCount += 1

        # At least {self.packets_per_window} calls should have been successful
        self.assertGreaterEqual(
            successCount,
            30,
            f"Expected that at least {self.packets_per_window} of {len(buff)} succeded but {successCount} did",
        )
        # most should have failed
        self.assertGreater(
            failedCount,
            successCount,
            f"Expected that most of {len(buff)} failed but only {failedCount} failed. ({successCount} succeded)",
        )
