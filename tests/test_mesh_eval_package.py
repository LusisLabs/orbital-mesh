from __future__ import annotations

import unittest

from services.evaluation.mesh_eval import MeshEvalConfig, evaluate_native_mesh
from shared.mesh_runtime import Decision, Trigger, load_fixture


class MeshEvalPackageTests(unittest.TestCase):
    def test_config_packages_latent_mesh_tokenizer_args(self) -> None:
        config = MeshEvalConfig(
            context_token_budget=4096,
            tokenizer_json="/models/tokenizer.json",
        )

        artifact = config.to_artifact()

        self.assertEqual(artifact["package"], "native_mesh_eval")
        self.assertEqual(artifact["latent_mesh"]["tokenizer_backend"], "huggingface_tokenizers")
        self.assertEqual(
            artifact["latent_mesh"]["rust_args"],
            ["--context-token-budget", "4096", "--tokenizer-json", "/models/tokenizer.json"],
        )

    def test_native_eval_trace_carries_mesh_eval_artifact(self) -> None:
        result = evaluate_native_mesh(
            trigger=Trigger.from_dict(_signal_trigger()),
            decision=Decision.from_dict(load_fixture("decisions", "high_risk_decision.json")),
            run_events=[{"sequence": 1, "event_type": "evidence_pack_ready", "stage": "evidence_pack_ready"}],
            artifacts={"evidence_pack": {"probe_results": [{"name": "metrics"}]}},
            config=MeshEvalConfig(context_token_budget=1024, sentencepiece_model="/models/spiece.model"),
        )

        mesh_eval = result["task_trace"]["mesh_eval"]
        self.assertEqual(mesh_eval["package"], "native_mesh_eval")
        self.assertEqual(mesh_eval["latent_mesh"]["context_token_budget"], 1024)
        self.assertEqual(mesh_eval["latent_mesh"]["tokenizer_backend"], "sentencepiece")
        self.assertIn("trajectory_score", result)
        self.assertIn("verifier_output", result)

    def test_config_rejects_two_tokenizer_backends(self) -> None:
        with self.assertRaises(ValueError):
            MeshEvalConfig(tokenizer_json="a.json", sentencepiece_model="b.model").validate()


def _signal_trigger() -> dict:
    return {
        "trigger_id": "tr_mesh_eval",
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
