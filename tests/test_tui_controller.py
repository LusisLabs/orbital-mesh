from __future__ import annotations

import tempfile
import unittest

from tui import MeshOperatorController


class TuiControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.controller = MeshOperatorController(state_directory=self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_run_scenario_records_recent_run_and_snapshot(self) -> None:
        result = self.controller.run_scenario("disable-flag", evaluation_mode="native", orchestration_mode="native")

        self.assertIn("run_metadata", result)
        runs = self.controller.list_recent_runs()
        self.assertEqual(len(runs), 1)
        snapshot = self.controller.load_run_snapshot(runs[0]["run_id"])
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["decision"]["decision_type"], "disable_flag")
        self.assertTrue(snapshot["run_metadata"]["trigger_emitted"])

    def test_duplicate_replay_scenario_triggers_duplicate_suppression(self) -> None:
        first = self.controller.run_scenario("duplicate-replay", evaluation_mode="native", orchestration_mode="native")
        second = self.controller.run_scenario("duplicate-replay", evaluation_mode="native", orchestration_mode="native")

        self.assertEqual(first["evaluation"]["final_recommendation"], "execute")
        self.assertEqual(second["evaluation"]["final_recommendation"], "reject")
        self.assertTrue(any("duplicate evaluation suppressed" in reason for reason in second["evaluation"]["blocking_reasons"]))
        self.assertEqual(len(self.controller.list_evaluations()), 1)

    def test_retry_recovery_scenario_succeeds(self) -> None:
        result = self.controller.run_scenario("retry-recovery", evaluation_mode="native", orchestration_mode="native")

        self.assertEqual(result["execution"]["status"], "succeeded")
        self.assertEqual(result["feedback"]["outcome"], "successful")
        self.assertEqual(result["execution"]["external_refs"]["flag_change_id"], "ffchg_retry_recovered")

    def test_retry_exhausted_scenario_opens_incident(self) -> None:
        result = self.controller.run_scenario("retry-exhausted", evaluation_mode="native", orchestration_mode="native")

        self.assertEqual(result["execution"]["status"], "failed")
        self.assertEqual(result["feedback"]["outcome"], "escalated")
        self.assertEqual(result["execution"]["failure"]["human_review_route"], "human_review")
        self.assertIn("incident_id", result["execution"]["external_refs"])

    def test_scenario_preview_is_side_effect_free(self) -> None:
        preview = self.controller.scenario_preview("approval-required")

        self.assertEqual(preview["customer_tier"], "strategic")
        self.assertEqual(self.controller.list_recent_runs(), [])
        self.assertEqual(self.controller.list_evaluations(), {})

        result = self.controller.run_scenario("disable-flag", evaluation_mode="native", orchestration_mode="native")

        self.assertIn("disable-flag_0001", result["trigger"]["trigger_id"])

    def test_dashboard_metrics_and_activity_summarize_recent_runs(self) -> None:
        self.controller.run_scenario("disable-flag", evaluation_mode="native", orchestration_mode="native")
        self.controller.run_scenario("retry-exhausted", evaluation_mode="native", orchestration_mode="native")

        metrics = self.controller.dashboard_metrics()
        activity = self.controller.scenario_activity()

        self.assertEqual(metrics["total_runs"], 2)
        self.assertEqual(metrics["successful_runs"], 1)
        self.assertEqual(metrics["escalated_runs"], 1)
        self.assertEqual(metrics["evaluation_records"], 2)
        self.assertEqual(activity["disable-flag"]["badge"], "stable")
        self.assertEqual(activity["retry-exhausted"]["badge"], "page")
        self.assertEqual(activity["retry-exhausted"]["runs"], 1)

    def test_clear_state_removes_runs_and_evaluations(self) -> None:
        self.controller.run_scenario("disable-flag", evaluation_mode="native", orchestration_mode="native")
        self.controller.clear_state()

        self.assertEqual(self.controller.list_recent_runs(), [])
        self.assertEqual(self.controller.list_evaluations(), {})


if __name__ == "__main__":
    unittest.main()
