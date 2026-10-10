"""Background job lane running on daemon threads."""

import logging
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable

logger = logging.getLogger("daemon.workers")


class Workers:
    """Runs blocking jobs (OpenAI calls, audio effects, playback) off the
    main thread. With count=1, jobs run one at a time in submission order.

    concurrent.futures.ThreadPoolExecutor is not used because it joins its
    threads when the interpreter exits: a job stuck in an OpenAI call or in
    audio playback would keep the process alive until systemd kills it.
    """

    THREAD_JOIN_TIMEOUT = 1  # seconds

    def __init__(self, name: str, count: int = 1):
        self._name = name
        self._count = count
        self._jobs: queue.Queue = queue.Queue()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Starts the worker threads."""
        if self._threads:
            return
        for i in range(self._count):
            thread = threading.Thread(
                target=self._run, name=f"{self._name}-{i}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Cancels queued jobs and stops the threads. A job that is already
        running is left to finish on its daemon thread. Safe to call more
        than once, and before start()."""
        if not self._threads:
            return
        while True:
            try:
                item = self._jobs.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                item[0].cancel()
        for _ in self._threads:
            self._jobs.put(None)
        for thread in self._threads:
            thread.join(self.THREAD_JOIN_TIMEOUT)
            if thread.is_alive():
                logger.warning("%s is still busy at shutdown", thread.name)
        self._threads = []

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        """Queues fn(*args). The returned Future holds its result or exception."""
        future: Future = Future()
        self._jobs.put((future, fn, args))
        return future

    def _run(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            future, fn, args = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = fn(*args)
            except Exception as e:  # handed to the main thread via the Future
                future.set_exception(e)
            else:
                future.set_result(result)
