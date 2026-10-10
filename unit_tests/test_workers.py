#!/usr/bin/env python
"""Unit tests for daemon.workers."""

import threading
import unittest

from daemon.workers import Workers


class TestWorkers(unittest.TestCase):
    def _make(self, count: int = 1) -> Workers:
        workers = Workers("test", count)
        self.addCleanup(workers.stop)
        return workers

    def test_submit_resultInFuture(self):
        # arrange
        workers = self._make()
        workers.start()

        # act
        future = workers.submit(lambda a, b: a + b, 2, 3)

        # assert
        self.assertEqual(5, future.result(timeout=2))

    def test_submit_exceptionInFuture(self):
        # arrange
        workers = self._make()
        workers.start()

        def boom():
            raise ValueError("nope")

        # act
        future = workers.submit(boom)

        # assert
        self.assertIsInstance(future.exception(timeout=2), ValueError)

    def test_oneThread_runsJobsInOrder(self):
        # arrange
        workers = self._make()
        workers.start()
        order = []

        # act
        futures = [workers.submit(order.append, i) for i in range(20)]
        for f in futures:
            f.result(timeout=2)

        # assert
        self.assertEqual(list(range(20)), order)

    def test_threadsAreDaemonThreads(self):
        # arrange
        workers = self._make(count=2)

        # act
        workers.start()

        # assert
        self.assertEqual(2, len(workers._threads))
        self.assertTrue(all(t.daemon for t in workers._threads))

    def test_stop_cancelsQueuedJobs(self):
        # arrange
        workers = self._make()
        workers.start()
        started, release = threading.Event(), threading.Event()

        def blocker():
            started.set()
            return release.wait(2)

        running = workers.submit(blocker)
        queued = workers.submit(lambda: "never")
        self.assertTrue(started.wait(2))

        # act
        workers.stop()
        release.set()

        # assert
        self.assertTrue(queued.cancelled())
        self.assertTrue(running.result(timeout=2))

    def test_stop_beforeStartAndTwiceIsNoop(self):
        # arrange
        workers = self._make()

        # act / assert (no exception, no hang)
        workers.stop()
        workers.start()
        workers.stop()
        workers.stop()
        self.assertEqual([], workers._threads)


if __name__ == "__main__":
    unittest.main()
