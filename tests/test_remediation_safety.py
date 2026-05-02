from __future__ import annotations

import tempfile
import unittest

from services.evaluation.service import EvaluationService
from shared.mesh_runtime import Decision, RuntimeConfig, RuntimeStateStore, Trigger
from shared.mesh_runtime.remediation_safety import evaluate_remediation_safety


class RemediationSafetyTests(unittest.TestCase):
    def test_safe_audit_action_passes_with_high_score(self) -> None:
        case = evaluate_remediation_safety(
            _trigger(),
            _decision(
                decision_type="no_action",
                action="record_no_action",
                system="audit_log_sink",
                confidence=0.8,
                risk_level="low",
                rollback_plan="audit-only action has no rollback",
            ),
            state_store=None,
        )

        self.assertTrue(case.passed)
        self.assertEqual(case.verdict, "pass")
        self.assertGreaterEqual(case.score, case.threshold)

    def test_severe_signature_hard_stops_non_escalation(self) -> None:
        trigger = _trigger(error_signatures=["disk_pressure"])
        decision = _decision(
            decision_type="restart_systemd_service",
            action="restart_systemd_service",
            system="systemd_service",
            confidence=0.9,
            risk_level="medium",
            rollback_plan="restart only once; escalate if recovery probe fails",
            evidence_pack={"error_signatures": ["disk_pressure"]},
        )

        case = evaluate_remediation_safety(trigger, decision)

        self.assertFalse(case.passed)
        self.assertEqual(case.verdict, "human_review")
        self.assertIn("severe signature requires escalation", case.hard_stops)

    def test_weak_mutating_action_needs_more_evidence(self) -> None:
        trigger = _trigger(metrics={}, related_context={})
        decision = _decision(
            decision_type="reduce_rollout",
            action="set_rollout",
            system="feature_flag_service",
            confidence=0.62,
            risk_level="medium",
            rollback_plan="restore prior rollout",
            evidence=[],
            evidence_pack={},
        )

        case = evaluate_remediation_safety(trigger, decision)

        self.assertFalse(case.passed)
        self.assertIn(case.verdict, {"needs_more_evidence", "human_review"})
        self.assertLess(case.components["evidence"], 0.55)

    def test_evaluation_records_safety_case_and_blocks_unsafe_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfig(
                evaluation_mode="native",
                state_directory=tmp,
                ssh_allowed_hosts=("reth-host",),
                ssh_allowed_services=("reth.service",),
            )
            trigger = _trigger(error_signatures=["disk_pressure"])
            decision = _decision(
                decision_type="restart_systemd_service",
                action="restart_systemd_service",
                system="systemd_service",
                parameters={"host": "reth-host", "service": "reth.service"},
                confidence=0.92,
                risk_level="medium",
                rollback_plan="restart only once; escalate if recovery probe fails",
                evidence_pack={"error_signatures": ["disk_pressure"]},
            )

            result = EvaluationService(config=config, state_store=RuntimeStateStore(tmp)).evaluate(trigger, decision)

            self.assertFalse(result.passed)
            self.assertEqual(result.final_recommendation, "human_review")
            self.assertIn("remediation_safety", result.stage_results)
            self.assertIn("remediation safety case has hard stops", result.blocking_reasons)
            self.assertIn(
                "severe signature requires escalation",
                result.stage_results["remediation_safety"]["hard_stops"],
            )


def _trigger(
    *,
    error_signatures: list[str] | None = None,
    metrics: dict | None = None,
    related_context: dict | None = None,
) -> Trigger:
    context = {
        "error_signatures": error_signatures or [],
        "post_action_observations": {"10m": {"healthy": True}},
    }
    if related_context is not None:
        context = related_context
    return Trigger(
        trigger_id="trig_safety",
        trigger_type="reth_node_degraded",
        triggered_at="2026-04-27T00:00:00Z",
        service="el-1-reth-lighthouse",
        endpoint="reth.rpc",
        environment="production",
        flag_key="",
        current_rollout_pct=0,
        comparison_window={"start": "2026-04-27T00:00:00Z", "end": "2026-04-27T00:05:00Z"},
        segment={"customer_tier": "standard"},
        metrics=metrics
        if metrics is not None
        else {
            "peer_count": 0,
            "block_lag": 0,
            "baseline_p95_latency_ms": 100,
            "observed_p95_latency_ms": 120,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.02,
        },
        related_context=context,
    )


def _decision(
    *,
    decision_type: str,
    action: str,
    system: str,
    confidence: float,
    risk_level: str,
    rollback_plan: str,
    parameters: dict | None = None,
    evidence: list[str] | None = None,
    evidence_pack: dict | None = None,
) -> Decision:
    return Decision(
        decision_id=f"dec_{decision_type}",
        trigger_id="trig_safety",
        summary=f"{decision_type} test decision",
        decision_type=decision_type,
        autonomy_tier="autonomous",
        reasoning={
            "evidence": evidence if evidence is not None else ["peer_count=0", "rpc reachable"],
            "evidence_pack": evidence_pack
            if evidence_pack is not None
            else {
                "execution": {"peer_count": 0},
                "consensus": {"engine_api_reachable": True},
                "storage": {"disk_used_pct": 30},
                "rpc": {"http_reachable": True},
                "node": {"name": "el-1-reth-lighthouse"},
            },
            "source_event_ids": ["evt_1"],
        },
        expected_outcome={"target_metrics": {"peer_count": ">= 1"}},
        risk={"level": risk_level, "blast_radius": "single_reth_node"},
        confidence=confidence,
        execution_plan={
            "system": system,
            "action": action,
            "parameters": parameters or {},
            "rollback_plan": rollback_plan,
        },
    )


if __name__ == "__main__":
    unittest.main()
