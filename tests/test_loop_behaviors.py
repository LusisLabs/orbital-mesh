from __future__ import annotations

import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from services.actuators.repo_patch import RepoPatchAdapter
from services.evaluation.service import EvaluationService
from services.orchestrator.goose_adapter import GooseAdapter, GooseExecutionResult
from services.orchestrator.service import OrchestratorService
from services.pipeline import FirstSlicePipeline
from shared.mesh_runtime import EvaluationResult, RuntimeConfig, load_fixture


def base_signal() -> dict:
    return copy.deepcopy(load_fixture("signals", "search_latency_regression.json"))


def base_kubernetes_signal() -> dict:
    return copy.deepcopy(load_fixture("signals", "kubernetes_crashloop_patch.json"))


def approved_evaluation(decision_id: str) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=f"eval_{decision_id}",
        decision_id=decision_id,
        passed=True,
        final_recommendation="execute",
        stage_results={
            "schema_validation": {"passed": True},
            "policy_validation": {"passed": True, "notes": []},
            "promptfoo_quality": {"passed": True, "score": 0.91, "notes": []},
            "business_rules": {"passed": True, "notes": []},
            "execution_readiness": {"passed": True, "notes": []},
        },
        blocking_reasons=[],
        review_route=None,
    )


class RetryThenSuccessAdapter(GooseAdapter):
    def __init__(self) -> None:
        self.calls = 0
        self.incident_calls = 0

    def execute_decision(self, decision, idempotency_key: str) -> GooseExecutionResult:
        self.calls += 1
        if self.calls < 3:
            return GooseExecutionResult(
                status="failed",
                external_refs={},
                failure={"reason": "transient_api_failure"},
                retryable=True,
            )
        return GooseExecutionResult(
            status="succeeded",
            external_refs={"audit_log_id": f"audit_{decision.decision_id}", "flag_change_id": "ffchg_recovered"},
        )

    def open_execution_incident(self, decision, failure_reason: str) -> dict[str, str]:
        self.incident_calls += 1
        return {"incident_id": f"inc_{decision.decision_id}"}


class AlwaysTransientFailureAdapter(GooseAdapter):
    def __init__(self) -> None:
        self.calls = 0
        self.incident_calls = 0

    def execute_decision(self, decision, idempotency_key: str) -> GooseExecutionResult:
        self.calls += 1
        return GooseExecutionResult(
            status="failed",
            external_refs={"audit_log_id": f"audit_{decision.decision_id}"},
            failure={"reason": "transient_api_failure"},
            retryable=True,
        )

    def open_execution_incident(self, decision, failure_reason: str) -> dict[str, str]:
        self.incident_calls += 1
        return {"incident_id": f"inc_{decision.decision_id}"}


class RetryWindowExceededAdapter(GooseAdapter):
    def __init__(self) -> None:
        self.calls = 0
        self.incident_calls = 0

    def execute_decision(self, decision, idempotency_key: str) -> GooseExecutionResult:
        self.calls += 1
        return GooseExecutionResult(
            status="failed",
            external_refs={"audit_log_id": f"audit_{decision.decision_id}"},
            failure={"reason": "transient_api_failure", "retry_after_seconds": 31},
            retryable=True,
        )

    def open_execution_incident(self, decision, failure_reason: str) -> dict[str, str]:
        self.incident_calls += 1
        return {"incident_id": f"inc_{decision.decision_id}"}


class LoopBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            evaluation_mode="native",
            orchestration_mode="native",
            state_directory=self.temp_dir.name,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pipeline_no_action_path_records_audit_only(self) -> None:
        signal = base_signal()
        signal["request_telemetry"]["observed"]["p95_latency_ms"] = 530
        signal["request_telemetry"]["observed"]["error_rate"] = 0.018
        signal["request_telemetry"]["observed"]["timeout_rate"] = 0.01
        signal["related_context"]["flag_causality_confidence"] = 0.25
        signal["post_action_observations"]["10m"]["p95_latency_ms"] = 470
        signal["post_action_observations"]["10m"]["error_rate"] = 0.015
        signal["post_action_observations"]["30m"]["p95_latency_ms"] = 440
        signal["post_action_observations"]["30m"]["error_rate"] = 0.014

        result = FirstSlicePipeline(config=self.config).run(signal)

        self.assertEqual(result["decision"]["decision_type"], "no_action")
        self.assertEqual(result["evaluation"]["final_recommendation"], "execute")
        self.assertEqual(result["execution"]["applied_action"]["system"], "audit_log_sink")
        self.assertEqual(result["execution"]["applied_action"]["action"], "record_no_action")
        self.assertEqual(result["feedback"]["outcome"], "successful")

    def test_pipeline_reduce_rollout_path(self) -> None:
        signal = base_signal()
        signal["request_telemetry"]["observed"]["p95_latency_ms"] = 530
        signal["request_telemetry"]["observed"]["error_rate"] = 0.018
        signal["request_telemetry"]["observed"]["timeout_rate"] = 0.015
        signal["post_action_observations"]["10m"]["p95_latency_ms"] = 450
        signal["post_action_observations"]["10m"]["error_rate"] = 0.014
        signal["post_action_observations"]["30m"]["p95_latency_ms"] = 435
        signal["post_action_observations"]["30m"]["error_rate"] = 0.014

        result = FirstSlicePipeline(config=self.config).run(signal)

        self.assertEqual(result["decision"]["decision_type"], "reduce_rollout")
        self.assertEqual(result["decision"]["execution_plan"]["parameters"]["rollout_pct"], 10)
        self.assertEqual(result["evaluation"]["final_recommendation"], "execute")
        self.assertEqual(result["feedback"]["outcome"], "successful")

    def test_pipeline_approval_required_path_blocks_execution(self) -> None:
        signal = base_signal()
        signal["segment"]["customer_tier"] = "strategic"

        result = FirstSlicePipeline(config=self.config).run(signal)

        self.assertEqual(result["decision"]["autonomy_tier"], "approval_required")
        self.assertEqual(result["evaluation"]["final_recommendation"], "human_review")
        self.assertEqual(result["execution"]["status"], "rejected")
        self.assertEqual(result["feedback"]["outcome"], "escalated")

    def test_duplicate_evaluation_is_rejected(self) -> None:
        signal = base_signal()
        pipeline = FirstSlicePipeline(config=self.config)
        trigger = pipeline.trigger.detect(pipeline.ingest.normalize_signal(signal))
        self.assertIsNotNone(trigger)
        decision = pipeline.decision.decide(trigger)

        first = pipeline.evaluation.evaluate(trigger, decision)
        second = pipeline.evaluation.evaluate(trigger, decision)

        self.assertTrue(first.passed)
        self.assertFalse(second.passed)
        self.assertEqual(second.final_recommendation, "reject")
        self.assertTrue(any("duplicate evaluation suppressed" in reason for reason in second.blocking_reasons))

    def test_duplicate_evaluation_persists_across_service_restart(self) -> None:
        signal = base_signal()
        first_pipeline = FirstSlicePipeline(config=self.config)
        trigger = first_pipeline.trigger.detect(first_pipeline.ingest.normalize_signal(signal))
        self.assertIsNotNone(trigger)
        decision = first_pipeline.decision.decide(trigger)

        first_result = EvaluationService(config=self.config).evaluate(trigger, decision)
        second_result = EvaluationService(config=self.config).evaluate(trigger, decision)

        self.assertTrue(first_result.passed)
        self.assertFalse(second_result.passed)
        self.assertEqual(second_result.final_recommendation, "reject")

    def test_orchestrator_retries_transient_failure_and_succeeds(self) -> None:
        signal = base_signal()
        result = FirstSlicePipeline(config=self.config).run(signal)
        with tempfile.TemporaryDirectory() as state_dir:
            fresh_config = RuntimeConfig(
                evaluation_mode="native",
                orchestration_mode="native",
                state_directory=state_dir,
            )
            fresh_pipeline = FirstSlicePipeline(config=fresh_config)
            decision = fresh_pipeline.decision.decide(
                fresh_pipeline.trigger.detect(fresh_pipeline.ingest.normalize_signal(signal))
            )
            adapter = RetryThenSuccessAdapter()
            service = OrchestratorService(
                adapter=adapter,
                config=RuntimeConfig(
                    orchestration_mode="native",
                    max_transient_retries=2,
                    state_directory=state_dir,
                ),
            )

            execution = service.execute(decision, approved_evaluation(decision.decision_id))

            self.assertEqual(adapter.calls, 3)
            self.assertEqual(adapter.incident_calls, 0)
            self.assertEqual(execution.status, "succeeded")
            self.assertIsNone(execution.failure)
            self.assertEqual(execution.external_refs["flag_change_id"], "ffchg_recovered")
            self.assertEqual(result["execution"]["status"], "succeeded")

    def test_orchestrator_routes_repeated_transient_failure_to_incident(self) -> None:
        signal = base_signal()
        pipeline = FirstSlicePipeline(config=self.config)
        trigger = pipeline.trigger.detect(pipeline.ingest.normalize_signal(signal))
        self.assertIsNotNone(trigger)
        decision = pipeline.decision.decide(trigger)
        adapter = AlwaysTransientFailureAdapter()
        service = OrchestratorService(
            adapter=adapter,
            config=RuntimeConfig(
                orchestration_mode="native",
                max_transient_retries=2,
                state_directory=self.temp_dir.name,
            ),
        )

        execution = service.execute(decision, approved_evaluation(decision.decision_id))

        self.assertEqual(adapter.calls, 3)
        self.assertEqual(adapter.incident_calls, 1)
        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.failure["human_review_route"], "human_review")
        self.assertEqual(execution.failure["attempts"], 3)
        self.assertIn("incident_id", execution.external_refs)

    def test_orchestrator_uses_default_backoff_without_retry_hint(self) -> None:
        signal = base_signal()
        pipeline = FirstSlicePipeline(config=self.config)
        trigger = pipeline.trigger.detect(pipeline.ingest.normalize_signal(signal))
        self.assertIsNotNone(trigger)
        decision = pipeline.decision.decide(trigger)
        adapter = AlwaysTransientFailureAdapter()
        clock_state = {"now": 0.0}

        def fake_clock() -> float:
            return clock_state["now"]

        def fake_sleep(seconds: float) -> None:
            clock_state["now"] += seconds

        service = OrchestratorService(
            adapter=adapter,
            config=RuntimeConfig(
                orchestration_mode="native",
                max_transient_retries=2,
                state_directory=self.temp_dir.name,
            ),
            clock=fake_clock,
            sleeper=fake_sleep,
        )

        execution = service.execute(decision, approved_evaluation(decision.decision_id))

        self.assertEqual(adapter.calls, 3)
        self.assertEqual(clock_state["now"], 3.0)
        self.assertEqual(execution.failure["attempts"], 3)

    def test_orchestrator_respects_retry_window_budget(self) -> None:
        signal = base_signal()
        pipeline = FirstSlicePipeline(config=self.config)
        trigger = pipeline.trigger.detect(pipeline.ingest.normalize_signal(signal))
        self.assertIsNotNone(trigger)
        decision = pipeline.decision.decide(trigger)
        adapter = RetryWindowExceededAdapter()
        clock_state = {"now": 0.0}

        def fake_clock() -> float:
            return clock_state["now"]

        def fake_sleep(seconds: float) -> None:
            clock_state["now"] += seconds

        service = OrchestratorService(
            adapter=adapter,
            config=RuntimeConfig(
                orchestration_mode="native",
                max_transient_retries=2,
                max_retry_window_seconds=60,
                state_directory=self.temp_dir.name,
            ),
            clock=fake_clock,
            sleeper=fake_sleep,
        )

        execution = service.execute(decision, approved_evaluation(decision.decision_id))

        self.assertEqual(adapter.calls, 2)
        self.assertEqual(adapter.incident_calls, 1)
        self.assertEqual(clock_state["now"], 31.0)
        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.failure["attempts"], 2)
        self.assertIn("incident_id", execution.external_refs)

    def test_feedback_marks_flag_for_human_owned_remediation_after_recurrence(self) -> None:
        signal = base_signal()
        signal["related_context"]["regressions_last_7d"] = 3

        result = FirstSlicePipeline(config=self.config).run(signal)

        self.assertEqual(result["feedback"]["outcome"], "successful")
        self.assertEqual(result["feedback"]["recommended_follow_up"], "mark_flag_for_human_owned_remediation")

    def test_feedback_rolls_back_when_business_guardrail_breaks(self) -> None:
        signal = base_signal()
        signal["post_action_observations"]["30m"]["business_guardrail_breached"] = True

        result = FirstSlicePipeline(config=self.config).run(signal)

        self.assertEqual(result["feedback"]["outcome"], "rolled_back")
        self.assertEqual(result["feedback"]["recommended_follow_up"], "restore_prior_rollout_and_escalate")

    def test_cli_modes_execute_end_to_end(self) -> None:
        signal = base_signal()
        with tempfile.TemporaryDirectory() as state_dir:
            config = RuntimeConfig(
                evaluation_mode="promptfoo",
                orchestration_mode="goose",
                state_directory=state_dir,
                promptfoo_command=f"{sys.executable} -m services.evaluation.cli_gate",
                goose_command=f"{sys.executable} -m services.orchestrator.cli_executor",
            )
            result = FirstSlicePipeline(config=config).run(signal)

        self.assertEqual(result["evaluation"]["stage_results"]["promptfoo_quality"]["passed"], True)
        self.assertIn("artifacts", result["evaluation"]["stage_results"]["promptfoo_quality"])
        self.assertIn("assertion_results", result["evaluation"]["stage_results"]["promptfoo_quality"]["artifacts"])
        self.assertEqual(result["execution"]["status"], "succeeded")
        self.assertIn("audit_log_id", result["execution"]["external_refs"])
        self.assertTrue(result["execution"]["external_refs"]["goose_review"]["approved"])

    def test_runtime_records_typed_stage_events_and_integration_artifacts(self) -> None:
        signal = base_signal()
        with tempfile.TemporaryDirectory() as state_dir:
            config = RuntimeConfig(
                evaluation_mode="promptfoo",
                orchestration_mode="goose",
                state_directory=state_dir,
                promptfoo_command=f"{sys.executable} -m services.evaluation.cli_gate",
                goose_command=f"{sys.executable} -m services.orchestrator.cli_executor",
            )
            result = FirstSlicePipeline(config=config).run(signal)

        event_types = [event["event_type"] for event in result["run_events"]]
        self.assertIn("evaluation_ready", event_types)
        self.assertIn("execution_recorded", event_types)
        integration_events = [event for event in result["run_events"] if event.get("integration_name")]
        self.assertTrue(any(event["integration_name"] == "promptfoo" for event in integration_events))
        self.assertTrue(any(event["integration_name"] == "goose" for event in integration_events))
        self.assertGreater(result["run_metadata"]["stage_event_count"], 0)
        self.assertGreaterEqual(result["run_metadata"]["integration_artifact_count"], 2)

    def test_goose_cli_can_apply_bounded_code_patch(self) -> None:
        signal = base_signal()
        fixture_repo = Path(__file__).resolve().parents[1] / "fixtures" / "codebases" / "search_service"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "search_service"
            shutil.copytree(fixture_repo, repo_path)
            signal["related_context"].update(
                {
                    "code_remediation_candidate": True,
                    "repo_path": str(repo_path),
                    "suspected_file": "app/search.py",
                    "allowed_paths": ["app/search.py"],
                    "test_commands": ["python3 -m unittest discover -s tests"],
                    "patch_template": {
                        "target_file": "app/search.py",
                        "find": "PARSE_TIMEOUT_MS = 100",
                        "replace": "PARSE_TIMEOUT_MS = 80",
                    },
                }
            )
            config = RuntimeConfig(
                evaluation_mode="promptfoo",
                orchestration_mode="goose",
                state_directory=temp_dir,
                promptfoo_command=f"{sys.executable} -m services.evaluation.cli_gate",
                goose_command=f"{sys.executable} -m services.orchestrator.cli_executor",
            )

            result = FirstSlicePipeline(config=config).run(signal)

            self.assertEqual(result["decision"]["decision_type"], "investigate_and_patch")
            self.assertEqual(result["execution"]["status"], "succeeded")
            self.assertEqual(
                result["execution"]["applied_action"]["system"],
                "repo_patch_service",
            )
            patched_file = repo_path / "app" / "search.py"
            self.assertIn("PARSE_TIMEOUT_MS = 80", patched_file.read_text())
            test_results = result["execution"]["external_refs"]["test_results"]
            self.assertEqual(test_results[0]["returncode"], 0)
            self.assertEqual(result["feedback"]["outcome"], "successful")

    def test_repo_patch_accepts_absolute_target_inside_repo_scope(self) -> None:
        fixture_repo = Path(__file__).resolve().parents[1] / "fixtures" / "codebases" / "search_service"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "search_service"
            shutil.copytree(fixture_repo, repo_path)
            target_path = repo_path / "app" / "search.py"

            result = RepoPatchAdapter().execute_patch(
                {
                    "repo_path": str(repo_path),
                    "allowed_paths": ["app/search.py"],
                    "patch_template": {
                        "target_file": str(target_path),
                        "find": "PARSE_TIMEOUT_MS = 100",
                        "replace": "PARSE_TIMEOUT_MS = 80",
                    },
                    "test_commands": ["python3 -m unittest discover -s tests"],
                },
                "absolute_target_test",
            )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["external_refs"]["patched_files"], ["app/search.py"])

    def test_repo_patch_supports_shell_form_test_commands(self) -> None:
        fixture_repo = Path(__file__).resolve().parents[1] / "fixtures" / "codebases" / "search_service"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "search_service"
            shutil.copytree(fixture_repo, repo_path)

            result = RepoPatchAdapter().execute_patch(
                {
                    "repo_path": str(repo_path),
                    "allowed_paths": ["app/search.py"],
                    "patch_template": {
                        "target_file": "app/search.py",
                        "find": "PARSE_TIMEOUT_MS = 100",
                        "replace": "PARSE_TIMEOUT_MS = 80",
                    },
                    "test_commands": ["cd . && python3 -m unittest discover -s tests"],
                },
                "shell_test_command",
            )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["external_refs"]["test_results"][0]["returncode"], 0)

    def test_kubernetes_signal_can_drive_bounded_patch_flow(self) -> None:
        signal = base_kubernetes_signal()
        fixture_repo = Path(__file__).resolve().parents[1] / "fixtures" / "codebases" / "search_service"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "search_service"
            shutil.copytree(fixture_repo, repo_path)
            signal["related_context"]["repo_path"] = str(repo_path)
            config = RuntimeConfig(
                evaluation_mode="promptfoo",
                orchestration_mode="goose",
                state_directory=temp_dir,
                promptfoo_command=f"{sys.executable} -m services.evaluation.cli_gate",
                goose_command=f"{sys.executable} -m services.orchestrator.cli_executor",
            )

            result = FirstSlicePipeline(config=config).run(signal)

            self.assertEqual(result["trigger"]["trigger_type"], "kubernetes_deployment_unhealthy")
            self.assertEqual(result["decision"]["decision_type"], "investigate_and_patch")
            self.assertEqual(result["execution"]["status"], "succeeded")
            self.assertEqual(result["execution"]["applied_action"]["system"], "repo_patch_service")
            self.assertEqual(result["feedback"]["outcome"], "successful")
            self.assertIn("PARSE_TIMEOUT_MS = 80", (repo_path / "app" / "search.py").read_text())

    def test_kubernetes_image_pull_failure_prefers_rollback(self) -> None:
        signal = base_kubernetes_signal()
        signal["deployment"]["rollout_status"] = "failed"
        signal["logs"] = []
        signal["events"] = [
            {
                "reason": "ErrImagePull",
                "message": "Failed to pull image registry.local/semantic-search:42",
                "count": 4,
                "type": "Warning",
            }
        ]
        signal["related_context"]["code_remediation_candidate"] = False
        signal["related_context"].pop("repo_path", None)
        config = RuntimeConfig(
            evaluation_mode="native",
            orchestration_mode="native",
            state_directory=self.temp_dir.name,
        )

        result = FirstSlicePipeline(config=config).run(signal)

        self.assertEqual(result["decision"]["decision_type"], "rollback_deployment")
        self.assertEqual(result["execution"]["applied_action"]["system"], "kubernetes_service")
        self.assertEqual(result["execution"]["applied_action"]["action"], "rollback_deployment")

    def test_kubernetes_probe_failure_prefers_restart(self) -> None:
        signal = base_kubernetes_signal()
        signal["logs"] = []
        signal["events"] = [
            {
                "reason": "Unhealthy",
                "message": "Liveness probe failed: HTTP probe failed with statuscode: 503",
                "count": 5,
                "type": "Warning",
            }
        ]
        signal["pods"][0]["container_status"] = "Running"
        signal["pods"][0]["restarts"] = 1
        signal["related_context"]["code_remediation_candidate"] = False
        signal["related_context"].pop("repo_path", None)
        config = RuntimeConfig(
            evaluation_mode="native",
            orchestration_mode="native",
            state_directory=self.temp_dir.name,
        )

        result = FirstSlicePipeline(config=config).run(signal)

        self.assertEqual(result["decision"]["decision_type"], "restart_deployment")
        self.assertEqual(result["execution"]["applied_action"]["action"], "restart_deployment")


if __name__ == "__main__":
    unittest.main()
