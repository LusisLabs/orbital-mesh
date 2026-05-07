from __future__ import annotations

import unittest

from shared.mesh_runtime import build_operator_handoff, load_schema, validate_payload


class OperatorHandoffContractTests(unittest.TestCase):
    def test_operator_handoff_schema_is_loadable(self) -> None:
        schema = load_schema("operator-handoff.schema.json")
        self.assertEqual(schema["title"], "OperatorHandoff")

    def test_operator_handoff_payload_validates(self) -> None:
        packet = build_operator_handoff(
            run_id="run_1",
            handoff_id="handoff_1",
            from_operator={"operator_id": "launcher@example.com", "roles": ["launcher"], "source": "proxy_header"},
            to_operator={"operator_id": "approver@example.com", "roles": ["approver"], "source": "operator_handoff"},
            reason="shift change",
            next_action="review evaluation blockers before approval",
            urgency="high",
            related_event_id="evt_1",
        )
        validate_payload("operator-handoff.schema.json", packet)
        self.assertEqual(packet["schema_version"], "mesh.operator_handoff.v1")
        self.assertEqual(packet["status"], "open")
        self.assertEqual(packet["urgency"], "high")

    def test_operator_handoff_rejects_missing_next_action(self) -> None:
        with self.assertRaises(ValueError):
            build_operator_handoff(
                run_id="run_1",
                handoff_id="handoff_1",
                from_operator={"operator_id": "launcher@example.com", "roles": ["launcher"], "source": "proxy_header"},
                to_operator={"operator_id": "approver@example.com", "roles": ["approver"], "source": "operator_handoff"},
                reason="shift change",
                next_action="",
            )
