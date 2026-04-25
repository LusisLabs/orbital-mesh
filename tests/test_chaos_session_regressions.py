"""Regression tests for three bugs surfaced by the first real chaos session run.

Each test documents the failure it covers. These should not be deleted
without a matching design change — they're each worth more than the
dozen pass/fails they represent because they cover behavior the rest
of the test suite was blind to until a real cluster produced the data.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch


# --------------------------------------------------------- Bug 1: event freshness


class EventFreshnessTests(unittest.TestCase):
    """Kubernetes keeps events for ~1 hour by default. Without a time
    filter in the signal collector, events from the bad_image chaos
    at t=0 contaminate every signal through t=3600 — every subsequent
    trigger shows ``error_signatures=['image_pull_failure']`` even
    after the image was reverted. This regressed the first live
    chaos session into 14 unexpected ``rollback_deployment``
    decisions in a row.
    """

    def _event(self, *, reason: str, minutes_ago: int) -> dict:
        """Build a synthetic Kubernetes event with a timestamp ``minutes_ago``
        minutes before the current wall clock."""
        from datetime import timedelta
        ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
        return {
            "involvedObject": {"name": "search-api-abc", "kind": "Pod"},
            "reason": reason,
            "message": f"fake {reason}",
            "lastTimestamp": ts,
            "type": "Warning",
        }

    def test_stale_event_is_excluded(self) -> None:
        """An event from 30 minutes ago must not appear in the signal."""
        from services.ingest.kubernetes_live_signal import _event_is_fresh, _event_window_cutoff
        cutoff = _event_window_cutoff()
        stale = self._event(reason="ImagePullBackOff", minutes_ago=30)
        self.assertFalse(_event_is_fresh(stale, cutoff))

    def test_fresh_event_is_included(self) -> None:
        from services.ingest.kubernetes_live_signal import _event_is_fresh, _event_window_cutoff
        cutoff = _event_window_cutoff()
        fresh = self._event(reason="BackOff", minutes_ago=1)
        self.assertTrue(_event_is_fresh(fresh, cutoff))

    def test_event_with_only_eventTime_is_handled(self) -> None:
        """Newer Kubernetes events populate ``eventTime`` instead of
        ``lastTimestamp``. Both must work."""
        from datetime import timedelta
        from services.ingest.kubernetes_live_signal import _event_is_fresh, _event_window_cutoff
        cutoff = _event_window_cutoff()
        fresh_ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        event = {"eventTime": fresh_ts, "reason": "BackOff"}
        self.assertTrue(_event_is_fresh(event, cutoff))

    def test_event_with_no_timestamps_is_excluded(self) -> None:
        """Missing-timestamp events drop out. Better than classifying
        every undated payload as fresh."""
        from services.ingest.kubernetes_live_signal import _event_is_fresh, _event_window_cutoff
        cutoff = _event_window_cutoff()
        self.assertFalse(_event_is_fresh({"reason": "BackOff"}, cutoff))

    def test_event_window_respects_env_override(self) -> None:
        """Operators running long investigations can widen the window."""
        from services.ingest.kubernetes_live_signal import _event_window_cutoff
        from datetime import timedelta
        default = datetime.now(timezone.utc) - timedelta(seconds=300)
        # 60s window should produce a cutoff closer to now than the default.
        with patch.dict("os.environ", {"MESH_K8S_EVENT_WINDOW_SECONDS": "60"}):
            override = _event_window_cutoff()
        self.assertGreater(override, default)


# --------------------------------------------------------- Bug 2: trigger over-sensitivity


class TriggerFailingPodsTests(unittest.TestCase):
    """The original ``failing_pods = [... if not ready or restarts > 0]``
    fired on any pod in startup (ready=False but perfectly healthy).
    ``pod_kill_one`` in the chaos portfolio is supposed to test that
    Mesh does NOT fire on transient churn — every pod_kill_one signal
    flagged a trigger under the old logic."""

    def _envelope(
        self,
        pods: list[dict],
        *,
        rollout_status: str = "healthy",
        error_signatures: list[str] | None = None,
    ) -> object:
        """Build a minimal k8s signal envelope with the given pod list.

        ``rollout_status`` and ``error_signatures`` are explicit because
        the trigger's firing logic depends on both the deployment-level
        status and the aggregated signatures. A test that wants to
        exercise the "degraded rollout + no hard signatures" path (the
        motivating case for the new trigger tightening) sets
        rollout_status="degraded" and leaves signatures empty.
        """
        from shared.mesh_runtime import EventEnvelope
        return EventEnvelope(
            event_type="normalized_signal",
            object_id="sig_test",
            schema_version="v1",
            emitted_at="2026-04-23T10:00:00Z",
            payload={
                "signal_type": "kubernetes_deployment_issue",
                "environment": "e2e",
                "service": "search-api",
                "endpoint": "deployment/search-api",
                "cluster": "kind-mesh-e2e",
                "namespace": "mesh-e2e",
                "comparison_window": {"baseline": "revision:1-1", "observed": "revision:1"},
                "segment": {"customer_tier": "system", "region": "kind-mesh-e2e"},
                "deployment": {
                    "name": "search-api",
                    "revision": "1",
                    "image": "nginx:1.25-alpine",
                    "rollout_started_at": "2026-04-23T09:59:00Z",
                    "rollout_status": rollout_status,
                    "desired_replicas": 2,
                    "available_replicas": 2,
                    "updated_replicas": 2,
                },
                "pods": pods,
                "events": [],
                "logs": [],
                "log_summary": {
                    "primary_symptom": (error_signatures or ["unknown"])[0] if error_signatures else "unknown",
                    "error_signatures": list(error_signatures or []),
                    "categories": [],
                    "likely_layer": "unknown",
                    "sample_lines": [],
                    "event_reasons": [],
                    "restart_count_total": 0,
                },
                "related_context": {},
                "post_action_observations": {},
            },
            summary={"service": "search-api", "endpoint": "deployment/search-api", "deployment": "search-api"},
        )

    def test_pod_in_startup_not_ready_does_not_fire(self) -> None:
        """Simulate pod_kill_one aftermath: one pod back to Running+ready,
        one still starting. Old logic fired; new logic does not."""
        from services.trigger.service import TriggerService
        envelope = self._envelope([
            {"name": "p1", "ready": True, "restarts": 0, "container_status": "Running",
             "phase": "Running", "last_state_reason": None},
            {"name": "p2", "ready": False, "restarts": 0, "container_status": "ContainerCreating",
             "phase": "Pending", "last_state_reason": None},
        ])
        trigger = TriggerService().detect(envelope)
        self.assertIsNone(trigger, "transient startup should not fire a trigger")

    def test_pod_in_crash_loop_still_fires(self) -> None:
        """Make sure we didn't over-tighten — actual failures must still trigger."""
        from services.trigger.service import TriggerService
        envelope = self._envelope([
            {"name": "p1", "ready": False, "restarts": 3, "container_status": "CrashLoopBackOff",
             "phase": "Running", "last_state_reason": "Error"},
        ])
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)

    def test_pod_with_image_pull_backoff_still_fires(self) -> None:
        from services.trigger.service import TriggerService
        envelope = self._envelope([
            {"name": "p1", "ready": False, "restarts": 0, "container_status": "ImagePullBackOff",
             "phase": "Pending", "last_state_reason": None},
        ])
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)

    def test_oom_killed_pod_still_fires(self) -> None:
        from services.trigger.service import TriggerService
        envelope = self._envelope([
            {"name": "p1", "ready": True, "restarts": 1, "container_status": "Running",
             "phase": "Running", "last_state_reason": "OOMKilled"},
        ])
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger, "restarts > 0 is enough on its own")

    def test_degraded_rollout_without_hard_signature_does_not_fire(self) -> None:
        """Second-generation fix for pod_kill_one: during a pod recreate,
        rollout_status briefly reads 'degraded' even though nothing is
        truly broken. With no corroborating hard signature, this must
        not fire. Before the fix, the bare rollout_unhealthy path
        produced a trigger that Mesh then decided on — every
        pod_kill_one in the live session flunked."""
        from services.trigger.service import TriggerService
        envelope = self._envelope(
            [
                {"name": "p1", "ready": True, "restarts": 0, "container_status": "Running",
                 "phase": "Running", "last_state_reason": None},
                {"name": "p2", "ready": False, "restarts": 0, "container_status": "ContainerCreating",
                 "phase": "Pending", "last_state_reason": None},
            ],
            rollout_status="degraded",
            error_signatures=[],
        )
        trigger = TriggerService().detect(envelope)
        self.assertIsNone(trigger, "transient degraded rollout should not fire without hard signature")

    def test_degraded_rollout_with_probe_failure_alone_does_not_fire(self) -> None:
        """``probe_failure`` is deliberately excluded from hard signatures.
        The workload's readiness probe fires 'Readiness probe failed'
        events during normal startup that the summarizer stamps as
        probe_failure. Treating that as a hard signature would reopen
        the pod_kill_one false-positive loophole."""
        from services.trigger.service import TriggerService
        envelope = self._envelope(
            [
                {"name": "p1", "ready": True, "restarts": 0, "container_status": "Running",
                 "phase": "Running", "last_state_reason": None},
                {"name": "p2", "ready": False, "restarts": 0, "container_status": "ContainerCreating",
                 "phase": "Pending", "last_state_reason": None},
            ],
            rollout_status="degraded",
            error_signatures=["probe_failure"],
        )
        trigger = TriggerService().detect(envelope)
        self.assertIsNone(trigger)

    def test_degraded_rollout_with_crash_loop_fires(self) -> None:
        """Hard signature corroborates the degraded rollout — trigger fires."""
        from services.trigger.service import TriggerService
        envelope = self._envelope(
            [
                {"name": "p1", "ready": True, "restarts": 0, "container_status": "Running",
                 "phase": "Running", "last_state_reason": None},
                {"name": "p2", "ready": False, "restarts": 0, "container_status": "ContainerCreating",
                 "phase": "Pending", "last_state_reason": None},
            ],
            rollout_status="degraded",
            error_signatures=["crash_loop"],
        )
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)

    def test_failed_rollout_fires_even_without_hard_signature(self) -> None:
        """``rollout_status=failed`` is definitive — the deployment
        controller has given up. Fire alone."""
        from services.trigger.service import TriggerService
        envelope = self._envelope(
            [],  # no pods needed; rollout_failed alone is enough
            rollout_status="failed",
            error_signatures=[],
        )
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)


