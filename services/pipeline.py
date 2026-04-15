from __future__ import annotations

from typing import TYPE_CHECKING

from shared.mesh_runtime import RuntimeConfig, RuntimeStateStore
from services.runtime import MeshRuntimeEngine

if TYPE_CHECKING:
    from services.decision.service import DecisionService
    from services.evaluation.service import EvaluationService
    from services.feedback.service import FeedbackService
    from services.ingest.service import IngestService
    from services.orchestrator.service import OrchestratorService
    from services.trigger.service import TriggerService


class FirstSlicePipeline:
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
        self.engine = MeshRuntimeEngine(
            config=self.config,
            state_store=self.state_store,
            ingest=ingest,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
            orchestrator=orchestrator,
            feedback=feedback,
        )
        self.ingest = self.engine.ingest
        self.trigger = self.engine.trigger
        self.decision = self.engine.decision
        self.evaluation = self.engine.evaluation
        self.orchestrator = self.engine.orchestrator
        self.feedback = self.engine.feedback

    def run(self, raw_signal: dict, scenario_name: str = "manual") -> dict:
        return self.engine.run_sync(raw_signal, scenario_name=scenario_name)
