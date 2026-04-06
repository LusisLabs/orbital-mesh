from __future__ import annotations

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
        normalized_event = self.ingest.normalize_signal(raw_signal)
        trigger = self.trigger.detect(normalized_event)
        if trigger is None:
            result = {"normalized_event": normalized_event.to_dict(), "trigger": None}
            run_record = self.state_store.record_loop_run(
                scenario_name=scenario_name,
                evaluation_mode=self.config.evaluation_mode,
                orchestration_mode=self.config.orchestration_mode,
                result=result,
            )
            result["run_metadata"] = run_record.__dict__
            return result

        decision = self.decision.decide(trigger)
        evaluation = self.evaluation.evaluate(trigger, decision)
        execution = self.orchestrator.execute(decision, evaluation)
        feedback = self.feedback.record(trigger, decision, execution, normalized_event)
        result = {
            "normalized_event": normalized_event.to_dict(),
            "trigger": trigger.to_dict(),
            "decision": decision.to_dict(),
            "evaluation": evaluation.to_dict(),
            "execution": execution.to_dict(),
            "feedback": feedback.to_dict(),
        }
        run_record = self.state_store.record_loop_run(
            scenario_name=scenario_name,
            evaluation_mode=self.config.evaluation_mode,
            orchestration_mode=self.config.orchestration_mode,
            result=result,
        )
        result["run_metadata"] = run_record.__dict__
        return result

