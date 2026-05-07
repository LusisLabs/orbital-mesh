from __future__ import annotations

import copy
import unittest

from shared.mesh_runtime import load_fixture
from shared.mesh_runtime.perennial import evaluate_darkharness_packet_policy


class DarkharnessPolicyTests(unittest.TestCase):
    def test_policy_allows_approved_production_action(self) -> None:
        result = evaluate_darkharness_packet_policy(
            pilot_scope=_pilot_scope(),
            run_export=_run_export(final_recommendation="execute", approvals=[{"event_id": "evt_approval"}]),
            action_records=[_action_record("possible")],
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.violations, [])
        self.assertTrue(result.checks["production_action_has_operator_approval"])

    def test_policy_blocks_allowed_production_action_without_operator_approval(self) -> None:
        result = evaluate_darkharness_packet_policy(
            pilot_scope=_pilot_scope(),
            run_export=_run_export(final_recommendation="execute", approvals=[]),
            action_records=[_action_record("direct")],
        )

        self.assertFalse(result.allowed)
        self.assertIn("production_action_has_operator_approval", result.violations)

    def test_policy_allows_denied_production_action_without_operator_approval(self) -> None:
        result = evaluate_darkharness_packet_policy(
            pilot_scope=_pilot_scope(),
            run_export=_run_export(
                final_recommendation="reject",
                blocking_reasons=["production-impacting action requires operator approval"],
                approvals=[],
            ),
            action_records=[_action_record("direct")],
        )

        self.assertTrue(result.allowed)
        self.assertTrue(result.checks["production_action_has_operator_approval"])

    def test_policy_reports_boundary_violations(self) -> None:
        pilot_scope = _pilot_scope()
        pilot_scope["data_boundary"]["raw_reservoir_egress"] = "approved_exception"
        pilot_scope["data_boundary"]["external_model_calls"] = "allow"
        pilot_scope["authority"]["production_actions_approval_required"] = False

        result = evaluate_darkharness_packet_policy(
            pilot_scope=pilot_scope,
            run_export=_run_export(final_recommendation="reject", approvals=[]),
            action_records=[_action_record("none")],
        )

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.violations,
            [
                "approval_required",
                "raw_reservoir_egress_denied",
                "external_model_calls_denied_by_default",
            ],
        )


def _pilot_scope() -> dict:
    return copy.deepcopy(load_fixture("perennial", "allowed_action.json")["contracts"]["pilot_scope"])


def _run_export(
    *,
    final_recommendation: str,
    approvals: list[dict],
    blocking_reasons: list[str] | None = None,
) -> dict:
    return {
        "evaluation_record": {
            "final_recommendation": final_recommendation,
            "blocking_reasons": blocking_reasons or [],
        },
        "approval_records": approvals,
    }


def _action_record(production_impact: str) -> dict:
    return {
        "action": {
            "production_impact": production_impact,
        },
    }


if __name__ == "__main__":
    unittest.main()
