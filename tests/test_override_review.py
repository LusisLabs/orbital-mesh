from __future__ import annotations

import unittest

from shared.mesh_runtime import build_override_review, load_schema, validate_payload


class OverrideReviewContractTests(unittest.TestCase):
    def test_override_review_schema_is_loadable(self) -> None:
        schema = load_schema("override-review.schema.json")
        self.assertEqual(schema["title"], "OverrideReview")

    def test_override_review_payload_validates(self) -> None:
        packet = build_override_review(
            run_id="run_1",
            review_id="review_1",
            reviewer={"operator_id": "reviewer@example.com", "roles": ["viewer"], "source": "proxy_header"},
            override_command={
                "event_id": "evt_1",
                "command_id": "cmd_1",
                "command_type": "override_decision",
                "issued_at": "2026-05-05T00:00:00Z",
                "operator_id": "approver@example.com",
            },
            verdict="accepted",
            reason="override was bounded and documented",
            findings=["decision override matched rollback runbook"],
            action_items=[],
            related_event_id="evt_2",
        )
        validate_payload("override-review.schema.json", packet)
        self.assertEqual(packet["schema_version"], "mesh.override_review.v1")
        self.assertTrue(packet["independent_reviewer"])

    def test_override_review_rejects_override_operator_as_reviewer(self) -> None:
        with self.assertRaises(ValueError):
            build_override_review(
                run_id="run_1",
                review_id="review_1",
                reviewer={"operator_id": "approver@example.com", "roles": ["approver"], "source": "proxy_header"},
                override_command={
                    "event_id": "evt_1",
                    "command_id": "cmd_1",
                    "command_type": "override_decision",
                    "issued_at": "2026-05-05T00:00:00Z",
                    "operator_id": "approver@example.com",
                },
                verdict="accepted",
                reason="self-review is not independent",
                findings=[],
                action_items=[],
            )

    def test_override_review_rejects_non_override_command(self) -> None:
        with self.assertRaises(ValueError):
            build_override_review(
                run_id="run_1",
                review_id="review_1",
                reviewer={"operator_id": "reviewer@example.com", "roles": ["viewer"], "source": "proxy_header"},
                override_command={
                    "event_id": "evt_1",
                    "command_id": "cmd_1",
                    "command_type": "approve",
                    "issued_at": "2026-05-05T00:00:00Z",
                    "operator_id": "approver@example.com",
                },
                verdict="accepted",
                reason="approve is not an override",
                findings=[],
                action_items=[],
            )
