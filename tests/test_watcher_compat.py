"""Tests for the legacy MESH_WATCH_TARGETS → KubernetesWatcher compat shim."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from services.watchers.base import WatcherRegistry
from services.watchers.compat import LEGACY_WATCHER_NAME, register_legacy_watchers


def _coordinator(*, watch_enabled: bool, watch_targets: tuple[dict, ...]):
    coordinator = MagicMock()
    coordinator.config = MagicMock()
    coordinator.config.watch_enabled = watch_enabled
    coordinator.config.watch_targets = watch_targets
    coordinator.config.kubectl_command = "kubectl"
    coordinator.config.watch_interval_seconds = 60
    coordinator.config.watch_cooldown_seconds = 300
    return coordinator


class CompatShimTests(unittest.TestCase):
    def setUp(self):
        # Ensure the new config env var is unset for every test by default.
        self._original_env = os.environ.pop("MESH_WATCHER_CONFIG_PATH", None)

    def tearDown(self):
        if self._original_env is not None:
            os.environ["MESH_WATCHER_CONFIG_PATH"] = self._original_env

    def test_no_targets_skips_registration(self):
        registry = WatcherRegistry()
        coordinator = _coordinator(watch_enabled=True, watch_targets=())
        result = register_legacy_watchers(coordinator=coordinator, registry=registry)
        self.assertFalse(result)
        self.assertEqual(registry.list_names(), [])

    def test_disabled_skips_registration(self):
        registry = WatcherRegistry()
        coordinator = _coordinator(
            watch_enabled=False,
            watch_targets=({"deployment_name": "app", "namespace": "default"},),
        )
        result = register_legacy_watchers(coordinator=coordinator, registry=registry)
        self.assertFalse(result)
        self.assertEqual(registry.list_names(), [])

    def test_legacy_targets_register_kubernetes_watcher(self):
        registry = WatcherRegistry()
        coordinator = _coordinator(
            watch_enabled=True,
            watch_targets=(
                {"deployment_name": "app", "namespace": "default"},
                {"deployment_name": "worker", "namespace": "jobs", "kube_context": "prod"},
            ),
        )
        result = register_legacy_watchers(coordinator=coordinator, registry=registry)
        self.assertTrue(result)
        self.assertEqual(registry.list_names(), [LEGACY_WATCHER_NAME])
        watcher = registry.get(LEGACY_WATCHER_NAME)
        self.assertIsNotNone(watcher)
        self.assertEqual(watcher.signal_source, "kubernetes")
        self.assertEqual(len(watcher.targets), 2)

    def test_new_config_path_skips_legacy_shim(self):
        registry = WatcherRegistry()
        coordinator = _coordinator(
            watch_enabled=True,
            watch_targets=({"deployment_name": "app"},),
        )
        with patch.dict(os.environ, {"MESH_WATCHER_CONFIG_PATH": "/tmp/watchers.json"}):
            result = register_legacy_watchers(coordinator=coordinator, registry=registry)
        self.assertFalse(result)
        self.assertEqual(registry.list_names(), [])

    def test_invalid_target_entries_are_skipped(self):
        registry = WatcherRegistry()
        coordinator = _coordinator(
            watch_enabled=True,
            watch_targets=(
                "not-a-dict",  # type: ignore[arg-type]
                {"namespace": "default"},  # missing deployment_name
                {"deployment_name": "app", "namespace": "default"},
            ),
        )
        result = register_legacy_watchers(coordinator=coordinator, registry=registry)
        self.assertTrue(result)
        watcher = registry.get(LEGACY_WATCHER_NAME)
        self.assertEqual(len(watcher.targets), 1)
        self.assertEqual(watcher.targets[0].deployment_name, "app")


if __name__ == "__main__":
    unittest.main()
