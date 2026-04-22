"""WatcherRegistry — thread-lifecycle + status aggregation for typed watchers.

Each watcher runs on its own daemon thread and handles its own polling cadence,
dedup, and coordinator calls.  The registry owns the thread set and exposes a
uniform ``start/stop/status`` surface to the control plane.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Protocol, runtime_checkable


_LOG = logging.getLogger("mesh.watcher_registry")


# Jitter cap as a fraction of the watcher's interval (0.2 => ±20%).
# Prevents thundering herd when many watchers start at once with aligned cadence.
_JITTER_FRACTION = 0.2


@runtime_checkable
class Watcher(Protocol):
    """Structural protocol every watcher must satisfy.

    Watchers are responsible for their own dedup / cooldown / run creation.
    The registry only coordinates threading.
    """

    name: str
    signal_source: str  # e.g. "kubernetes", "feature_flag", "argocd", "prometheus"
    interval_seconds: int

    def tick(self) -> None:
        """Run one poll cycle. Called repeatedly by the registry thread."""

    def status(self) -> dict[str, Any]:
        """Return watcher health/stats for the /api/watchers endpoint."""


class WatcherRegistry:
    """Registry that holds N typed watchers, each with its own thread."""

    def __init__(self) -> None:
        self._watchers: dict[str, Watcher] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, watcher: Watcher) -> None:
        """Register a watcher by name. Replacing an existing entry first stops it."""
        if not isinstance(watcher, Watcher):  # structural check
            raise TypeError(
                f"register() requires an object implementing the Watcher protocol "
                f"(got {type(watcher).__name__})"
            )
        with self._lock:
            # Use the locked predicate helper directly — calling the public
            # ``is_running`` would re-enter ``self._lock`` and deadlock.
            if watcher.name in self._watchers and self._thread_is_alive_locked(watcher.name):
                # Gracefully stop the old one under the same name.
                self._stop_locked(watcher.name, timeout=2.0)
            self._watchers[watcher.name] = watcher

    def unregister(self, name: str, *, timeout: float = 5.0) -> None:
        with self._lock:
            if name not in self._watchers:
                return
            if self._thread_is_alive_locked(name):
                self._stop_locked(name, timeout=timeout)
            self._watchers.pop(name, None)
            self._threads.pop(name, None)
            self._stop_events.pop(name, None)

    def list_names(self) -> list[str]:
        with self._lock:
            return sorted(self._watchers)

    def get(self, name: str) -> Watcher | None:
        with self._lock:
            return self._watchers.get(name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, name: str) -> None:
        with self._lock:
            watcher = self._watchers.get(name)
            if watcher is None:
                raise KeyError(f"no watcher registered with name {name!r}")
            if self._thread_is_alive_locked(name):
                return
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_loop,
                args=(watcher, stop_event),
                daemon=True,
                name=f"mesh-watcher-{name}",
            )
            self._stop_events[name] = stop_event
            self._threads[name] = thread
            thread.start()
            _LOG.info(
                "Watcher %r started (source=%s interval=%ds)",
                name,
                watcher.signal_source,
                watcher.interval_seconds,
            )

    def stop(self, name: str, *, timeout: float = 5.0) -> None:
        with self._lock:
            self._stop_locked(name, timeout=timeout)

    def start_all(self) -> None:
        for name in self.list_names():
            self.start(name)

    def stop_all(self, *, timeout: float = 5.0) -> None:
        for name in self.list_names():
            self.stop(name, timeout=timeout)

    def is_running(self, name: str) -> bool:
        # Callers holding the lock should use _thread_is_alive_locked.
        with self._lock:
            return self._thread_is_alive_locked(name)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "watchers": [
                    {
                        "name": name,
                        "signal_source": watcher.signal_source,
                        "interval_seconds": watcher.interval_seconds,
                        "running": self._thread_is_alive_locked(name),
                        "detail": watcher.status(),
                    }
                    for name, watcher in self._watchers.items()
                ],
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _stop_locked(self, name: str, *, timeout: float) -> None:
        stop_event = self._stop_events.get(name)
        thread = self._threads.get(name)
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._threads.pop(name, None)
        # Keep the stop_event around as a signal that the watcher was started
        # previously; start() creates a fresh one.

    def _thread_is_alive_locked(self, name: str) -> bool:
        thread = self._threads.get(name)
        return thread is not None and thread.is_alive()

    def _run_loop(self, watcher: Watcher, stop_event: threading.Event) -> None:
        interval = max(int(watcher.interval_seconds), 10)
        # Jitter the first sleep so concurrently-started watchers don't align.
        initial_delay = interval * _JITTER_FRACTION * random.random()
        if initial_delay > 0 and stop_event.wait(timeout=initial_delay):
            return
        while not stop_event.is_set():
            start = time.monotonic()
            try:
                watcher.tick()
            except Exception:
                _LOG.exception("Watcher %r tick() raised", watcher.name)
            elapsed = time.monotonic() - start
            # Sleep the remainder of the interval, capped at 0 so a slow tick
            # doesn't wedge the loop into tight-polling on the next pass.
            sleep_seconds = max(0.0, interval - elapsed)
            if sleep_seconds and stop_event.wait(timeout=sleep_seconds):
                break
