"""Tests for :class:`WatcherRegistry` — thread-lifecycle coordinator for typed watchers."""

from __future__ import annotations

import threading
import time
import unittest
from typing import Any

from services.watchers.base import Watcher, WatcherRegistry


class _FakeWatcher:
    """Minimal watcher used to probe registry behavior."""

    signal_source = "fake"

    def __init__(self, name: str, interval_seconds: int = 10) -> None:
        self.name = name
        self.interval_seconds = interval_seconds
        self.tick_count = 0
        self.raise_after: int | None = None
        self._lock = threading.Lock()

    def tick(self) -> None:
        with self._lock:
            self.tick_count += 1
            if self.raise_after is not None and self.tick_count >= self.raise_after:
                raise RuntimeError("tick failed intentionally")

    def status(self) -> dict[str, Any]:
        return {"tick_count": self.tick_count}


class WatcherProtocolTests(unittest.TestCase):
    def test_fake_watcher_satisfies_protocol(self):
        watcher = _FakeWatcher(name="w1")
        self.assertIsInstance(watcher, Watcher)


class WatcherRegistryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.registry = WatcherRegistry()

    def tearDown(self):
        self.registry.stop_all(timeout=2.0)

    def test_register_records_watcher(self):
        w = _FakeWatcher(name="w1")
        self.registry.register(w)
        self.assertIn("w1", self.registry.list_names())
        self.assertIs(self.registry.get("w1"), w)

    def test_register_rejects_non_watcher(self):
        class NotAWatcher:
            pass

        with self.assertRaises(TypeError):
            self.registry.register(NotAWatcher())  # type: ignore[arg-type]

    def test_start_creates_thread_that_ticks(self):
        w = _FakeWatcher(name="w1", interval_seconds=10)
        self.registry.register(w)
        self.registry.start("w1")
        # Wait for the first tick (jitter may delay initial poll by up to 20%).
        deadline = time.monotonic() + 3.0
        while w.tick_count == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertGreaterEqual(w.tick_count, 1)
        self.assertTrue(self.registry.is_running("w1"))

    def test_stop_joins_thread(self):
        w = _FakeWatcher(name="w1", interval_seconds=10)
        self.registry.register(w)
        self.registry.start("w1")
        self.registry.stop("w1", timeout=2.0)
        self.assertFalse(self.registry.is_running("w1"))

    def test_start_unknown_raises(self):
        with self.assertRaises(KeyError):
            self.registry.start("missing")

    def test_start_all_and_stop_all(self):
        a, b = _FakeWatcher("a"), _FakeWatcher("b")
        self.registry.register(a)
        self.registry.register(b)
        self.registry.start_all()
        self.assertTrue(self.registry.is_running("a"))
        self.assertTrue(self.registry.is_running("b"))
        self.registry.stop_all(timeout=2.0)
        self.assertFalse(self.registry.is_running("a"))
        self.assertFalse(self.registry.is_running("b"))

    def test_duplicate_register_replaces_running_watcher(self):
        a1 = _FakeWatcher("a")
        self.registry.register(a1)
        self.registry.start("a")
        self.assertTrue(self.registry.is_running("a"))
        a2 = _FakeWatcher("a")
        # Replacing a running watcher should stop the old thread cleanly.
        self.registry.register(a2)
        self.assertIs(self.registry.get("a"), a2)
        self.assertFalse(self.registry.is_running("a"))

    def test_unregister_stops_and_removes(self):
        a = _FakeWatcher("a")
        self.registry.register(a)
        self.registry.start("a")
        self.registry.unregister("a", timeout=2.0)
        self.assertNotIn("a", self.registry.list_names())
        self.assertFalse(self.registry.is_running("a"))

    def test_tick_exception_does_not_kill_thread(self):
        w = _FakeWatcher(name="w", interval_seconds=10)
        w.raise_after = 1
        self.registry.register(w)
        self.registry.start("w")
        # After the first raising tick, the loop should still be alive and waiting.
        deadline = time.monotonic() + 3.0
        while w.tick_count < 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertGreaterEqual(w.tick_count, 1)
        self.assertTrue(self.registry.is_running("w"))
        self.registry.stop("w", timeout=2.0)

    def test_status_includes_every_watcher(self):
        self.registry.register(_FakeWatcher("a"))
        self.registry.register(_FakeWatcher("b"))
        status = self.registry.status()
        names = {entry["name"] for entry in status["watchers"]}
        self.assertEqual(names, {"a", "b"})
        for entry in status["watchers"]:
            self.assertEqual(entry["signal_source"], "fake")
            self.assertIn("running", entry)
            self.assertIn("detail", entry)


if __name__ == "__main__":
    unittest.main()
