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


# --------------------------------------------------------- Bug 8: symmetric revert


class ProbeHandlerRevertTests(unittest.TestCase):
    """readiness_failure injects a ``tcpSocket`` probe handler
    alongside the baseline's ``httpGet``. The injection nulls out
    ``httpGet`` so the result is valid. But the revert, until this
    fix, applied the baseline template without nulling out
    ``tcpSocket`` — strategic merge kept both, and k8s rejected the
    patch with "may not specify more than 1 handler type". The
    cluster then stayed in the bad state for the rest of the
    session. The fix normalizes the revert so all non-baseline
    handler types are explicitly nulled."""

    def test_revert_nulls_out_non_baseline_probe_handlers(self) -> None:
        from tests.e2e.chaos.injector import _normalize_probe_handlers_for_revert
        template = {
            "spec": {
                "containers": [
                    {
                        "name": "c",
                        "readinessProbe": {
                            "httpGet": {"path": "/", "port": 80},
                            "initialDelaySeconds": 1,
                        },
                    }
                ]
            }
        }
        normalized = _normalize_probe_handlers_for_revert(template)
        probe = normalized["spec"]["containers"][0]["readinessProbe"]
        self.assertEqual(probe["httpGet"], {"path": "/", "port": 80})
        # The three non-baseline handlers are explicitly nulled so
        # strategic-merge deletes whatever is in the current state.
        self.assertIsNone(probe["tcpSocket"])
        self.assertIsNone(probe["exec"])
        self.assertIsNone(probe["grpc"])
        # Non-handler probe fields are preserved.
        self.assertEqual(probe["initialDelaySeconds"], 1)

    def test_revert_is_noop_when_no_probes_present(self) -> None:
        """A deployment with no probes should pass through untouched."""
        from tests.e2e.chaos.injector import _normalize_probe_handlers_for_revert
        template = {"spec": {"containers": [{"name": "c", "image": "nginx"}]}}
        normalized = _normalize_probe_handlers_for_revert(template)
        self.assertEqual(normalized, template)


class ReadinessFailureObservationTests(unittest.TestCase):
    def test_readiness_failure_accepts_degraded_updated_rollout(self) -> None:
        """The compose stack uses rolling Deployments.

        Old pods may stay ready while the bad new ReplicaSet is blocked
        by the injected readiness probe, so the harness must key on
        unavailable updated replicas rather than requiring total
        readyReplicas to hit zero.
        """
        from tests.e2e.chaos.injector import ChaosInjector

        injector = ChaosInjector()
        injector._kubectl_json = lambda *args: {  # type: ignore[method-assign]
            "status": {
                "readyReplicas": 3,
                "updatedReplicas": 1,
                "unavailableReplicas": 1,
            }
        }

        observed_at = injector._wait_for_readiness_degraded("semantic-search", "search", timeout_seconds=1)
        self.assertIsInstance(observed_at, float)

    def test_scale_to_zero_still_waits_for_zero_ready(self) -> None:
        from tests.e2e.chaos.injector import ChaosInjector

        injector = ChaosInjector()
        injector._kubectl_json = lambda *args: {  # type: ignore[method-assign]
            "spec": {"replicas": 0},
            "status": {"readyReplicas": 0},
        }

        observed_at = injector._wait_for_zero_ready("semantic-search", "search", timeout_seconds=1)
        self.assertIsInstance(observed_at, float)

    def test_pod_kill_all_waits_for_transient_zero_ready_not_zero_desired(self) -> None:
        from tests.e2e.chaos.injector import ChaosInjector

        injector = ChaosInjector()
        injector._kubectl_json = lambda *args: {  # type: ignore[method-assign]
            "spec": {"replicas": 3},
            "status": {"readyReplicas": 0},
        }

        observed_at = injector._wait_for_ready_replicas_below(
            "semantic-search",
            "search",
            ready_replicas=1,
            timeout_seconds=1,
        )
        self.assertIsInstance(observed_at, float)

    def test_pod_reason_accepts_last_terminated_oom_reason(self) -> None:
        from tests.e2e.chaos.injector import ChaosInjector

        injector = ChaosInjector()
        injector._list_pods = lambda *args: [  # type: ignore[method-assign]
            {
                "containerStatuses": [
                    {
                        "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                        "lastState": {"terminated": {"reason": "OOMKilled"}},
                    }
                ]
            }
        ]

        observed_at = injector._wait_for_pod_reason(
            "semantic-search",
            "search",
            reasons=("OOMKilled",),
            timeout_seconds=1,
        )
        self.assertIsInstance(observed_at, float)


