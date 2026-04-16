"""Tests for the WatchDaemon — continuous Kubernetes deployment watcher."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.watch_daemon import WatchDaemon, WatchTarget


def _healthy_signal():
    return {
        "deployment": {"rollout_status": "healthy"},
        "pods": [
            {"name": "pod-1", "ready": True, "restarts": 0, "container_status": "Running", "last_state_reason": ""},
        ],
    }


def _unhealthy_signal():
    return {
        "deployment": {"rollout_status": "degraded"},
        "pods": [
            {"name": "pod-1", "ready": False, "restarts": 3, "container_status": "CrashLoopBackOff", "last_state_reason": "Error"},
            {"name": "pod-2", "ready": True, "restarts": 0, "container_status": "Running", "last_state_reason": ""},
        ],
    }


class WatchDaemonTests(unittest.TestCase):
    def _make_coordinator(self):
        coordinator = MagicMock()
        coordinator.config = MagicMock()
        coordinator.config.kubectl_command = "kubectl"
        coordinator.get_run.return_value = {"status": "completed"}
        coordinator.create_run.return_value = {"run_id": "run_test"}
        return coordinator

    def test_starts_and_stops(self):
        daemon = WatchDaemon(
            coordinator=self._make_coordinator(),
            targets=[WatchTarget("app", "default")],
            interval_seconds=10,
        )
        self.assertFalse(daemon.running)
        daemon.start()
        self.assertTrue(daemon.running)
        daemon.stop(timeout=2)
        self.assertFalse(daemon.running)

    def test_status_reports_targets(self):
        daemon = WatchDaemon(
            coordinator=self._make_coordinator(),
            targets=[WatchTarget("app", "default"), WatchTarget("api", "prod")],
            interval_seconds=10,
        )
        status = daemon.status()
        self.assertFalse(status["running"])
        self.assertEqual(len(status["targets"]), 2)
        self.assertEqual(status["targets"][0]["deployment_name"], "app")

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_creates_run_for_unhealthy_deployment(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = self._make_coordinator()
        daemon = WatchDaemon(
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            interval_seconds=10,
            default_cooldown_seconds=0,
        )
        daemon._poll_target(daemon.targets[0])
        coordinator.create_run.assert_called_once()
        call_args = coordinator.create_run.call_args[0][0]
        self.assertEqual(call_args["live_signal"]["deployment_name"], "app")
        self.assertEqual(call_args["steering_mode"], "interruptible_auto")

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_skips_healthy_deployment(self, mock_collect):
        mock_collect.return_value = _healthy_signal()
        coordinator = self._make_coordinator()
        daemon = WatchDaemon(
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            interval_seconds=10,
        )
        daemon._poll_target(daemon.targets[0])
        coordinator.create_run.assert_not_called()

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_dedup_blocks_repeat_runs(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = self._make_coordinator()
        daemon = WatchDaemon(
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            interval_seconds=10,
            default_cooldown_seconds=0,
        )
        daemon._poll_target(daemon.targets[0])
        self.assertEqual(coordinator.create_run.call_count, 1)
        daemon._poll_target(daemon.targets[0])
        self.assertEqual(coordinator.create_run.call_count, 1)

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_cooldown_prevents_rapid_runs(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = self._make_coordinator()
        daemon = WatchDaemon(
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            interval_seconds=10,
            default_cooldown_seconds=300,
        )
        daemon._poll_target(daemon.targets[0])
        self.assertEqual(coordinator.create_run.call_count, 1)
        mock_collect.return_value = {
            "deployment": {"rollout_status": "degraded"},
            "pods": [{"name": "pod-1", "ready": False, "restarts": 5, "container_status": "OOMKilled", "last_state_reason": "OOMKilled"}],
        }
        daemon._poll_target(daemon.targets[0])
        self.assertEqual(coordinator.create_run.call_count, 1)

    @patch("services.ingest.kubernetes_live_signal.collect_kubernetes_signal")
    def test_skips_when_active_run_in_progress(self, mock_collect):
        mock_collect.return_value = _unhealthy_signal()
        coordinator = self._make_coordinator()
        coordinator.get_run.return_value = {"status": "running"}
        daemon = WatchDaemon(
            coordinator=coordinator,
            targets=[WatchTarget("app", "default")],
            interval_seconds=10,
            default_cooldown_seconds=0,
        )
        daemon._dedup[("default", "app")] = type(daemon)._DeduplicationEntry if hasattr(type(daemon), "_DeduplicationEntry") else __import__("services.watch_daemon", fromlist=["_DeduplicationEntry"])._DeduplicationEntry()
        from services.watch_daemon import _DeduplicationEntry
        daemon._dedup[("default", "app")] = _DeduplicationEntry(active_run_id="run_active")
        daemon._poll_target(daemon.targets[0])
        coordinator.create_run.assert_not_called()

    def test_is_actionable_healthy(self):
        self.assertFalse(WatchDaemon._is_actionable(_healthy_signal()))

    def test_is_actionable_unhealthy(self):
        self.assertTrue(WatchDaemon._is_actionable(_unhealthy_signal()))

    def test_extract_error_signature(self):
        sig = WatchDaemon._extract_error_signature(_unhealthy_signal())
        self.assertIn("CrashLoopBackOff", sig)
        self.assertIn("Error", sig)

    def test_extract_error_signature_healthy(self):
        sig = WatchDaemon._extract_error_signature(_healthy_signal())
        self.assertEqual(sig, "healthy")


if __name__ == "__main__":
    unittest.main()
