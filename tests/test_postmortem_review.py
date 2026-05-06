from __future__ import annotations

import unittest

from shared.mesh_runtime import build_postmortem_review, load_schema, validate_payload


class PostmortemReviewContractTests(unittest.TestCase):
    def test_postmortem_review_schema_is_loadable(self) -> None:
        schema = load_schema("postmortem-review.schema.json")
        self.assertEqual(schema["title"], "PostmortemReview")

    def test_postmortem_review_payload_validates(self) -> None:
        packet = build_postmortem_review(
            run_id="run_1",
            review_id="review_1",
            reviewer={"operator_id": "reviewer@example.com", "roles": ["viewer"], "source": "proxy_header"},
            launcher_operator_id="launcher@example.com",
            verdict="accepted",
            findings=["run export includes timeline and Merkle proof"],
            action_items=[],
            reviewed_export_id="run_export_1",
            reviewed_package_sha256="a" * 64,
            related_event_id="evt_1",
        )
        validate_payload("postmortem-review.schema.json", packet)
        self.assertEqual(packet["schema_version"], "mesh.postmortem_review.v1")
        self.assertTrue(packet["independent_reviewer"])

    def test_postmortem_review_rejects_launch_operator_as_reviewer(self) -> None:
        with self.assertRaises(ValueError):
            build_postmortem_review(
                run_id="run_1",
                review_id="review_1",
                reviewer={"operator_id": "launcher@example.com", "roles": ["launcher"], "source": "proxy_header"},
                launcher_operator_id="launcher@example.com",
                verdict="accepted",
                findings=[],
                action_items=[],
            )
