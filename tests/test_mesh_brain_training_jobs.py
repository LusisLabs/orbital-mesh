from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    TrainingJobRequest,
    build_data_plane_e2e,
    build_training_jobs_e2e,
    launch_lora_job,
    launch_preference_job,
    launch_quantization_job,
    launch_rl_rollout_job,
    launch_sft_job,
    write_training_job_result,
)
from mesh_brain.runtime import DatasetBundle, DatasetRow


class MeshBrainTrainingJobsTests(unittest.TestCase):
    def test_training_jobs_e2e_launches_required_methods_and_writes_manifests(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            jobs = build_training_jobs_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "jobs")

            self.assertEqual(set(jobs), {"sft", "qlora", "dpo", "agent_rl", "qat"})
            for name, job in jobs.items():
                job_dir = Path(temp_dir) / "jobs" / name
                self.assertTrue((job_dir / "training_job.json").exists())
                self.assertTrue((job_dir / "model_card.json").exists())
                self.assertTrue((job_dir / "deployment_manifest.json").exists())
                self.assertTrue((job_dir / "metrics.json").exists())
                self.assertEqual(job.status, "completed")
                self.assertEqual(job.deployment_manifest["dataset_versions"], [data_result.bundle.dataset_version])
                self.assertTrue(job.deployment_manifest["release_gate_required"])

        self.assertEqual(jobs["sft"].posttraining_run.artifact.artifact_type, "task_adapter")
        self.assertEqual(jobs["qlora"].posttraining_run.artifact.artifact_type, "tenant_adapter")
        self.assertEqual(jobs["dpo"].posttraining_run.artifact.artifact_type, "policy_adapter")
        self.assertEqual(jobs["agent_rl"].metrics["unsafe_action_rate"], 0.0)
        self.assertEqual(jobs["qat"].posttraining_run.artifact.artifact_type, "quantized_checkpoint")

    def test_launchers_track_metrics_outputs_signed_card_and_deployment_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            request = TrainingJobRequest(
                method="sft",
                tenant_id="tenant_a",
                task_type="crops",
                dataset_bundle=data_result.bundle,
                code_version="code-v1",
                base_artifact_id="base-model",
                hyperparameters={"epochs": 3},
                output_directory=str(Path(temp_dir) / "job"),
            )
            result = launch_sft_job(request)
            written = write_training_job_result(result=result)
            deployment_manifest = json.loads(Path(written["deployment_manifest.json"]).read_text(encoding="utf-8"))

        self.assertEqual(result.request.hyperparameters["epochs"], 3)
        self.assertGreater(result.metrics["tokens_seen"], 0)
        self.assertEqual([output.name for output in result.outputs], ["adapter_weights", "optimizer_state", "training_trace"])
        self.assertTrue(result.signed_model_card["signed_manifest_ref"].startswith("sha256:"))
        self.assertEqual(deployment_manifest["artifact_id"], result.posttraining_run.artifact.artifact_id)
        self.assertEqual(deployment_manifest["base_artifact_id"], "base-model")

    def test_preference_rl_and_quantization_jobs_require_matching_trainable_rows(self) -> None:
        bundle = DatasetBundle(
            dataset_version="dataset_sft_only",
            source_manifest_id="manifest_sft_only",
            created_at="2026-04-30T00:00:00+00:00",
            rows=[_row("sft")],
        )
        request = TrainingJobRequest(
            method="dpo",
            tenant_id="tenant_a",
            task_type="crops",
            dataset_bundle=bundle,
            code_version="code-v1",
            base_artifact_id="base-model",
        )

        with self.assertRaisesRegex(ValueError, "preference_pair"):
            launch_preference_job(request, method="dpo")

        rl_request = TrainingJobRequest(
            method="agent_rl",
            tenant_id="tenant_a",
            task_type="crops",
            dataset_bundle=bundle,
            code_version="code-v1",
            base_artifact_id="base-model",
        )
        with self.assertRaisesRegex(ValueError, "rl_trajectory"):
            launch_rl_rollout_job(rl_request)

        quantized = launch_quantization_job(request)
        self.assertEqual(quantized.outputs[0].name, "quantized_checkpoint")

    def test_lora_launcher_can_emit_qlora_hyperparameters(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=temp_dir)
            request = TrainingJobRequest(
                method="lora",
                tenant_id="tenant_a",
                task_type="crops",
                dataset_bundle=data_result.bundle,
                code_version="code-v1",
                base_artifact_id="base-model",
            )
            result = launch_lora_job(request, qlora=True)

        self.assertEqual(result.request.method, "qlora")
        self.assertTrue(result.posttraining_run.training_manifest.hyperparameters["quantized_base"])


def _row(row_type: str) -> DatasetRow:
    return DatasetRow(
        row_id=f"row_{row_type}",
        tenant_id="tenant_a",
        source="test",
        timestamp="2026-04-30T00:00:00+00:00",
        redaction_status="clean",
        license_usage_class="internal_enterprise",
        provenance_pointer=f"test://{row_type}",
        row_type=row_type,
        payload={"input": "investigate", "output": "done"},
    )


if __name__ == "__main__":
    unittest.main()
