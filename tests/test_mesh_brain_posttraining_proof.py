from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.posttraining_proof import (
    LocalSubprocessTrainingBackend,
    run_posttraining_proof,
)
from shared.mesh_runtime.monitoring_corpus import build_public_monitoring_corpus_rows


class MeshBrainPosttrainingProofTests(unittest.TestCase):
    def test_real_local_posttraining_proof_registers_evals_and_smoke_serves_artifact(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_posttraining_proof(output_directory=Path(temp_dir), tenant_id="tenant_a")
            backend = json.loads((Path(temp_dir) / "posttraining_backend_result.json").read_text(encoding="utf-8"))
            adapter_export = json.loads((Path(temp_dir) / "posttraining_adapter_export.json").read_text(encoding="utf-8"))
            deployment = json.loads((Path(temp_dir) / "posttraining_deployment_record.json").read_text(encoding="utf-8"))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.backend_result["status"], "completed")
        self.assertIsNotNone(result.registered_artifact)
        self.assertIsNotNone(result.adapter_export)
        self.assertIsNotNone(result.eval_job)
        self.assertIsNotNone(result.serving_smoke)
        self.assertEqual(result.adapter_export["export_format"], "mlx_lm_lora")
        self.assertEqual(result.adapter_export["backend_compatibility"]["training_entrypoint"], "mlx_lm_lora.train")
        self.assertIn("--adapter-path", result.adapter_export["load_metadata"]["generate_command"])
        self.assertEqual(result.eval_job["release_decision"], "promote")
        self.assertEqual(result.serving_smoke["status"], "passed")
        self.assertEqual(result.deployment_record["status"], "smoke_served")
        self.assertFalse(result.deployment_record["deployed"])
        self.assertEqual(result.deployment_record["release_decision"], "promote")
        self.assertEqual(backend["backend_name"], "local_subprocess_training_backend")
        self.assertEqual(adapter_export["export_format"], "mlx_lm_lora")
        self.assertEqual(deployment["status"], "smoke_served")
        self.assertEqual(deployment["adapter_export_id"], result.adapter_export["export_id"])
        self.assertIn("posttraining_backend_result", result.artifact_paths)
        self.assertIn("posttraining_adapter_export", result.artifact_paths)
        self.assertIn("posttraining_adapter_export_manifest", result.artifact_paths)
        self.assertIn("posttraining_eval_job", result.artifact_paths)
        self.assertIn("posttraining_serving_smoke", result.artifact_paths)

    def test_posttraining_proof_uses_corpus_and_runtime_context_for_dataset(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_posttraining_proof(
                output_directory=Path(temp_dir),
                tenant_id="tenant_a",
                corpus_rows=build_public_monitoring_corpus_rows()[:1],
                runtime_sessions=[
                    {
                        "run_id": "run_live",
                        "stage": "completed",
                        "status": "completed",
                        "scenario_key": "runtime_context",
                        "created_at": "2026-04-30T00:00:00+00:00",
                        "updated_at": "2026-04-30T00:00:01+00:00",
                        "artifacts": {"feedback": {"outcome": "successful"}},
                    }
                ],
                runtime_events=[
                    {
                        "run_id": "run_live",
                        "event_id": "evt_1",
                        "sequence": 1,
                        "stage": "feedback",
                        "event_type": "feedback_recorded",
                        "recorded_at": "2026-04-30T00:00:02+00:00",
                        "payload": {"outcome": "successful"},
                        "status": "completed",
                    }
                ],
            )
            manifest = json.loads((Path(temp_dir) / "data" / "dataset_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.dataset_context_summary["corpus_record_count"], 1)
        self.assertEqual(result.dataset_context_summary["runtime_session_count"], 1)
        self.assertEqual(result.dataset_context_summary["runtime_event_count"], 1)
        self.assertGreater(manifest["output_counts"]["sft.jsonl"], 1)
        self.assertEqual(result.backend_result["metrics"]["train_rows"], 3.0)

    def test_local_subprocess_posttraining_proof_blocks_failed_command(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_posttraining_proof(
                output_directory=Path(temp_dir),
                tenant_id="tenant_a",
                backend=LocalSubprocessTrainingBackend(),
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.backend_result["status"], "failed")
        self.assertEqual(result.backend_result["return_code"], 7)
        self.assertIsNone(result.registered_artifact)
        self.assertIsNone(result.adapter_export)
        self.assertIsNone(result.eval_job)
        self.assertIsNone(result.serving_smoke)
        self.assertEqual(result.deployment_record["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
