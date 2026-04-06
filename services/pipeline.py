from __future__ import annotations

from services.diagnosis.service import DiagnosisService
from services.evaluation.service import EvaluationService
from services.feedback.service import FeedbackService
from services.ingest.service import IngestService
from services.orchestrator.service import OrchestratorService
from services.planner.service import PlannerService
from services.trigger.service import TriggerService


class FirstSlicePipeline:
    def __init__(self) -> None:
        self.ingest = IngestService()
        self.trigger = TriggerService()
        self.diagnosis = DiagnosisService()
        self.planner = PlannerService()
        self.evaluation = EvaluationService()
        self.orchestrator = OrchestratorService()
        self.feedback = FeedbackService()

    def run(self, raw_signal: dict) -> dict:
        normalized_event = self.ingest.normalize_signal(raw_signal)
        trigger = self.trigger.detect(normalized_event)
        if trigger is None:
            return {"normalized_event": normalized_event.to_dict(), "trigger": None}

        diagnosis = self.diagnosis.diagnose(trigger)
        plan = self.planner.plan(trigger, diagnosis)
        evaluation = self.evaluation.evaluate(plan)
        execution = self.orchestrator.execute(plan, evaluation)
        feedback = self.feedback.record(trigger, diagnosis, plan, execution)
        return {
            "normalized_event": normalized_event.to_dict(),
            "trigger": trigger.to_dict(),
            "diagnosis": diagnosis.to_dict(),
            "plan": plan.to_dict(),
            "evaluation": evaluation.to_dict(),
            "execution": execution.to_dict(),
            "feedback": feedback.to_dict(),
        }
