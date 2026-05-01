from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    ApprovalDecision,
    MeshOSAgentRuntime,
    ModelProposal,
    RuntimeUser,
    ToolDefinition,
    build_agent_runtime_e2e,
    build_data_plane_e2e,
    build_posttraining_e2e,
    build_serving_fabric_e2e,
    new_model_artifact,
)


class MeshBrainAgentRuntimeTests(unittest.TestCase):
    def test_agent_runtime_e2e_routes_protected_action_to_approval_and_replay(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            posttraining.artifact.state = "production"
            base = new_model_artifact(artifact_type="base_model", version="base", signed_manifest_ref="sha256:base")
            base.artifact_id = "base"
            base.state = "production"
            _, serving_plan = build_serving_fabric_e2e(artifacts=[base, posttraining.artifact])
            runtime, result = build_agent_runtime_e2e(serving_plan=serving_plan)
            replay = runtime.replay(result)
            row = runtime.export_replay_dataset_row(
                tenant_id="tenant_a",
                result=result,
                provenance_pointer="audit://mb_agent_runtime_reference",
            )

        event_types = [event.event_type for event in result.events]
        self.assertEqual(result.status, "approval_required")
        self.assertIn("tool_schema_validated", event_types)
        self.assertIn("policy_decision", event_types)
        self.assertIn("approval_decision", event_types)
        self.assertNotIn("tool_call", event_types)
        self.assertTrue(replay["policy_recorded_before_tool"])
        self.assertEqual(row.row_type, "rl_trajectory")
        self.assertEqual(row.payload["terminal_outcome"], "approval_required")

    def test_tool_execution_requires_schema_validation_and_policy_first(self) -> None:
        runtime = _runtime()
        result = runtime.run(
            run_id="run_allowed",
            serving_plan=_serving_plan(),
            user=RuntimeUser(user_id="sre_1", tenant_id="tenant_a", roles={"sre"}),
            proposal=ModelProposal(
                content="Inspect deployment.",
                tool_name="kubernetes.get_deployment",
                tool_arguments={"deployment": "search"},
            ),
        )
        event_types = [event.event_type for event in result.events]

        self.assertEqual(result.status, "completed")
        self.assertLess(event_types.index("tool_schema_validated"), event_types.index("tool_call"))
        self.assertLess(event_types.index("policy_decision"), event_types.index("tool_call"))

    def test_invalid_schema_blocks_before_tool_execution(self) -> None:
        runtime = _runtime()
        result = runtime.run(
            run_id="run_invalid",
            serving_plan=_serving_plan(),
            user=RuntimeUser(user_id="sre_1", tenant_id="tenant_a", roles={"sre"}),
            proposal=ModelProposal(
                content="Inspect deployment.",
                tool_name="kubernetes.get_deployment",
                tool_arguments={"name": "search"},
            ),
        )

        self.assertEqual(result.status, "blocked_invalid_schema")
        self.assertNotIn("tool_call", [event.event_type for event in result.events])

    def test_permission_denial_blocks_before_tool_execution(self) -> None:
        runtime = _runtime()
        result = runtime.run(
            run_id="run_denied",
            serving_plan=_serving_plan(),
            user=RuntimeUser(user_id="viewer_1", tenant_id="tenant_a", roles={"viewer"}),
            proposal=ModelProposal(
                content="Inspect deployment.",
                tool_name="kubernetes.get_deployment",
                tool_arguments={"deployment": "search"},
            ),
        )

        self.assertEqual(result.status, "blocked_by_policy")
        self.assertNotIn("tool_call", [event.event_type for event in result.events])

    def test_memory_write_is_proposed_reviewed_and_versioned(self) -> None:
        runtime = _runtime()
        result = runtime.run(
            run_id="run_memory",
            serving_plan=_serving_plan(),
            user=RuntimeUser(user_id="sre_1", tenant_id="tenant_a", roles={"sre"}),
            proposal=ModelProposal(
                content="Remember bounded runbook.",
                memory_write={"procedure": "Check deployment before restart."},
            ),
            approval=ApprovalDecision(required=True, approved=True, approver="lead_1"),
        )

        self.assertEqual(result.memory_records[0].state, "reviewed")
        self.assertEqual(result.memory_records[0].version, 1)
        self.assertEqual(result.memory_records[0].reviewed_by, "lead_1")


def _runtime() -> MeshOSAgentRuntime:
    return MeshOSAgentRuntime(
        tool_registry=[
            ToolDefinition(
                name="kubernetes.get_deployment",
                schema={
                    "type": "object",
                    "properties": {"deployment": {"type": "string"}},
                    "required": ["deployment"],
                    "additionalProperties": False,
                },
                allowed_roles={"sre"},
            )
        ]
    )


def _serving_plan():
    class Route:
        tenant_id = "tenant_a"

        def to_dict(self):
            return {"tenant_id": "tenant_a", "route_mode": "standard"}

    class Plan:
        adapter_artifact_ids: list[str] = []
        route = Route()

        def to_dict(self):
            return {"adapter_artifact_ids": [], "route": self.route.to_dict()}

    return Plan()


if __name__ == "__main__":
    unittest.main()
