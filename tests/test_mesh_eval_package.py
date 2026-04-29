from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.evaluation.service import EvaluationService
from services.evaluation.mesh_eval import MeshEvalConfig, evaluate_native_mesh, run_latentmas_tokenizer_probe
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
        self.assertEqual(mesh_eval["latent_mesh"]["tokenizer_probe"]["status"], "not_configured")
        self.assertIn("trajectory_score", result)
        self.assertIn("verifier_output", result)

    def test_config_rejects_two_tokenizer_backends(self) -> None:
        with self.assertRaises(ValueError):
            MeshEvalConfig(tokenizer_json="a.json", sentencepiece_model="b.model").validate()

    def test_latentmas_probe_runs_configured_command(self) -> None:
        with TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "probe.py"
            script.write_text(
                "import json\n"
                "import sys\n"
                "text = sys.argv[sys.argv.index('--tokenize-text') + 1]\n"
                "budget = int(sys.argv[sys.argv.index('--context-token-budget') + 1])\n"
                "print(json.dumps({"
                "'tokenizer_backend': 'Heuristic', "
                "'context_token_budget': budget, "
                "'retained_text': text[-budget:], "
                "'original_chars': len(text), "
                "'retained_chars': min(len(text), budget), "
                "'token_count': min(len(text), budget), "
                "'truncated': len(text) > budget"
                "}))\n",
                encoding="utf-8",
            )

            result = run_latentmas_tokenizer_probe(
                config=MeshEvalConfig(
                    context_token_budget=4,
                    latentmas_command=f"python3 {script}",
                ),
                text="abcdef",
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["context_token_budget"], 4)
        self.assertEqual(result["retained_text"], "cdef")

    def test_evaluation_service_runs_latentmas_probe_end_to_end(self) -> None:
        command = "cargo run --quiet --manifest-path latent-mesh/LatentMAS/Cargo.toml --"
        with patch.dict(
            "os.environ",
            {
                "MESH_EVAL_LATENTMAS_COMMAND": command,
                "MESH_EVAL_CONTEXT_TOKEN_BUDGET": "4",
                "MESH_EVAL_LATENTMAS_TIMEOUT_SECONDS": "30",
            },
        ):
            result = EvaluationService().evaluate_trace(
                trigger=Trigger.from_dict(_signal_trigger()),
                decision=Decision.from_dict(load_fixture("decisions", "high_risk_decision.json")),
                run_events=[{"sequence": 1, "event_type": "evidence_pack_ready", "stage": "evidence_pack_ready"}],
                artifacts={"evidence_pack": {"probe_results": [{"name": "metrics"}]}},
            )

        probe = result["task_trace"]["mesh_eval"]["latent_mesh"]["tokenizer_probe"]
        self.assertEqual(probe["status"], "ok")
        self.assertEqual(probe["context_token_budget"], 4)
        self.assertLessEqual(probe["token_count"], 4)


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
