from __future__ import annotations

import tempfile
import unittest

from services.evaluation.service import EvaluationService
from services.evaluation.sre_judge import MultiModelSreJudge, NativeSreJudge, SreJudgment
from shared.mesh_runtime import Decision, RuntimeConfig, Trigger
from shared.mesh_runtime.state import RuntimeStateStore


class StaticJudge:
    def __init__(self, judgment: SreJudgment) -> None:
        self.judgment = judgment

    def evaluate(self, **kwargs):
        return self.judgment


def _trigger() -> Trigger:
    return Trigger(
        trigger_id="trig_eval_judge",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="2026-04-29T00:00:00Z",
        environment="prod",
        service="search",
        endpoint="deployment/search",
        flag_key="",
        current_rollout_pct=0,
        comparison_window={"baseline": "PT1H", "observed": "PT5M"},
        segment={"customer_tier": "standard"},
        metrics={
            "restart_count_total": 1,
            "baseline_p95_latency_ms": 1,
            "observed_p95_latency_ms": 2,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.02,
            "baseline_timeout_rate": 0.0,
            "observed_timeout_rate": 0.0,
            "sample_size": 10,
        },
        related_context={
            "error_signatures": ["crash_loop"],
            "rollout_status": "degraded",
            "release_id": "rev-1",
            "active_incidents": 0,
            "similar_prior_cases": 0,
        },
    )


def _decision() -> Decision:
    return Decision(
        decision_id="dec_eval_judge",
        trigger_id="trig_eval_judge",
        decision_type="restart_deployment",
        autonomy_tier="autonomous",
        summary="Restart deployment",
        reasoning={
            "primary_hypothesis": "transient crash",
            "evidence": ["crash_loop", "deployment rollout is scoped to one namespace"],
            "evidence_pack": {
                "probe_results": [{"probe_id": "kubectl_describe", "status": "succeeded"}],
                "fast_path_signatures": ["crash_loop"],
            },
            "alternatives_considered": ["escalate"],
        },
        expected_outcome={
            "target_metrics": {"p95_latency_ms": "<= current", "error_rate": "<= current"},
            "time_to_effect": "10m",
        },
        risk={"level": "medium", "blast_radius": "single_deployment", "customer_impact_if_wrong": "brief churn"},
        confidence=0.9,
        execution_plan={
            "system": "kubernetes_service",
            "action": "restart_deployment",
            "parameters": {"deployment_name": "search", "namespace": "default"},
            "rollback_plan": "rollback if restart fails",
        },
    )


class SreJudgeEvaluationTests(unittest.TestCase):
    def test_execute_judgment_preserves_execute_when_no_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = EvaluationService(
                config=RuntimeConfig(state_directory=tmp),
                state_store=RuntimeStateStore(tmp),
                sre_judge=StaticJudge(SreJudgment(recommendation="execute", confidence=0.9, risk_assessment="medium")),
            )

            result = svc.evaluate(_trigger(), _decision())

            self.assertTrue(result.passed)
            self.assertEqual(result.final_recommendation, "execute")
            self.assertEqual(result.stage_results["sre_judgment"]["recommendation"], "execute")

    def test_human_review_judgment_blocks_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = EvaluationService(
                config=RuntimeConfig(state_directory=tmp),
                state_store=RuntimeStateStore(tmp),
                sre_judge=StaticJudge(SreJudgment(recommendation="human_review", confidence=0.8, risk_assessment="medium")),
            )

            result = svc.evaluate(_trigger(), _decision())

            self.assertFalse(result.passed)
            self.assertEqual(result.final_recommendation, "human_review")
            self.assertIn("sre judge recommends human_review", result.blocking_reasons)

    def test_multi_judge_disagreement_routes_review(self) -> None:
        judge = MultiModelSreJudge(
            StaticJudge(SreJudgment(recommendation="execute", confidence=0.9, risk_assessment="low", model="a")),
            StaticJudge(SreJudgment(recommendation="human_review", confidence=0.7, risk_assessment="medium", model="b")),
        )

        judgment = judge.evaluate(trigger=_trigger(), decision=_decision(), stage_results={}, blocking_reasons=[])

        self.assertEqual(judgment.recommendation, "human_review")
        self.assertFalse(judgment.agreement)
        self.assertEqual(len(judgment.raw_judgments), 2)

    def test_native_judge_preserves_hard_review_for_escalate(self) -> None:
        decision = _decision()
        decision.decision_type = "escalate"
        decision.execution_plan = {
            "system": "incident_service",
            "action": "open_incident",
            "parameters": {"service": "search", "severity": "high"},
            "rollback_plan": "close incident if false alarm",
        }
        judgment = NativeSreJudge().evaluate(
            trigger=_trigger(),
            decision=decision,
            stage_results={},
            blocking_reasons=["decision routes to human review"],
        )

        self.assertEqual(judgment.recommendation, "human_review")


if __name__ == "__main__":
    unittest.main()
