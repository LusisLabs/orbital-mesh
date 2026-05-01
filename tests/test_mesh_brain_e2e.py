from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from mesh_brain import (
    MeshBrainRuntime,
    ToolCall,
    ToolPolicy,
    build_dataset_bundle,
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
                    "text": "Investigate latency. api_key=abcdefghi123456789 must not leak.",
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
        self.assertEqual(result.gate_result.release_decision, "promote")
        self.assertEqual(result.serving_route.engine, "sglang")
        self.assertTrue(result.serving_route.verification_required)
        self.assertEqual(result.runtime_trace["status"], "approval_required")
        self.assertEqual(result.trace_dataset_row.row_type, "rl_trajectory")
        self.assertEqual(result.trace_dataset_row.payload["terminal_outcome"], "approval_required")


def _route():
    class Route:
        def to_dict(self):
            return {
                "tenant_id": "tenant_a",
                "task_type": "crops",
                "hardware_tier": "nvidia_datacenter",
                "engine": "sglang",
            }

    return Route()


if __name__ == "__main__":
    unittest.main()
