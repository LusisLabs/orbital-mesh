from __future__ import annotations

import tempfile
import unittest

from services.evaluation.service import EvaluationService
from shared.mesh_runtime import Decision, RuntimeConfig, Trigger
from shared.mesh_runtime.autonomy_policy import evaluate_autonomy_policy


class AutonomyPolicyTests(unittest.TestCase):
    def test_fully_autonomous_live_kubernetes_rollback_requires_certified_scope(self) -> None:
        verdict = evaluate_autonomy_policy(
            _decision(system="kubernetes_service", action="rollback_deployment", decision_type="rollback_deployment"),
            target_profile="pilot",
            live_execution_enabled=True,
        )

        self.assertTrue(verdict.allowed)
        self.assertTrue(verdict.live_execution_allowed)
        self.assertEqual(verdict.connector_id, "kubernetes")
        self.assertEqual(verdict.requested_scope, "rollback")

    def test_approval_required_blocks_until_operator_approval_is_observed(self) -> None:
        decision = _decision(
            system="kubernetes_service",
            action="rollback_deployment",
            decision_type="rollback_deployment",
            autonomy_tier="approval_required",
        )

        blocked = evaluate_autonomy_policy(decision, live_execution_enabled=True)
        approved = evaluate_autonomy_policy(decision, live_execution_enabled=True, approval_observed=True)

        self.assertFalse(blocked.allowed)
        self.assertIn("approval_required_before_execution", blocked.blockers)
        self.assertTrue(approved.allowed)

    def test_advisory_only_rejects_mutating_scope(self) -> None:
        verdict = evaluate_autonomy_policy(
            _decision(system="kubernetes_service", action="rollback_deployment", decision_type="rollback_deployment"),
            policy_tier="advisory_only",
            live_execution_enabled=True,
        )

        self.assertFalse(verdict.allowed)
        self.assertIn("advisory_only_scope_cannot_mutate", verdict.blockers)

    def test_denied_always_blocks_even_advisory_scope(self) -> None:
        verdict = evaluate_autonomy_policy(
            _decision(system="repo_patch_service", action="investigate_and_patch", decision_type="investigate_and_patch"),
            policy_tier="denied_always",
        )

        self.assertFalse(verdict.allowed)
        self.assertIn("autonomy_tier_denied_always", verdict.blockers)

    def test_uncertified_live_feature_flag_write_fails_closed(self) -> None:
        verdict = evaluate_autonomy_policy(
            _decision(system="feature_flag_service", action="set_rollout", decision_type="disable_flag"),
            live_execution_enabled=True,
        )

        self.assertFalse(verdict.allowed)
        self.assertIn("scope_not_allowed_by_connector_certification", verdict.blockers)

    def test_local_mock_execution_reports_live_blockers_without_blocking_fixture(self) -> None:
        verdict = evaluate_autonomy_policy(
            _decision(system="feature_flag_service", action="set_rollout", decision_type="disable_flag"),
            live_execution_enabled=False,
        )

        self.assertTrue(verdict.allowed)
        self.assertFalse(verdict.live_execution_allowed)
        self.assertTrue(verdict.mock_execution_only)
        self.assertIn("live_execution_disabled", verdict.live_blockers)
        self.assertIn("scope_not_allowed_by_connector_certification", verdict.live_blockers)

    def test_evaluation_force_approval_gate_blocks_autonomous_live_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = EvaluationService(
                config=RuntimeConfig(
                    state_directory=tmp,
                    readiness_profile="pilot",
                    kubernetes_live_execution_enabled=True,
                    force_approval_gate=True,
                )
            )

            result = service.evaluate(_trigger(), _decision())

            self.assertFalse(result.passed)
            self.assertIn("approval_required_before_execution", result.blocking_reasons)
            self.assertIn("autonomy_policy", result.stage_results)
            self.assertFalse(result.stage_results["autonomy_policy"]["allowed"])


def _trigger() -> Trigger:
    return Trigger(
        trigger_id="trig_autonomy_policy",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="2026-05-08T00:00:00Z",
        environment="production",
        service="search",
        endpoint="deployment/search",
        flag_key="",
        current_rollout_pct=0,
        comparison_window={"start": "2026-05-08T00:00:00Z", "end": "2026-05-08T00:05:00Z"},
        segment={"customer_tier": "standard"},
        metrics={
            "baseline_p95_latency_ms": 100,
            "observed_p95_latency_ms": 120,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.02,
        },
        related_context={
            "cluster_access_available": True,
            "post_action_observations": {"10m": {"healthy": True}},
        },
    )


def _decision(
    *,
    system: str = "kubernetes_service",
    action: str = "rollback_deployment",
    decision_type: str = "rollback_deployment",
    autonomy_tier: str = "autonomous",
) -> Decision:
    return Decision(
        decision_id=f"dec_{decision_type}_{action}",
        trigger_id="trig_autonomy_policy",
        summary=f"{decision_type} policy decision",
        decision_type=decision_type,
        autonomy_tier=autonomy_tier,
        reasoning={
            "primary_hypothesis": "scoped rollout regression",
            "evidence": ["deployment unhealthy", "single namespace affected"],
            "alternatives_considered": ["escalate"],
            "source_event_ids": ["evt_autonomy_policy"],
            "evidence_pack": {"artifact_ref": "evidence://autonomy-policy"},
        },
        expected_outcome={
            "target_metrics": {"p95_latency_ms": "<= current", "error_rate": "<= current"},
            "time_to_effect": "10m",
        },
        risk={"level": "medium", "blast_radius": "single_deployment", "customer_impact_if_wrong": "brief churn"},
        confidence=0.91,
        execution_plan={
            "system": system,
            "action": action,
            "parameters": {"deployment_name": "search", "namespace": "default"},
            "rollback_plan": "restore previous deployment state",
        },
    )


if __name__ == "__main__":
    unittest.main()
