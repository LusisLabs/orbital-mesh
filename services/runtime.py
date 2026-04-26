from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from services.decision.llm_fallback import LlmActionProposer
from services.decision.service import DecisionService
from services.evaluation.service import EvaluationService
from services.evidence import EvidenceService
from services.feedback.service import FeedbackService
from services.ingest.service import IngestService
from services.orchestrator.service import OrchestratorService
from services.scenario_analysis.service import ScenarioAnalysisService
from services.trigger.service import TriggerService
from shared.mesh_runtime import RuntimeConfig, RuntimeStateStore
from shared.mesh_runtime.active_memory import ActiveMemoryStore
from shared.mesh_runtime.run_events import HYPOTHESIS_RANKED

if TYPE_CHECKING:
    from shared.mesh_runtime.contracts import Decision
    from shared.mesh_runtime.alert_store import AlertStore
    from shared.mesh_runtime.context_store import ContextStore
    from shared.mesh_runtime.infra_graph import InfraGraph
    from shared.mesh_runtime.learning import LearningStore


class MeshRuntimeEngine:
    def __init__(
        self,
        config: RuntimeConfig | None = None,
        state_store: RuntimeStateStore | None = None,
        learning_store: LearningStore | None = None,
        context_store: ContextStore | None = None,
        infra_graph: InfraGraph | None = None,
        alert_store: AlertStore | None = None,
        ingest: IngestService | None = None,
        trigger: TriggerService | None = None,
        evidence: EvidenceService | None = None,
        decision: DecisionService | None = None,
        evaluation: EvaluationService | None = None,
        orchestrator: OrchestratorService | None = None,
        feedback: FeedbackService | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.state_store = state_store or RuntimeStateStore(self.config.state_directory)
        self.learning_store = learning_store
        self.context_store = context_store
        self.ingest = ingest or IngestService(learning_store=learning_store)
        self.trigger = trigger or TriggerService()
        self.evidence = evidence or EvidenceService()
        escalation_reasoner = None
        if self.config.llm_escalation_enabled and (learning_store or context_store):
            from services.decision.llm_reasoning import EscalationReasoner
            escalation_reasoner = EscalationReasoner(
                config=self.config,
                context_store=context_store,
                learning_store=learning_store,
            )
        # The hypothesis engine is always wired now. Its k8s predicates
        # gracefully return ``unknown`` when the relevant store is None,
        # and its Reth predicates read the evidence pack rather than any
        # store — so there's no benefit to gating construction on
        # store presence. Construction itself is cheap (no I/O).
        from services.decision.hypothesis_engine import HypothesisEngine
        hypothesis_engine = HypothesisEngine(
            infra_graph=infra_graph,
            alert_store=alert_store,
            context_store=context_store,
        )
        # Layer 3: construct the LLM decision proposer only when enabled. Cheap
        # object (no subprocess until propose() fires) so we build it lazily
        # through the config gate and pass it into DecisionService alongside
        # master's escalation_reasoner and hypothesis_engine.
        llm_proposer = LlmActionProposer(self.config) if self.config.llm_decision_fallback_enabled else None
        # Layer 5: OpenAI-compatible LLM observer. Lazy: built only when
        # MESH_OBSERVER_ENABLED + a base_url + api_key + model are set.
        # Disabled-by-default keeps the deterministic-only path the floor
        # for everyone who hasn't opted in.
        llm_observer = None
        if self.config.observer_enabled:
            from services.observer import LlmObserver, ObserverConfig
            llm_observer = LlmObserver(ObserverConfig(
                enabled=True,
                base_url=self.config.observer_base_url,
                api_key=self.config.observer_api_key,
                model=self.config.observer_model,
                timeout_seconds=self.config.observer_timeout_seconds,
                max_tokens=self.config.observer_max_tokens,
                provider=self.config.observer_provider,
            ))
        self.decision = decision or DecisionService(
            learning_store=learning_store,
            escalation_reasoner=escalation_reasoner,
            hypothesis_engine=hypothesis_engine,
            llm_proposer=llm_proposer,
            llm_observer=llm_observer,
        )
        self.evaluation = evaluation or EvaluationService(config=self.config, state_store=self.state_store)
        self.orchestrator = orchestrator or OrchestratorService(config=self.config)
        self.feedback = feedback or FeedbackService()
        self.scenario_analysis = ScenarioAnalysisService(
            state_store=None,
            learning_store=learning_store,
            context_store=context_store,
            active_memory=ActiveMemoryStore(self.config.state_directory),
        )

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

        record_event(
            "trigger_ready",
            "trigger_ready",
            trigger.to_dict(),
            artifact_key="trigger",
            status="recorded",
        )

        evidence_pack = self.evidence.assemble(trigger=trigger, signal_payload=raw_signal)
        record_event(
            "evidence_pack_ready",
            "evidence_pack_ready",
            evidence_pack.to_dict(),
            artifact_key="evidence_pack",
            status="recorded",
        )

        scenario_analysis, memory_compaction = self.scenario_analysis.analyze(trigger)
        record_event(
            "scenario_analysis_ready",
            "scenario_analysis_ready",
            scenario_analysis.to_dict(),
            artifact_key="scenario_analysis",
            status="recorded",
        )
        if memory_compaction is not None:
            record_event(
                "scenario_analysis_ready",
                "memory_compaction_recorded",
                memory_compaction.to_dict(),
                artifact_key="memory_compaction",
                status="recorded",
            )
        decision = self.decision.decide(
            trigger,
            scenario_analysis=scenario_analysis,
            evidence_pack=evidence_pack.to_dict(),
        )
        ranked_hypotheses = _ranked_hypotheses_from_decision(decision)
        if ranked_hypotheses:
            record_event(
                "decision_ready",
                HYPOTHESIS_RANKED,
                {
                    "trigger_id": trigger.trigger_id,
                    "top_hypothesis": deepcopy(ranked_hypotheses[0]),
                    "ranked_hypotheses": deepcopy(ranked_hypotheses),
                },
                artifact_key="ranked_hypotheses",
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
        review_artifact = _execution_review_artifact(execution)
        if review_artifact:
            artifact_key, integration_name, payload = review_artifact
            record_event(
                "executing",
                "integration_artifact_recorded",
                payload,
                artifact_key=artifact_key,
                integration_name=integration_name,
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
            "scenario_analysis": scenario_analysis.to_dict(),
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


def _execution_review_artifact(execution) -> tuple[str, str, dict] | None:
    if not isinstance(execution.external_refs, dict):
        return None
    for artifact_key, integration_name in (("hermes_review", "hermes"), ("goose_review", "goose")):
        payload = execution.external_refs.get(artifact_key)
        if isinstance(payload, dict):
            return artifact_key, integration_name, payload
    return None


def _ranked_hypotheses_from_decision(decision: "Decision") -> list[dict]:
    reasoning = decision.reasoning if isinstance(decision.reasoning, dict) else {}
    ranked = reasoning.get("ranked_hypotheses")
    if isinstance(ranked, list) and ranked:
        return [dict(item) for item in ranked if isinstance(item, dict)]
    evidence_pack = reasoning.get("evidence_pack")
    if isinstance(evidence_pack, dict):
        hypotheses = evidence_pack.get("hypotheses")
        if isinstance(hypotheses, list) and hypotheses:
            return [dict(item) for item in hypotheses if isinstance(item, dict)]
    return []
