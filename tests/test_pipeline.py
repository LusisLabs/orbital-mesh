from __future__ import annotations

import unittest

from services.evaluation.service import EvaluationService
from services.orchestrator.service import OrchestratorService
from services.pipeline import FirstSlicePipeline
from shared.mesh_runtime import EvaluationResult, RemediationPlan, RuntimeConfig, load_fixture


class PipelineTests(unittest.TestCase):
    def test_first_slice_happy_path(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        result = FirstSlicePipeline().run(signal)

        self.assertIsNotNone(result["trigger"])
        self.assertEqual(result["trigger"]["trigger_type"], "performance_regression")
        self.assertEqual(result["evaluation"]["final_recommendation"], "execute_stepwise")
        self.assertEqual(result["execution"]["status"], "completed")
        self.assertEqual(result["feedback"]["outcome"], "successful")

    def test_evaluation_rejects_protected_high_risk_plan(self) -> None:
        plan = RemediationPlan.from_dict(load_fixture("plans", "high_risk_plan.json"))
        service = EvaluationService(config=RuntimeConfig(evaluation_mode="mock"))
        evaluation = service.evaluate(plan)

        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.final_recommendation, "human_review")
        self.assertTrue(any("protected scope" in reason for reason in evaluation.blocking_reasons))

    def test_orchestrator_reject_path_does_not_execute_steps(self) -> None:
        plan = RemediationPlan.from_dict(load_fixture("plans", "high_risk_plan.json"))
        evaluation = EvaluationResult(
            evaluation_id="eval_test",
            plan_id=plan.plan_id,
            passed=False,
            final_recommendation="human_review",
            plan_results={},
            step_results={},
            blocking_reasons=["manual review required"],
            review_route="human_review_queue",
        )
        service = OrchestratorService(config=RuntimeConfig(orchestration_mode="mock"))
        execution = service.execute(plan, evaluation)

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(execution.step_history, [])


if __name__ == "__main__":
    unittest.main()
