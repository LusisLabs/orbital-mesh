from __future__ import annotations

import unittest

from shared.mesh_runtime.approval_queue import build_approval_queue_packet
from shared.mesh_runtime.control_plane_models import RunSession


def _session(*, blocked: bool = False) -> RunSession:
    session = RunSession.new(
        goal_id="goal_test",
        scenario_key="search_latency_regression",
        steering_mode="approval_gate",
        auto_mode=False,
        pause_points=[],
        evaluation_mode="native",
        orchestration_mode="native",
        artifacts={
            "operator": {
                "operator_id": "launcher@example.com",
                "roles": ["launcher"],
                "source": "proxy_header",
            },
            "input_signal": {
                "service": "semantic-search",
                "namespace": "search",
                "environment": "pilot",
            },
            "ownership_boundary": {
                "service": "semantic-search",
                "namespace": "search",
                "owner": {"owner_id": "platform.search"},
                "approver_roles": ["approver"],
            },
            "decision": {
                "decision_type": "rollback_deployment",
                "risk_level": "medium",
                "evidence_refs": ["evidence://decision"],
            },
            "evaluation": {
                "passed": not blocked,
                "final_recommendation": "human_review" if blocked else "execute",
                "blocking_reasons": ["approval required before execution"] if blocked else [],
            },
        },
    )
    session.stage = "awaiting_operator"
    session.status = "awaiting_operator"
    session.pending_pause_stage = "evaluation_ready"
    session.latest_event_id = "evt_latest"
    return session


class ApprovalQueuePacketTests(unittest.TestCase):
    def test_pending_approval_queue_item_is_schema_valid(self) -> None:
        session = _session()

        packet = build_approval_queue_packet(
            [session],
            {session.run_id: []},
            environment="staging",
            generated_at="2026-05-06T05:00:00Z",
        )

        self.assertEqual(packet["schema_version"], "mesh.approval_queue.v1")
        self.assertEqual(packet["status"], "ready")
        self.assertEqual(packet["pending_count"], 1)
        self.assertEqual(packet["blocked_count"], 0)
        item = packet["items"][0]
        self.assertEqual(item["approval_state"], "pending")
        self.assertEqual(item["allowed_commands"], ["approve", "resume", "cancel", "handoff"])
        self.assertEqual(item["requested_by"]["operator_id"], "launcher@example.com")
        self.assertEqual(item["approver_roles"], ["approver"])
        self.assertIn("run://", item["evidence_refs"][0])

    def test_blocked_approval_queue_item_uses_blocked_event(self) -> None:
        session = _session(blocked=True)

        packet = build_approval_queue_packet(
            [session],
            {
                session.run_id: [
                    {
                        "event_id": "evt_blocked",
                        "event_type": "approval_blocked",
                        "payload": {
                            "final_recommendation": "human_review",
                            "blocking_reasons": ["evidence sufficiency failed"],
                        },
                    }
                ]
            },
            environment="staging",
            generated_at="2026-05-06T05:00:00Z",
        )

        self.assertEqual(packet["status"], "blocked")
        self.assertEqual(packet["blocked_count"], 1)
        item = packet["items"][0]
        self.assertEqual(item["approval_state"], "blocked")
        self.assertEqual(item["blockers"], ["evidence sufficiency failed"])
        self.assertEqual(item["allowed_commands"], ["explain_blockers", "override_decision", "cancel", "handoff"])
        self.assertIn("event://evt_blocked", item["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
