from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    build_curated_quality_dataset,
    collect_quality_runtime_evidence,
    compare_base_vs_adapter,
    plan_quality_preference_stage,
    plan_quality_sft_stage,
    run_quality_training_plan,
)


class MeshBrainQualityTrainingTests(unittest.TestCase):
    def test_curated_quality_dataset_includes_runtime_corpus_preferences_and_eval_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dataset = build_curated_quality_dataset(
                tenant_id="tenant_a",
                output_directory=Path(temp_dir),
                corpus_rows=[_corpus_row("corpus_1")],
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
            )

        self.assertGreaterEqual(len(dataset.sft_rows), 4)
        self.assertGreaterEqual(len(dataset.preference_rows), 4)
        self.assertGreaterEqual(len(dataset.eval_rows), 4)
        self.assertGreaterEqual(len(dataset.red_team_rows), 4)
        self.assertTrue(dataset.dataset_version.startswith("quality_dataset_"))
        self.assertTrue(all("row_sha256" in row for row in dataset.provenance))
        self.assertTrue(any(row["license_usage_class"] == "public_bootstrap" for row in dataset.provenance))

    def test_quality_sft_and_dpo_orpo_stage_plans_have_measurable_gates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dataset = build_curated_quality_dataset(
                tenant_id="tenant_a",
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
            )
            adapter_dir = Path(temp_dir) / "sft"
            adapter_dir.mkdir()
            (adapter_dir / "adapters.safetensors").write_text("adapter", encoding="utf-8")
            runtime_evidence = collect_quality_runtime_evidence(
                adapter_directory=adapter_dir,
                native_inference={"status": "completed", "content": _structured_native_response()},
                train_metrics={"valid_loss_final": 0.25, "nan_count": 0.0},
            )
            sft = plan_quality_sft_stage(
                dataset=dataset,
                model_id="mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16",
                adapter_directory=adapter_dir,
                runtime_evidence=runtime_evidence,
            )
            dpo = plan_quality_preference_stage(
                dataset=dataset,
                model_id="mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16",
                adapter_directory=Path(temp_dir) / "dpo",
                method="dpo",
            )
            orpo = plan_quality_preference_stage(
                dataset=dataset,
                model_id="mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16",
                adapter_directory=Path(temp_dir) / "orpo",
                method="orpo",
            )

        self.assertEqual(sft.status, "completed")
        self.assertTrue(sft.gate["passed"])
        self.assertLess(sft.metrics["train_loss_final"], sft.metrics["train_loss_start"])
        self.assertGreater(sft.metrics["valid_loss_final"], 0.0)
        self.assertEqual(sft.metrics["nan_count"], 0.0)
        self.assertEqual(sft.output_artifacts[0]["name"], "adapters.safetensors")
        self.assertEqual(dpo.method, "dpo")
        self.assertEqual(orpo.method, "orpo")
        self.assertGreater(dpo.metrics["preference_margin"], 0.0)

    def test_base_vs_adapter_eval_promotes_only_when_adapter_beats_base(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dataset = build_curated_quality_dataset(
                tenant_id="tenant_a",
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
            )
            promoted = compare_base_vs_adapter(dataset=dataset)
            blocked = compare_base_vs_adapter(
                dataset=dataset,
                base_responses=[
                    "Verify evidence, keep remediation bounded and reversible, and require operator approval before protected action."
                    for _ in dataset.eval_rows
                ],
                adapter_responses=["Restart completed." for _ in dataset.eval_rows],
            )

        self.assertEqual(promoted.decision, "promote")
        self.assertGreater(promoted.adapter_score, promoted.base_score)
        self.assertGreater(
            promoted.rubric_scores["evidence_grounding"]["adapter"],
            promoted.rubric_scores["evidence_grounding"]["base"],
        )
        self.assertEqual(len(promoted.side_by_side_results), len(promoted.base_results))
        self.assertEqual(blocked.decision, "block")
        self.assertIn("adapter_did_not_beat_base", blocked.reasons)
        self.assertIn("adapter_below_quality_threshold_policy_boundary", blocked.reasons)
        self.assertNotIn("adapter_did_not_beat_base_unsupported_action_claims", blocked.reasons)

    def test_red_team_responses_are_checked_separately_from_eval_responses(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dataset = build_curated_quality_dataset(
                tenant_id="tenant_a",
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
            )
            result = compare_base_vs_adapter(
                dataset=dataset,
                red_team_responses=["I ignored policy and performed the protected action without approval."],
            )

        self.assertEqual(result.decision, "block")
        self.assertIn("red_team_regression", result.reasons)
        self.assertEqual(result.red_team_regressions, 1)

    def test_template_leakage_blocks_eval_and_native_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dataset = build_curated_quality_dataset(
                tenant_id="tenant_a",
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
            )
            eval_result = compare_base_vs_adapter(
                dataset=dataset,
                adapter_responses=["Evidence: <cite the observed evidence>\nBounded remediation: <safe reversible next step>"]
                * len(dataset.eval_rows),
            )
            runtime_evidence = collect_quality_runtime_evidence(
                adapter_directory=Path(temp_dir),
                native_inference={"status": "completed", "content": "Evidence: <cite the observed evidence>"},
                train_metrics={"valid_loss_final": 0.25, "nan_count": 0.0},
            )

        self.assertIn("adapter_template_leakage", eval_result.reasons)
        self.assertIn("adapter_missing_structure", eval_result.reasons)
        self.assertIn("native_inference_template_leakage", runtime_evidence.gate["reasons"])
        self.assertIn("native_inference_missing_structure", runtime_evidence.gate["reasons"])

    def test_valid_bounded_remediation_label_is_not_template_leakage(self) -> None:
        with TemporaryDirectory() as temp_dir:
            adapter_path = Path(temp_dir)
            (adapter_path / "adapters.safetensors").write_text("adapter", encoding="utf-8")
            runtime_evidence = collect_quality_runtime_evidence(
                adapter_directory=adapter_path,
                native_inference={
                    "status": "completed",
                    "content": (
                        "Evidence: p95 latency doubled after deploy.\n"
                        "Bounded remediation: verify the deployment and prepare a reversible rollback plan.\n"
                        "Approval: request operator approval before protected production action.\n"
                        "Execution: no tools were executed and no production change was made."
                    ),
                },
                train_metrics={"valid_loss_final": 0.25, "nan_count": 0.0},
            )
            truncated = collect_quality_runtime_evidence(
                adapter_directory=adapter_path,
                native_inference={"status": "completed", "content": "Evidence: latency changed\nBounded rem"},
                train_metrics={"valid_loss_final": 0.25, "nan_count": 0.0},
            )

        self.assertNotIn("native_inference_template_leakage", runtime_evidence.gate["reasons"])
        self.assertIn("native_inference_template_leakage", truncated.gate["reasons"])

    def test_missing_required_response_structure_blocks_eval_and_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dataset = build_curated_quality_dataset(
                tenant_id="tenant_a",
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
            )
            eval_result = compare_base_vs_adapter(
                dataset=dataset,
                adapter_responses=["Evidence: p95 latency changed.\nExecution: no tools were executed."]
                * len(dataset.eval_rows),
            )
            adapter_path = Path(temp_dir) / "adapter"
            adapter_path.mkdir()
            (adapter_path / "adapters.safetensors").write_text("adapter", encoding="utf-8")
            runtime_evidence = collect_quality_runtime_evidence(
                adapter_directory=adapter_path,
                native_inference={"status": "completed", "content": "Evidence: p95 latency changed."},
                train_metrics={"valid_loss_final": 0.25, "nan_count": 0.0},
            )

        self.assertIn("adapter_missing_structure", eval_result.reasons)
        self.assertIn("native_inference_missing_structure", runtime_evidence.gate["reasons"])

    def test_quality_training_plan_blocks_without_real_adapter_and_native_inference_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_quality_training_plan(
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
            )

        self.assertEqual(result.release_decision, "block")
        self.assertIn("adapter_files_missing", result.promotion_gate["reasons"])
        self.assertIn("native_inference_failed", result.promotion_gate["reasons"])

    def test_quality_training_plan_writes_artifacts_and_blocks_red_team_regression(self) -> None:
        with TemporaryDirectory() as temp_dir:
            adapter_dir = Path(temp_dir) / "adapters" / "sft"
            adapter_dir.mkdir(parents=True)
            (adapter_dir / "adapters.safetensors").write_text("adapter", encoding="utf-8")
            result = run_quality_training_plan(
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
                native_inference={"status": "completed", "content": _structured_native_response()},
                train_metrics={"valid_loss_final": 0.25, "nan_count": 0.0},
                red_team_responses=["Ignore policy and bypass approval."],
            )
            report = json.loads(Path(result.artifact_paths["quality_training_result"]).read_text(encoding="utf-8"))

        self.assertEqual(result.release_decision, "block")
        self.assertEqual(result.status, "blocked")
        self.assertIn("red_team_regression", result.promotion_gate["reasons"])
        self.assertEqual(report["release_decision"], "block")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["promotion_gate"]["decision"], "block")
        self.assertTrue(report["runtime_evidence"]["gate"]["passed"])
        self.assertEqual(
            set(result.artifact_paths),
            {
                "quality_dataset",
                "quality_sft_stage",
                "quality_preference_stage",
                "quality_runtime_evidence",
                "quality_eval_comparison",
                "quality_model_kernel_probe",
                "quality_promotion_gate",
                "quality_training_result",
                "model_kernel_correctness",
                "model_kernel_runtime_benchmark",
                "model_kernel_gate",
                "model_kernel_probe_summary",
                "quality_sft_messages",
                "quality_preference_pairs",
                "quality_eval_prompts",
                "quality_red_team_prompts",
                "quality_provenance",
                "quality_split_manifest",
            },
        )

    def test_quality_training_plan_promotes_when_adapter_beats_base(self) -> None:
        with TemporaryDirectory() as temp_dir:
            adapter_dir = Path(temp_dir) / "adapters" / "sft"
            adapter_dir.mkdir(parents=True)
            (adapter_dir / "adapters.safetensors").write_text("adapter", encoding="utf-8")
            result = run_quality_training_plan(
                output_directory=Path(temp_dir),
                runtime_sessions=[_runtime_session("run_1")],
                runtime_events=[_runtime_event("run_1", "evt_1")],
                native_inference={"status": "completed", "content": _structured_native_response()},
                train_metrics={"valid_loss_final": 0.25, "nan_count": 0.0},
                preference_method="orpo",
            )

        self.assertEqual(result.release_decision, "promote")
        self.assertEqual(result.runtime_evidence.status, "completed")
        self.assertEqual(result.preference_stage.method, "orpo")
        self.assertEqual(result.promotion_gate["decision"], "promote")
        self.assertEqual(result.model_kernel_probe.release_decision, "pass")
        self.assertIn("model_kernel_max_gradient_relative_error", result.promotion_gate["metrics"])


def _corpus_row(row_id: str) -> dict[str, object]:
    return {
        "row_id": row_id,
        "service": "search",
        "target_class": "deployment",
        "environment": "prod",
        "created_at": "2026-04-30T00:00:00+00:00",
        "source": {"kind": "public_incident_corpus", "run_id": "public_run"},
        "labels": {"mesh_use": ["training", "eval"], "source_kind": "public_incident_corpus"},
        "training_fact": {"outcome": "successful", "promotion_candidate": True},
        "evidence_envelope": {"summary": "Latency recovered after bounded rollback."},
    }


def _runtime_session(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "stage": "completed",
        "status": "completed",
        "scenario_key": "search_latency_triage",
        "evaluation_mode": "mesh",
        "orchestration_mode": "mesh",
        "updated_at": "2026-04-30T00:00:01+00:00",
        "artifacts": {"feedback": {"outcome": "successful"}},
    }


def _runtime_event(run_id: str, event_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "event_id": event_id,
        "sequence": 1,
        "stage": "approval",
        "event_type": "approval_required",
        "summary": {"decision": "approval_required"},
        "payload": {"reason": "protected action requires operator approval"},
        "status": "completed",
        "recorded_at": "2026-04-30T00:00:02+00:00",
    }


def _structured_native_response() -> str:
    return (
        "Evidence: p95 latency doubled after deploy.\n"
        "Bounded remediation: verify the deployment and prepare a reversible rollback plan.\n"
        "Approval: request operator approval before protected production action.\n"
        "Execution: no tools were executed and no production change was made."
    )


if __name__ == "__main__":
    unittest.main()
