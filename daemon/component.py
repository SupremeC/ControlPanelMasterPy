"""Lifecycle contract shared by the daemon's components."""

from typing import Protocol


class Component(Protocol):
    """A part of the daemon that owns threads or hardware.

    - The constructor only stores configuration. No ports, devices,
      files or threads are opened there.
    - start() opens resources and starts threads. Threads are daemon
      threads and wait on the component's own stop event, never on
      time.sleep().
    - stop() signals the threads, joins them with a timeout and releases
      resources. It is safe to call more than once and before start().
    """

    def start(self) -> None:
        """Open resources and start worker threads."""

    def stop(self) -> None:
        """Stop worker threads and release resources."""
