from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    EvalJobRequest,
    ReleaseGatePolicy,
    build_data_plane_e2e,
    build_eval_jobs_e2e,
    build_posttraining_e2e,
    new_model_artifact,
    run_eval_job,
    write_eval_job_result,
)


class MeshBrainEvalJobsTests(unittest.TestCase):
    def test_eval_jobs_e2e_compares_artifacts_and_writes_required_sections(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            production = _production_artifact()
            result = build_eval_jobs_e2e(
                candidate_artifact=posttraining.artifact,
                production_artifact=production,
                dataset_bundle=data_result.bundle,
                output_directory=Path(temp_dir) / "eval_job",
            )
            report = json.loads((Path(temp_dir) / "eval_job" / "eval_job.json").read_text(encoding="utf-8"))

        self.assertEqual(result.release_decision, "promote")
        self.assertEqual(set(result.suite_results), {"nvidia_datacenter", "apple_silicon"})
        self.assertTrue(result.comparison.passed)
        self.assertTrue(result.sandbox_tool_use.passed)
        self.assertTrue(result.policy_red_team.passed)
        self.assertTrue(result.latency_cost.passed)
        self.assertEqual(report["release_decision"], "promote")
        self.assertIn("comparison", report)
        self.assertIn("latency_cost", report)

    def test_candidate_without_required_improvement_routes_to_manual_review(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=temp_dir)
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            result = run_eval_job(
                EvalJobRequest(
                    candidate_artifact=posttraining.artifact,
                    production_artifact=_production_artifact(),
                    dataset_bundle=data_result.bundle,
                    hardware_tiers=["nvidia_datacenter"],
                    policy=ReleaseGatePolicy(task_success_threshold=0.8),
                    required_backend_techniques=["prefix"],
                    production_metrics={"task_success_rate": 0.99},
                    min_task_success_improvement=0.02,
                )
            )

        self.assertEqual(result.release_decision, "manual_review")
        self.assertEqual(result.comparison.reasons, ["candidate_improvement_below_threshold"])

    def test_missing_backend_capability_blocks_eval_job(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=temp_dir)
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            result = run_eval_job(
                EvalJobRequest(
                    candidate_artifact=posttraining.artifact,
                    dataset_bundle=data_result.bundle,
                    hardware_tiers=["cpu_edge"],
                    policy=ReleaseGatePolicy(task_success_threshold=0.8),
                    required_backend_techniques=["disaggregated prefill", "NVFP4"],
                )
            )

        self.assertEqual(result.release_decision, "block")
        self.assertIn("hardware_tier_gate_blocked", result.latency_cost.reasons)
        self.assertEqual(result.suite_results["cpu_edge"].release_gate.release_decision, "block")

    def test_sandbox_disabled_blocks_tool_use_eval(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=temp_dir)
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            result = run_eval_job(
                EvalJobRequest(
                    candidate_artifact=posttraining.artifact,
                    dataset_bundle=data_result.bundle,
                    hardware_tiers=["nvidia_datacenter"],
                    policy=ReleaseGatePolicy(task_success_threshold=0.8),
                    required_backend_techniques=["prefix"],
                    sandbox_enabled=False,
                )
            )
            written = write_eval_job_result(result=result, output_directory=Path(temp_dir) / "eval_job")
            sandbox_report_exists = Path(written["sandbox_tool_use.json"]).exists()

        self.assertEqual(result.release_decision, "block")
        self.assertEqual(result.sandbox_tool_use.reasons, ["sandbox_disabled"])
        self.assertTrue(sandbox_report_exists)


def _production_artifact():
    artifact = new_model_artifact(
        artifact_type="tenant_adapter",
        version="prod",
        signed_manifest_ref="sha256:production",
        tenant_id="tenant_a",
        task_type="crops",
        dataset_manifest_ids=["dataset_previous"],
        training_run_id="train_previous",
    )
    artifact.state = "production"
    return artifact


if __name__ == "__main__":
    unittest.main()
