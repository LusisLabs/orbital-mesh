from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from typing import Any

from mesh_brain import (
    MeshBrainRuntime,
    MeshBrainRegistry,
    ReleaseGatePolicy,
    ToolCall,
    ToolPolicy,
    build_dataset_bundle,
    curated_quality_source_coverage_pass,
    evaluate_release_gate,
    new_model_artifact,
    run_e2e_reference_flow,
)


class MeshBrainDataPlaneTests(unittest.TestCase):
    def test_dataset_bundle_outputs_required_jsonl_rows_and_redacts_secrets(self) -> None:
        bundle = build_dataset_bundle(
            tenant_id="tenant_a",
            source_manifest_id="manifest_1",
            source_records=[
                {
                    "source": "incident",
                    "text": "Investigate latency. api_key=abcdefghi123456789 must not leak.",  # gitleaks:allow
                    "provenance_pointer": "incident://1",
                }
            ],
            dataset_version="dataset_test",
        )

        outputs = bundle.rows_by_output()

        self.assertEqual(set(outputs), {"sft.jsonl", "preference_pairs.jsonl", "rl_trajectories.jsonl", "eval_cases.jsonl", "red_team_cases.jsonl"})
        self.assertEqual(bundle.manifest()["dataset_version"], "dataset_test")
        self.assertEqual(len(bundle.rows), 5)
        for row in bundle.rows:
            self.assertEqual(row.tenant_id, "tenant_a")
            self.assertEqual(row.redaction_status, "redacted")
            self.assertIn("incident://1", row.provenance_pointer)
            self.assertNotIn("abcdefghi123456789", str(row.to_dict()))


class MeshBrainRuntimePolicyTests(unittest.TestCase):
    def test_runtime_blocks_protected_tool_without_approval_and_keeps_audit_trace(self) -> None:
        runtime = MeshBrainRuntime(
            tool_policy=ToolPolicy(
                allowed_tools={"kubernetes.restart_deployment"},
                protected_tools={"kubernetes.restart_deployment"},
            )
        )
        trace = runtime.run_tool_call(
            run_id="run_1",
            route=_route(),
            tool_call=ToolCall(
                name="kubernetes.restart_deployment",
                arguments={"deployment": "search"},
                risk_level="high",
            ),
        )

        self.assertEqual(trace["status"], "approval_required")
        self.assertTrue(trace["traceable"])
        self.assertEqual([event["event_type"] for event in trace["events"]], ["model_call", "policy_decision", "final_output"])

    def test_runtime_executes_allowed_low_risk_tool(self) -> None:
        runtime = MeshBrainRuntime(tool_policy=ToolPolicy(allowed_tools={"kubernetes.get_deployment"}))
        trace = runtime.run_tool_call(
            run_id="run_2",
            route=_route(),
            tool_call=ToolCall(name="kubernetes.get_deployment", arguments={"deployment": "search"}),
        )

        self.assertEqual(trace["status"], "allow")
        self.assertIn("tool_call", [event["event_type"] for event in trace["events"]])


class MeshBrainReferenceFlowTests(unittest.TestCase):
    def test_reference_flow_covers_data_training_eval_serving_runtime_and_trace_export(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_e2e_reference_flow(state_directory=temp_dir, tenant_id="tenant_a")

        self.assertEqual(result.training_manifest.method, "lora")
        self.assertEqual(result.artifact.state, "production")
        self.assertEqual(result.artifact.metadata["promotion_approval"]["approval_id"], "approval_reference_flow")
        self.assertEqual(result.artifact.metadata["rollback_manifest_ref"], "rollback://tenant_a/crops/reference-flow")
        self.assertEqual(result.gate_result.release_decision, "promote")
        self.assertEqual(result.serving_route.engine, "sglang")
        self.assertTrue(result.serving_route.verification_required)
        self.assertEqual(result.runtime_trace["status"], "approval_required")
        self.assertEqual(result.trace_dataset_row.row_type, "rl_trajectory")
        self.assertEqual(result.trace_dataset_row.payload["terminal_outcome"], "approval_required")

    def test_registry_rejects_promotion_without_operator_approval_and_rollback_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            registry = MeshBrainRegistry(temp_dir)
            artifact = registry.register_artifact(
                new_model_artifact(
                    artifact_type="tenant_adapter",
                    version="dataset_test",
                    signed_manifest_ref="sha256:adapter",
                    tenant_id="tenant_a",
                    task_type="crops",
                )
            )
            gate_result = evaluate_release_gate(
                candidate_artifact_id=artifact.artifact_id,
                metrics={
                    "critical_policy_regressions": 0,
                    "unsafe_autonomous_action_rate_delta": 0,
                    "schema_validity_delta": 0,
                    "task_success_rate": 1.0,
                    "canary_passed": False,
                    "model_kernel_passed": True,
                    "live_serving_smoke_passed": True,
                    "response_eval_passed": True,
                    "judge_rubric_passed": True,
                    "red_team_regression_passed": True,
                    "curated_quality_training_passed": True,
                    "quality_source_coverage": curated_quality_source_coverage_pass(),
                },
                policy=ReleaseGatePolicy(task_success_threshold=0.8),
            )

            missing_quality_coverage_gate = evaluate_release_gate(
                candidate_artifact_id=artifact.artifact_id,
                metrics={
                    key: value
                    for key, value in gate_result.metrics.items()
                    if key != "quality_source_coverage"
                },
                policy=ReleaseGatePolicy(task_success_threshold=0.8),
            )
            with self.assertRaisesRegex(ValueError, "curated quality coverage"):
                registry.promote_artifact(
                    artifact.artifact_id,
                    missing_quality_coverage_gate,
                    alias="tenant_a/crops",
                    approval={
                        "approval_id": "approval_test",
                        "operator_id": "operator_1",
                        "roles": ["approver"],
                        "approved_at": "2026-05-04T00:00:00+00:00",
                        "approved": True,
                    },
                    rollback_manifest_ref="rollback://tenant_a/crops",
                )

            with self.assertRaisesRegex(ValueError, "operator approval"):
                registry.promote_artifact(artifact.artifact_id, gate_result, alias="tenant_a/crops")
            with self.assertRaisesRegex(ValueError, "rollback metadata"):
                registry.promote_artifact(
                    artifact.artifact_id,
                    gate_result,
                    alias="tenant_a/crops",
                    approval={
                        "approval_id": "approval_test",
                        "operator_id": "operator_1",
                        "roles": ["approver"],
                        "approved_at": "2026-05-04T00:00:00+00:00",
                        "approved": True,
                    },
                )


def _route() -> Any:
    class Route:
        def to_dict(self) -> dict[str, str]:
            return {
                "tenant_id": "tenant_a",
                "task_type": "crops",
                "hardware_tier": "nvidia_datacenter",
                "engine": "sglang",
            }

    return Route()


if __name__ == "__main__":
    unittest.main()
