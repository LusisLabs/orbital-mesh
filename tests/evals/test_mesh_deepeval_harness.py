from __future__ import annotations

import importlib.util
import unittest

from services.evaluation.mesh_eval import BehavioralScorer, TrajectoryEvaluator
from shared.mesh_runtime import Decision, Trigger, load_fixture


DEEPEVAL_AVAILABLE = importlib.util.find_spec("deepeval") is not None


class MeshDeepEvalHarnessTests(unittest.TestCase):
    def test_code_defined_eval_runs_without_external_judge(self) -> None:
        trigger = Trigger.from_dict(
            {
                "trigger_id": "tr_eval",
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
                "related_context": {
                    "release_id": "rel",
                    "active_incidents": 0,
                    "similar_prior_cases": 0,
                    "webhook_alert_id": "a",
                    "webhook_source_id": "s",
                },
            }
        )
        decision = Decision.from_dict(load_fixture("decisions", "high_risk_decision.json"))
        trace = TrajectoryEvaluator().build_trace(
            trigger=trigger,
            decision=decision,
            run_events=[{"event_type": "evidence_pack_ready", "stage": "evidence_pack_ready"}],
            artifacts={"evidence_pack": {"probe_results": [{"name": "metrics", "success": True}]}},
        )

        score = BehavioralScorer().score(trace)

        self.assertIn("scorers", score.artifacts)
        self.assertEqual(score.artifacts["temperature"]["temperature"], 0.0)

    @unittest.skipUnless(DEEPEVAL_AVAILABLE, "deepeval is optional in local development")
    def test_deepeval_import_path_is_ready_for_ci(self) -> None:
        deepeval = __import__("deepeval")

        self.assertTrue(hasattr(deepeval, "__name__"))


if __name__ == "__main__":
    unittest.main()
