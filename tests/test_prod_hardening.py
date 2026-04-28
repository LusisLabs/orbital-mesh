from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from services.observer import MultiLlmObserver, ObserverVerdict
from services.observer.redaction import redact_for_observer
from services.orchestrator.adapters_common import CliExecutionResult
from services.orchestrator.goose_adapter import NativeGooseAdapter
from services.orchestrator.service import OrchestratorService
from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig
from shared.mesh_runtime.deferred_runs import DeferredRunStore


def _decision() -> Decision:
    return Decision(
        decision_id="dec_test",
        trigger_id="trig_test",
        decision_type="restart_systemd_service",
        autonomy_tier="approval_required",
        summary="Restart service",
        reasoning={
            "primary_hypothesis": "service wedged",
            "evidence": ["peer_count=0"],
            "alternatives_considered": ["escalate"],
        },
        expected_outcome={
            "target_metrics": {"p95_latency_ms": "<= current", "error_rate": "<= current"},
            "time_to_effect": "5m",
        },
        risk={"level": "medium", "blast_radius": "single_reth_node", "customer_impact_if_wrong": "brief outage"},
        confidence=0.8,
        execution_plan={
            "system": "systemd_service",
            "action": "restart_systemd_service",
            "parameters": {"host": "reth-1", "service": "reth.service"},
            "rollback_plan": "escalate if restart fails",
        },
    )


def _evaluation() -> EvaluationResult:
    return EvaluationResult(
        evaluation_id="eval_dec_test",
        decision_id="dec_test",
        passed=True,
        final_recommendation="execute",
        stage_results={},
        blocking_reasons=[],
    )


class _RetryingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute_decision(self, decision, idempotency_key):
        self.calls += 1
        return CliExecutionResult(
            status="failed",
            external_refs={},
            failure={"reason": "network_blip"},
            retryable=True,
        )

    def open_execution_incident(self, decision, failure_reason):
        return {"incident_id": "inc_test"}


class IdempotentSystemdTests(unittest.TestCase):
    def test_dispatched_without_outcome_blocks_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = OrchestratorService(
                adapter=_RetryingAdapter(),
                config=RuntimeConfig(state_directory=tmp, max_transient_retries=1),
                sleeper=lambda _: None,
            )
            key = "dec_test:restart_systemd_service"
            svc.attempt_store.begin(key, "dec_test", _decision().execution_plan)
            svc.attempt_store.mark_dispatched(key)

            execution = svc.execute(_decision(), _evaluation())

            self.assertEqual(execution.status, "failed")
            self.assertEqual(execution.failure["reason"], "outcome_unknown_after_dispatch")
            self.assertEqual(svc.adapter.calls, 0)

    def test_retryable_systemd_failure_does_not_double_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = _RetryingAdapter()
            svc = OrchestratorService(
                adapter=adapter,
                config=RuntimeConfig(state_directory=tmp, max_transient_retries=2),
                sleeper=lambda _: None,
            )

            execution = svc.execute(_decision(), _evaluation())

            self.assertEqual(execution.status, "failed")
            self.assertEqual(adapter.calls, 1)


class DeferredRunStoreTests(unittest.TestCase):
    def test_claim_due_marks_record_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DeferredRunStore(tmp)
            due_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
            record = store.create(
                source_run_id="run_parent",
                due_at=due_at,
                signal_payload={"signal_type": "kubernetes_deployment_issue"},
                parameters={"condition": "probe_failure persists"},
            )

            claimed = store.claim_due()
            claimed_again = store.claim_due()

            self.assertEqual([item["defer_id"] for item in claimed], [record["defer_id"]])
            self.assertEqual(claimed_again, [])


class LoadBalancerRestartTests(unittest.TestCase):
    def test_restart_wraps_drain_and_restore(self) -> None:
        adapter = NativeGooseAdapter(config=RuntimeConfig(ssh_allowed_hosts=("reth-1",), ssh_allowed_services=("reth.service",)))
        adapter.systemd_ssh.restart_service = lambda params: {
            "status": "succeeded",
            "external_refs": {"systemd": "restarted"},
        }
        params = {
            "host": "reth-1",
            "service": "reth.service",
            "lb_target_id": "target-1",
            "lb_pool": "rpc",
        }

        result = adapter._restart_systemd_with_preflight(params)

        self.assertEqual(result["status"], "succeeded")
        self.assertIn("lb_drain", result["external_refs"])
        self.assertIn("lb_restore", result["external_refs"])

    def test_fleet_capacity_blocks_restart(self) -> None:
        adapter = NativeGooseAdapter(config=RuntimeConfig())
        result = adapter._restart_systemd_with_preflight(
            {"fleet_id": "rpc-a", "fleet_min_healthy": 3, "fleet_healthy_count": 2}
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "fleet_capacity_below_threshold")


class _StaticObserver:
    def __init__(self, verdict: ObserverVerdict) -> None:
        self.verdict = verdict

    def is_active(self) -> bool:
        return True

    def review(self, **kwargs):
        return self.verdict


class MultiObserverTests(unittest.TestCase):
    def test_disagreement_chooses_more_conservative_verdict(self) -> None:
        primary = _StaticObserver(ObserverVerdict(verdict="approve", reason="ok", confidence=0.8, model="a"))
        secondary = _StaticObserver(ObserverVerdict(verdict="reject_unsafe", reason="unsafe", confidence=0.9, model="b"))
        observer = MultiLlmObserver(primary, secondary)

        verdict = observer.review(trigger={}, evidence_pack={}, ranked_hypotheses=[], deterministic_decision={})

        self.assertEqual(verdict.verdict, "reject_unsafe")
        self.assertIn("observer_agreement=False", verdict.reason)


class RedactionTests(unittest.TestCase):
    def test_redacts_nested_secrets(self) -> None:
        payload = {
            "rpc_url": "http://example",
            "jwt_secret_path": "/secrets/jwt.hex",
            "headers": {"Authorization": "Bearer abc123"},
            "api_key": "sk-test",
        }

        redacted = redact_for_observer(payload)

        self.assertEqual(redacted["jwt_secret_path"], "<redacted>")
        self.assertEqual(redacted["headers"]["Authorization"], "<redacted>")
        self.assertEqual(redacted["api_key"], "<redacted>")


if __name__ == "__main__":
    unittest.main()
