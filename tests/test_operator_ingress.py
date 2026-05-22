from __future__ import annotations

import unittest

from shared.mesh_runtime.operator_ingress import build_operator_agent_ingress, build_operator_ingress_agent_task


class OperatorIngressTests(unittest.TestCase):
    def test_slack_request_can_investigate_but_not_directly_actuate(self) -> None:
        ingress = build_operator_agent_ingress(
            source="slack",
            request_id="slack_evt_1",
            operator_identity={"operator_id": "U123", "roles": ["viewer"]},
            requested_action="investigate",
            text="check the failed run",
            evidence={"slack_signature_valid": True, "channel_id": "C1"},
        )

        self.assertEqual(ingress["allowed_effect"], "investigation_request")
        self.assertEqual(ingress["direct_actuation_allowed"], False)
        self.assertEqual(ingress["authority"]["external_ingress_authoritative"], False)

    def test_slack_approval_still_requires_mesh_role_policy(self) -> None:
        ingress = build_operator_agent_ingress(
            source="slack",
            request_id="slack_evt_2",
            operator_identity={"operator_id": "U123", "roles": ["approver"]},
            requested_action="approve_actuation",
            text="approve remediation",
            evidence={"slack_signature_valid": True, "channel_id": "C1"},
        )

        self.assertEqual(ingress["allowed_effect"], "approval_review")
        self.assertEqual(ingress["approval_requires_mesh_role_policy"], True)
        self.assertEqual(ingress["direct_actuation_allowed"], False)

    def test_slack_request_projects_to_mesh_agent_task_only(self) -> None:
        ingress = build_operator_agent_ingress(
            source="slack",
            request_id="slack_evt_3",
            operator_identity={"operator_id": "U123", "roles": ["viewer"]},
            requested_action="investigate",
            text="inspect run run_1",
            evidence={"slack_signature_valid": True, "channel_id": "C1", "user_id": "U123"},
        )

        task = build_operator_ingress_agent_task(run_id="run_1", ingress=ingress, agents=["codex"])

        self.assertEqual(task["run_id"], "run_1")
        self.assertEqual(task["kind"], "operator_ingress_investigation")
        self.assertEqual(task["agents"], ["codex"])
        self.assertEqual(task["open_questions"], ["inspect run run_1"])
        self.assertEqual(task["operator_ingress"]["source"], "slack")
        self.assertEqual(task["operator_ingress"]["operator_identity"]["operator_id"], "U123")
        self.assertEqual(task["lane_routing"]["operator_ingress"]["allowed_effect"], "investigation_request")
        self.assertEqual(task["authority"]["direct_actuation_allowed"], False)
        self.assertEqual(task["authority"]["operator_ingress_authoritative"], False)
        self.assertEqual(task["attempts"], [])

    def test_slack_approval_projects_to_review_task_not_actuation(self) -> None:
        ingress = build_operator_agent_ingress(
            source="slack",
            request_id="slack_evt_4",
            operator_identity={"operator_id": "U123", "roles": ["approver"]},
            requested_action="approve_actuation",
            text="approve remediation",
            evidence={"slack_signature_valid": True, "channel_id": "C1"},
        )

        task = build_operator_ingress_agent_task(run_id="run_2", ingress=ingress)

        self.assertEqual(task["operator_ingress"]["allowed_effect"], "approval_review")
        self.assertEqual(task["authority"]["direct_actuation_allowed"], False)
        self.assertEqual(task["authority"]["approval_requires_mesh_role_policy"], True)
        self.assertEqual(task["memory_write_policy"]["direct_write_allowed"], False)

    def test_rejects_non_mesh_ingress_records(self) -> None:
        with self.assertRaisesRegex(ValueError, "operator ingress record"):
            build_operator_ingress_agent_task(run_id="run_1", ingress={"schema_version": "external"})


if __name__ == "__main__":
    unittest.main()