# --------------------------------------------------------- Bug 3: decision capture on recovery timeout


class ScenarioRecoveryCaptureTests(unittest.TestCase):
    """Before the fix, a scenario that captured Mesh's decision but
    then timed out waiting for the cluster to recover showed up in
    the report with ``decision=None``. Operators couldn't tell the
    difference between 'Mesh never responded' and 'Mesh decided but
    cluster didn't self-heal'. The fix: stamp captured fields
    incrementally so a late failure can't erase them."""

    def test_scenario_returns_captured_fields_even_on_recovery_timeout(self) -> None:
        """Mock the Harness so injection + pipeline succeed but
        wait_for_deployment_ready raises. Verify the returned dict
        still has the decision."""
        from tests.e2e.chaos.portfolio import (
            ChaosExperiment,
            SEVERITY_HIGH,
        )
        from tests.e2e.continuous.session import _make_scenario_fn

        experiment = ChaosExperiment(
            name="crash_loop",
            description="",
            weight=1.0,
            severity=SEVERITY_HIGH,
            expected_decisions=frozenset({"restart_deployment"}),
            cooldown_seconds=30,
        )

        # Fake harness that simulates a successful pipeline but a
        # failing recovery wait. Must implement the methods the
        # scenario function calls.
        class FakeHarness:
            namespace = "mesh-e2e"
            def __init__(self):
                self.steps: list[tuple[str, dict]] = []
                self.injector = FakeInjector()

            def snapshot_cluster(self, target, label=None):
                return {"label": label, "pods": [], "deployment_status": {}}

            def inject(self, primitive, target):
                pass

            def run_mesh_pipeline(self, target):
                return {
                    "normalized_event": {"object_id": "sig_test"},
                    "trigger": {"trigger_type": "kubernetes_deployment_unhealthy"},
                    "decision": {"decision_type": "restart_deployment"},
                    "evaluation": {"final_recommendation": "execute"},
                    "execution": {"status": "succeeded"},
                    "feedback": {"outcome": "successful"},
                }

            def wait_for_deployment_ready(self, target, timeout_seconds=120):
                raise AssertionError("simulated recovery timeout")

            def record_step(self, name, status="completed", **payload):
                self.steps.append((name, payload))

        class FakeInjector:
            def revert(self, deployment, namespace):
                pass

        scenario_fn = _make_scenario_fn(experiment, target="search-api")
        harness = FakeHarness()
        result = scenario_fn(harness)

        # Decision must still be populated despite the recovery timeout.
        self.assertIsNotNone(result.get("decision"))
        self.assertEqual(result["decision"]["decision_type"], "restart_deployment")
        # The timeout must be recorded as a step so the report surfaces it.
        step_names = [name for name, _ in harness.steps]
        self.assertIn("recovery:timed_out", step_names)


if __name__ == "__main__":
    unittest.main()
