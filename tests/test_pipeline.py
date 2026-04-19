from __future__ import annotations

import tempfile
import unittest

from services.evaluation.service import EvaluationService
from services.orchestrator.hermes_adapter import HermesCliAdapter
from services.orchestrator.service import OrchestratorService
from services.pipeline import FirstSlicePipeline
from services.trigger.service import TriggerService
from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig, load_fixture


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            evaluation_mode="native",
            orchestration_mode="native",
            state_directory=self.temp_dir.name,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_first_slice_happy_path(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        result = FirstSlicePipeline(config=self.config).run(signal)

        self.assertIsNotNone(result["trigger"])
        self.assertEqual(result["trigger"]["trigger_type"], "feature_flag_performance_regression")
        self.assertEqual(result["decision"]["decision_type"], "disable_flag")
        self.assertEqual(result["evaluation"]["final_recommendation"], "execute")
        self.assertEqual(result["execution"]["status"], "succeeded")
        self.assertEqual(result["feedback"]["outcome"], "successful")

    def test_trigger_rejects_low_sample_signal(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        signal["request_telemetry"]["sample_size"] = 499
        normalized_event = FirstSlicePipeline(config=self.config).ingest.normalize_signal(signal)
        trigger = TriggerService().detect(normalized_event)

        self.assertIsNone(trigger)

    def test_evaluation_routes_high_risk_decision_to_human_review(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        pipeline = FirstSlicePipeline(config=self.config)
        trigger = pipeline.trigger.detect(pipeline.ingest.normalize_signal(signal))
        self.assertIsNotNone(trigger)
        decision = Decision.from_dict(load_fixture("decisions", "high_risk_decision.json"))
        service = EvaluationService(config=self.config)
        evaluation = service.evaluate(trigger, decision)

        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.final_recommendation, "human_review")
        self.assertTrue(any("risk level is high" in reason for reason in evaluation.blocking_reasons))

    def test_orchestrator_reject_path_does_not_apply_action(self) -> None:
        decision = Decision.from_dict(load_fixture("decisions", "high_risk_decision.json"))
        evaluation = EvaluationResult(
            evaluation_id="eval_test",
            decision_id=decision.decision_id,
            passed=False,
            final_recommendation="human_review",
            stage_results={
                "schema_validation": {"passed": True},
                "policy_validation": {"passed": True},
                "promptfoo_quality": {"passed": False, "score": 0.42, "notes": ["human review required"]},
                "business_rules": {"passed": False, "notes": ["human review required"]},
                "execution_readiness": {"passed": False, "notes": ["human review required"]},
            },
            blocking_reasons=["manual review required"],
            review_route="human_review",
        )
        service = OrchestratorService(config=self.config)
        execution = service.execute(decision, evaluation)

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(execution.external_refs, {})

    def test_orchestrator_uses_hermes_cli_adapter_for_hermes_mode(self) -> None:
        config = RuntimeConfig(
            evaluation_mode="native",
            orchestration_mode="hermes",
            hermes_command="python3 -m services.orchestrator.hermes_bridge --hermes-command hermes",
            state_directory=self.temp_dir.name,
        )
        service = OrchestratorService(config=config)
        self.assertIsInstance(service.adapter, HermesCliAdapter)


if __name__ == "__main__":
    unittest.main()
