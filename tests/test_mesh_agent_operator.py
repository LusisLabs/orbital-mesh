from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.mesh_agent_operator import (
    build_override_payload,
    _run_age_seconds,
    run_is_safe_for_agent_override,
    select_operator_agent,
)


def _paused_run(*, confidence: float = 0.72, risk_level: str = "medium") -> dict[str, object]:
    return {
        "run_id": "run_test",
        "stage": "awaiting_operator",
        "pending_pause_stage": "evaluation_ready",
        "artifacts": {
            "decision": {
                "confidence": confidence,
                "risk": {"level": risk_level},
                "execution_plan": {"rollback_plan": "restore prior revision"},
            },
            "evaluation": {
                "final_recommendation": "human_review",
                "stage_results": {
                    "schema_validation": {"passed": True},
                    "policy_validation": {"passed": True, "notes": []},
                    "business_rules": {"passed": False, "notes": ["approval required before execution"]},
                    "execution_readiness": {"passed": False, "notes": ["confidence below minimum threshold"]},
                    "remediation_safety": {"passed": False, "hard_stops": ["execution readiness failed"]},
                },
            },
        },
    }


class MeshAgentOperatorTests(unittest.TestCase):
    def test_selects_qualified_agent_by_priority(self) -> None:
        tasks = [
            {
                "attempts": [
                    {"agent": "latentmas", "completed_at": "now", "output": {"risk_flags": ["latentmas_output_unparseable"]}},
                    {"agent": "goose", "error": "rate limited"},
                    {"agent": "hermes", "status": "completed", "output": {"status": "completed"}},
                ]
            }
        ]
        self.assertEqual(select_operator_agent(tasks, ("hermes", "goose", "latentmas")), "hermes")

    def test_falls_back_to_native_mesh_without_qualified_agent(self) -> None:
        tasks = [{"attempts": [{"agent": "hermes", "error": "429"}]}]
        self.assertEqual(select_operator_agent(tasks, ("hermes",)), "native_mesh")

    def test_safe_override_accepts_only_recoverable_gate_blockers(self) -> None:
        self.assertTrue(run_is_safe_for_agent_override(_paused_run()))

    def test_safe_override_rejects_high_risk(self) -> None:
        self.assertFalse(run_is_safe_for_agent_override(_paused_run(risk_level="high")))

    def test_build_override_payload_raises_confidence_and_records_operator(self) -> None:
        payload = build_override_payload(
            _paused_run(confidence=0.72),
            operator_agent="hermes",
            confidence_floor=0.86,
            autonomy_tier="escalated",
        )
        self.assertEqual(payload["command"], "override_decision")
        self.assertEqual(payload["operator_agent"], "hermes")
        self.assertEqual(payload["autonomy_tier"], "escalated")
        self.assertEqual(payload["confidence"], 0.86)

    def test_run_age_seconds_parses_zulu_timestamp(self) -> None:
        age = _run_age_seconds(
            {"created_at": "2026-04-30T02:00:00Z"},
            now=datetime(2026, 4, 30, 2, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(age, 60.0)


if __name__ == "__main__":
    unittest.main()
