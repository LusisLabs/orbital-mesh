from __future__ import annotations

from copy import deepcopy

from services.decision.service import DecisionService
from services.evaluation.service import EvaluationService
from services.feedback.service import FeedbackService
from services.ingest.service import IngestService
from services.orchestrator.service import OrchestratorService
from services.trigger.service import TriggerService
from shared.mesh_runtime import RuntimeConfig, RuntimeStateStore


class MeshRuntimeEngine:
    def __init__(
        self,
        config: RuntimeConfig | None = None,
        state_store: RuntimeStateStore | None = None,
        ingest: IngestService | None = None,
        trigger: TriggerService | None = None,
        decision: DecisionService | None = None,
        evaluation: EvaluationService | None = None,
        orchestrator: OrchestratorService | None = None,
        feedback: FeedbackService | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.state_store = state_store or RuntimeStateStore(self.config.state_directory)
        self.ingest = ingest or IngestService()
        self.trigger = trigger or TriggerService()
        self.decision = decision or DecisionService()
        self.evaluation = evaluation or EvaluationService(config=self.config, state_store=self.state_store)
        self.orchestrator = orchestrator or OrchestratorService(config=self.config)
        self.feedback = feedback or FeedbackService()

    def run_sync(self, raw_signal: dict, scenario_name: str = "manual") -> dict:
        run_events: list[dict] = []

        def record_event(stage: str, event_type: str, payload: dict, **metadata: object) -> None:
            run_events.append(
                {
                    "stage": stage,
                    "event_type": event_type,
                    "payload": deepcopy(payload),
                    **metadata,
                }
            )

        normalized_event = self.ingest.normalize_signal(raw_signal)
        record_event(
            "ingesting",
            "normalized_event",
            normalized_event.to_dict(),
            artifact_key="normalized_event",
            status="recorded",
        )
        trigger = self.trigger.detect(normalized_event)
        if trigger is None:
            record_event(
                "no_trigger",
                "no_trigger",
                {"reason": "signal did not satisfy trigger thresholds"},
                status="completed",
            )
            result = {"normalized_event": normalized_event.to_dict(), "trigger": None, "run_events": run_events}
            run_record = self.state_store.record_loop_run(
                scenario_name=scenario_name,
                evaluation_mode=self.config.evaluation_mode,
                orchestration_mode=self.config.orchestration_mode,
                result=result,
            )
            result["run_metadata"] = run_record.__dict__
            return result

        decision = self.decision.decide(trigger)
        record_event(
            "trigger_ready",
            "trigger_ready",
            trigger.to_dict(),
            artifact_key="trigger",
            status="recorded",
        )
        record_event(
            "decision_ready",
            "decision_ready",
            decision.to_dict(),
            artifact_key="decision",
            status="recorded",
        )
        evaluation = self.evaluation.evaluate(trigger, decision)
        record_event(
            "evaluation_ready",
            "evaluation_ready",
            evaluation.to_dict(),
            artifact_key="evaluation",
            integration_name=self.config.evaluation_mode if self.config.evaluation_mode != "native" else None,
            status=evaluation.final_recommendation,
        )
        promptfoo_artifact = evaluation.stage_results.get("promptfoo_quality", {}).get("artifacts")
        if promptfoo_artifact:
            record_event(
                "evaluation_ready",
                "integration_artifact_recorded",
                promptfoo_artifact,
                artifact_key="promptfoo_artifact",
                integration_name="promptfoo",
                status="recorded",
            )
        execution = self.orchestrator.execute(decision, evaluation)
        record_event(
            "executing",
            "execution_recorded",
            execution.to_dict(),
            artifact_key="execution",
            integration_name=self.config.orchestration_mode if self.config.orchestration_mode != "native" else None,
            status=execution.status,
        )
        goose_review = execution.external_refs.get("goose_review") if isinstance(execution.external_refs, dict) else None
        if goose_review:
            record_event(
                "executing",
                "integration_artifact_recorded",
                goose_review,
                artifact_key="goose_review",
                integration_name="goose",
                status="recorded",
            )
        feedback = self.feedback.record(trigger, decision, execution, normalized_event)
        record_event(
            "feedback_ready",
            "feedback_recorded",
            feedback.to_dict(),
            artifact_key="feedback",
            status=feedback.outcome,
        )
        result = {
            "normalized_event": normalized_event.to_dict(),
            "trigger": trigger.to_dict(),
            "decision": decision.to_dict(),
            "evaluation": evaluation.to_dict(),
            "execution": execution.to_dict(),
            "feedback": feedback.to_dict(),
            "run_events": run_events,
        }
        run_record = self.state_store.record_loop_run(
            scenario_name=scenario_name,
            evaluation_mode=self.config.evaluation_mode,
            orchestration_mode=self.config.orchestration_mode,
            result=result,
        )
        result["run_metadata"] = run_record.__dict__
        return result