# --------------------------------------------------------- Bug 10: baseline-failure fast-trip


class CircuitBreakerBaselineTests(unittest.TestCase):
    """Before this fix, the breaker only tripped on 2 consecutive
    failures. A single baseline-deployment failure should halt
    immediately because the baseline being broken means every
    subsequent experiment runs against corrupted state — the session
    would keep producing meaningless data until the second probe
    finally caught up."""

    def test_first_baseline_failure_halts_immediately(self) -> None:
        from tests.e2e.chaos.steady_state import CircuitBreaker, ProbeResult
        breaker = CircuitBreaker(max_consecutive_failures=2)
        probe = ProbeResult(
            taken_at=0.0,
            label="after_5",
            cluster_reachable=True,
            baseline_ready=False,
            mesh_pipeline_ok=True,
            mesh_pipeline_latency_seconds=0.1,
            notes=["baseline[search-api]: 2/3 ready"],
        )
        breaker.record_result(probe)
        self.assertTrue(breaker.should_halt())
        self.assertIn("baseline deployment is unhealthy", breaker.halt_reason() or "")

    def test_generic_failure_still_requires_two_in_a_row(self) -> None:
        """Non-baseline failures (kubectl hiccup, cluster momentarily
        unreachable) still need the two-in-a-row threshold to avoid
        halting on transients."""
        from tests.e2e.chaos.steady_state import CircuitBreaker, ProbeResult
        breaker = CircuitBreaker(max_consecutive_failures=2)
        probe = ProbeResult(
            taken_at=0.0,
            label="after_5",
            cluster_reachable=False,  # not baseline-specific
            baseline_ready=True,
            mesh_pipeline_ok=True,
            mesh_pipeline_latency_seconds=0.1,
            notes=["cluster: kubectl timed out"],
        )
        breaker.record_result(probe)
        self.assertFalse(breaker.should_halt())


# --------------------------------------------------------- Bug 9: stabilization helper


class StableStateHelperTests(unittest.TestCase):
    """Unit tests for the pure-logic piece of ``wait_for_stable_state``.
    The kubectl-polling part can't be unit-tested without a live
    cluster, but the ``_is_stable`` check that decides whether a
    single poll is stable is pure logic and worth pinning down."""

    def _deployment(self, *, desired=2, ready=2, available=2, updated=2) -> dict:
        return {
            "spec": {"replicas": desired},
            "status": {
                "readyReplicas": ready,
                "availableReplicas": available,
                "updatedReplicas": updated,
            },
        }

    def _pod(self, *, phase="Running", container_state="running",
             deletion=None) -> dict:
        pod = {
            "metadata": {"name": "p1"},
            "status": {
                "phase": phase,
                "containerStatuses": [{"state": {container_state: {}}}],
            },
        }
        if deletion is not None:
            pod["metadata"]["deletionTimestamp"] = deletion
        return pod

    def test_stable_when_replica_counts_match_and_pods_running(self) -> None:
        from tests.e2e.harness import Harness
        deployment = self._deployment()
        pods = {"items": [self._pod(), self._pod()]}
        self.assertTrue(Harness._is_stable(deployment, pods))

    def test_unstable_when_ready_lags_desired(self) -> None:
        from tests.e2e.harness import Harness
        deployment = self._deployment(ready=1)
        pods = {"items": [self._pod(), self._pod()]}
        self.assertFalse(Harness._is_stable(deployment, pods))

    def test_unstable_when_pod_pending(self) -> None:
        from tests.e2e.harness import Harness
        deployment = self._deployment()
        pods = {"items": [self._pod(phase="Pending")]}
        self.assertFalse(Harness._is_stable(deployment, pods))

    def test_unstable_when_pod_terminating(self) -> None:
        """A pod with deletionTimestamp is still being torn down —
        its events remain active in kubectl's event log, which means
        the next experiment would see them. Not stable."""
        from tests.e2e.harness import Harness
        deployment = self._deployment()
        pods = {"items": [self._pod(deletion="2026-01-01T00:00:00Z")]}
        self.assertFalse(Harness._is_stable(deployment, pods))

    def test_unstable_when_container_waiting(self) -> None:
        from tests.e2e.harness import Harness
        deployment = self._deployment()
        pods = {"items": [self._pod(container_state="waiting")]}
        self.assertFalse(Harness._is_stable(deployment, pods))


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
