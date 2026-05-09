from __future__ import annotations

import unittest

from shared.mesh_runtime.review_blockers import classify_blocking_reasons


class ReviewBlockerClassificationTests(unittest.TestCase):
    def test_autonomy_policy_approval_blocker_is_recoverable_when_review_reason_is_recoverable(self) -> None:
        result = classify_blocking_reasons(
            ["approval required before execution", "approval_required_before_execution"],
            scenario_review_reasons=["conflicting signals are present"],
        )

        self.assertTrue(result["can_auto_remediate"])
        self.assertEqual(result["terminal_blockers"], [])
        self.assertEqual(result["unclassified_blockers"], [])
        self.assertIn("approval_required_before_execution", result["recoverable_blockers"])

    def test_autonomy_policy_approval_blocker_remains_terminal_without_recoverable_review_reason(self) -> None:
        result = classify_blocking_reasons(
            ["approval_required_before_execution"],
            scenario_review_reasons=[],
        )

        self.assertFalse(result["can_auto_remediate"])
        self.assertIn("approval_required_before_execution", result["terminal_blockers"])


if __name__ == "__main__":
    unittest.main()
