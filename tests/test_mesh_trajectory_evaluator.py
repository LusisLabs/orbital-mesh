from __future__ import annotations

import unittest

from services.evaluation.mesh_eval import BehavioralScorer, TrajectoryEvaluator, Verifier
from shared.mesh_runtime import Decision, Trigger, load_fixture


class MeshTrajectoryEvaluatorTests(unittest.TestCase):
    def test_trace_preserves_ordered_events_and_artifacts(self) -> None:
        trigger = Trigger.from_dict(_signal_trigger())
        decision = Decision.from_dict(load_fixture("decisions", "high_risk_decision.json"))
        trace = TrajectoryEvaluator().build_trace(
            trigger=trigger,
            decision=decision,
            run_events=[
                {"sequence": 2, "event_type": "decision_ready", "stage": "decision_ready"},
                {"sequence": 1, "event_type": "evidence_pack_ready", "stage": "evidence_pack_ready"},
            ],
            artifacts={"evidence_pack": {"probe_results": [{"name": "logs"}]}},
        )

        self.assertEqual([event["sequence"] for event in trace["events"]], [1, 2])
        self.assertEqual(trace["context"]["evidence_pack"]["probe_results"][0]["name"], "logs")
        self.assertIsNone(trace["mesh_eval"])

    def test_behavioral_scorer_blocks_missing_evidence(self) -> None:
        decision = Decision.from_dict(load_fixture("decisions", "high_risk_decision.json"))
        trace = TrajectoryEvaluator().build_trace(
            trigger=_signal_trigger(),
            decision=decision,
            run_events=[],
            artifacts={},
        )

        result = BehavioralScorer().score(trace)

        self.assertFalse(result.passed)
        self.assertTrue(any("evidence" in note for note in result.notes))

    def test_verifier_accepts_successful_full_run(self) -> None:
        trace = {
            "evaluation": {"passed": True, "final_recommendation": "execute"},
            "execution": {"status": "succeeded"},
            "feedback": {"outcome": "successful"},
        }

        result = Verifier().verify(trace)

        self.assertTrue(result["passed"])
        self.assertEqual(result["temperature"]["temperature"], 0.0)


def _signal_trigger() -> dict:
    return {
        "trigger_id": "tr_test",
        "trigger_type": "feature_flag_performance_regression",
        "triggered_at": "2026-01-01T00:00:00+00:00",
        "environment": "test",
        "service": "search",
        "endpoint": "/query",
        "flag_key": "search-ranking-v2",
        "current_rollout_pct": 25,
        "comparison_window": {"observed": "5m", "baseline": "1h"},
        "segment": {"customer_tier": "standard", "region": "us-east-1"},
        "metrics": {
            "baseline_p95_latency_ms": 100,
            "observed_p95_latency_ms": 200,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.02,
            "sample_size": 1000,
        },
        "related_context": {"release_id": "rel", "active_incidents": 0, "similar_prior_cases": 0},
    }


if __name__ == "__main__":
    unittest.main()
