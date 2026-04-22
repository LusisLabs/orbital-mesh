"""Tests for :class:`KubernetesWatcher` — typed K8s deployment poller.

Mirrors the legacy ``test_watch_daemon.py`` coverage but exercises the
new :class:`Watcher` protocol entry point (``tick()``) directly so the
underlying logic is covered independently from the deprecated wrapper.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.watchers.kubernetes import (
    KubernetesWatcher,
    WatchTarget,
    _DeduplicationEntry,
)


def _healthy_signal():
    return {
        "deployment": {"rollout_status": "healthy"},
        "pods": [
            {"name": "pod-1", "ready": True, "restarts": 0,
             "container_status": "Running", "last_state_reason": ""},
        ],
    }


def _unhealthy_signal():
    return {
        "deployment": {"rollout_status": "degraded"},
        "pods": [
            {"name": "pod-1", "ready": False, "restarts": 3,
             "container_status": "CrashLoopBackOff", "last_state_reason": "Error"},
            {"name": "pod-2", "ready": True, "restarts": 0,
             "container_status": "Running", "last_state_reason": ""},
        ],
    }


def _make_coordinator(*, run_status: str = "completed", run_id: str = "run_test"):
    coordinator = MagicMock()
    coordinator.config = MagicMock()
    coordinator.config.kubectl_command = "kubectl"
    coordinator.get_run.return_value = {"status": run_status}
    coordinator.create_run.return_value = {"run_id": run_id}
    return coordinator


class KubernetesWatcherProtocolTests(unittest.TestCase):
    def test_signal_source_constant(self):
        self.assertEqual(KubernetesWatcher.signal_source, "kubernetes")

    def test_status_includes_target_summary(self):
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=_make_coordinator(),
            targets=[WatchTarget("api", "default"), WatchTarget("worker", "jobs")],
        )
        status = watcher.status()
        self.assertEqual(status["name"], "prod")
        self.assertEqual(status["target_count"], 2)
        self.assertEqual(status["signal_source"], "kubernetes")
        self.assertEqual(status["runs_created"], 0)


class KubernetesWatcherStaticHelperTests(unittest.TestCase):
    def test_is_actionable_healthy(self):
        self.assertFalse(KubernetesWatcher._is_actionable(_healthy_signal()))

    def test_is_actionable_unhealthy(self):
        self.assertTrue(KubernetesWatcher._is_actionable(_unhealthy_signal()))

    def test_extract_error_signature(self):
        sig = KubernetesWatcher._extract_error_signature(_unhealthy_signal())
        self.assertIn("CrashLoopBackOff", sig)
        self.assertIn("Error", sig)

    def test_extract_error_signature_healthy(self):
        sig = KubernetesWatcher._extract_error_signature(_healthy_signal())
        self.assertEqual(sig, "healthy")


class KubernetesWatcherTickTests(unittest.TestCase):
    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_creates_run_for_unhealthy_deployment(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = _make_coordinator()
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            default_cooldown_seconds=0,
        )
        watcher.tick()
        coordinator.create_run.assert_called_once()
        payload = coordinator.create_run.call_args[0][0]
        self.assertEqual(payload["live_signal"]["deployment_name"], "app")
        self.assertEqual(payload["live_signal"]["watcher_name"], "prod")
        self.assertEqual(payload["steering_mode"], "interruptible_auto")
        self.assertEqual(watcher.status()["runs_created"], 1)

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_skips_healthy_deployment(self, mock_collect):
        mock_collect.return_value = _healthy_signal()
        coordinator = _make_coordinator()
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
        )
        watcher.tick()
        coordinator.create_run.assert_not_called()

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_dedup_blocks_repeat_runs(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = _make_coordinator()
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            default_cooldown_seconds=0,
        )
        watcher.tick()
        watcher.tick()
        self.assertEqual(coordinator.create_run.call_count, 1)

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_cooldown_prevents_rapid_runs(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = _make_coordinator()
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            default_cooldown_seconds=300,
        )
        watcher.tick()
        # Different signature, but cooldown still applies.
        mock_collect.return_value = {
            "deployment": {"rollout_status": "degraded"},
            "pods": [{"name": "pod-1", "ready": False, "restarts": 5,
                      "container_status": "OOMKilled", "last_state_reason": "OOMKilled"}],
        }
        watcher.tick()
        self.assertEqual(coordinator.create_run.call_count, 1)

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_skips_when_active_run_in_progress(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = _make_coordinator(run_status="running", run_id="run_active")
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            default_cooldown_seconds=0,
        )
        watcher._dedup[("default", "app")] = _DeduplicationEntry(active_run_id="run_active")
        watcher.tick()
        coordinator.create_run.assert_not_called()

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_correlator_is_invoked_when_provided(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = _make_coordinator()
        correlator = MagicMock()
        correlation = MagicMock()
        correlation.correlation_type = "same_namespace"
        correlation.to_dict.return_value = {"type": "same_namespace", "affected_services": ["app"]}
        correlator.correlate.return_value = correlation
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            default_cooldown_seconds=0,
            correlator=correlator,
        )
        watcher.tick()
        correlator.correlate.assert_called_once()
        payload = coordinator.create_run.call_args[0][0]
        self.assertEqual(payload["live_signal"]["correlation"]["type"], "same_namespace")

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_tick_continues_after_per_target_exception(self, mock_collect):
        # First target raises, second succeeds — watcher should not abort.
        mock_collect.side_effect = [
            RuntimeError("kubectl exploded"),
            _unhealthy_signal(),
        ]
        coordinator = _make_coordinator()
        watcher = KubernetesWatcher(
            name="prod",
            coordinator=coordinator,
            targets=[WatchTarget("a", "default"), WatchTarget("b", "default")],
            default_cooldown_seconds=0,
        )
        watcher.tick()
        coordinator.create_run.assert_called_once()
        self.assertIn("kubectl exploded", watcher.status()["last_error"])


if __name__ == "__main__":
    unittest.main()
