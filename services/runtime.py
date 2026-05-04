from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from services.decision.llm_fallback import LlmActionProposer
from services.decision.service import DecisionService
from services.evaluation.service import EvaluationService
from services.evidence import EvidenceService
from services.evidence.runners import build_configured_probe_runner
from services.feedback.service import FeedbackService, KubernetesFeedbackObserver
from services.ingest.service import IngestService
from services.investigation import InvestigationService, RethInvestigationPlanner, build_rca_report
from services.orchestrator.service import OrchestratorService
from services.scenario_analysis.service import ScenarioAnalysisService
from services.signal_history import SignalHistoryStore
from services.trigger.service import TriggerService
from shared.mesh_runtime import RuntimeConfig, RuntimeStateStore
from shared.mesh_runtime.active_memory import ActiveMemoryStore
from shared.mesh_runtime.run_events import HYPOTHESIS_RANKED
from shared.mesh_runtime.otel import PrometheusClient

if TYPE_CHECKING:
    from shared.mesh_runtime.contracts import Decision
    from shared.mesh_runtime.alert_store import AlertStore
    from shared.mesh_runtime.context_store import ContextStore
    from shared.mesh_runtime.infra_graph import InfraGraph
    from shared.mesh_runtime.learning import LearningStore


def _build_feedback_observer(config: RuntimeConfig):
    if not (config.feedback_prometheus_enabled and config.prometheus_url):
        return None
    from services.feedback.otel_observer import PrometheusFeedbackObserver

    return PrometheusFeedbackObserver(
        client=PrometheusClient(
            config.prometheus_url,
            timeout_seconds=config.prometheus_query_timeout_seconds,
        ),
        latency_query_template=config.feedback_prometheus_latency_query,
        error_rate_query_template=config.feedback_prometheus_error_rate_query,
    )


def _build_kubernetes_feedback_observer(config: RuntimeConfig) -> KubernetesFeedbackObserver | None:
    if not config.kubernetes_live_execution_enabled:
        return None
    return KubernetesFeedbackObserver(kubectl_command=config.kubectl_command)


def _requires_live_feedback(config: RuntimeConfig) -> bool:
    return config.live_feedback_required or config.readiness_profile in {"pilot", "expansion"}


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
        investigation: InvestigationService | None = None,
        decision: DecisionService | None = None,
        evaluation: EvaluationService | None = None,
        orchestrator: OrchestratorService | None = None,
        feedback: FeedbackService | None = None,
        signal_history: SignalHistoryStore | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.state_store = state_store or RuntimeStateStore(self.config.state_directory)
        self.learning_store = learning_store
        self.context_store = context_store
        # SignalHistoryStore — per-target temporal memory shared across
        # ingest (write path) and decision (read path). Constructed once
        # so both services key off the same target ids and the same
        # in-memory ring buffers. Hydrating from disk gives a Mesh
        # restart a few minutes of warm context instead of starting
        # cold; failure to hydrate is best-effort and never blocks
        # startup.
        self.signal_history = signal_history or SignalHistoryStore(
            state_directory=self.config.state_directory,
        )
        try:
            hydrated = self.signal_history.hydrate_from_disk()
            if hydrated:
                import logging
                logging.getLogger("mesh.runtime").info(
                    "signal_history: hydrated %d records from disk", hydrated,
                )
        except Exception:
            import logging
            logging.getLogger("mesh.runtime").exception(
                "signal_history: hydrate failed (non-fatal); starting cold",
            )
        self.ingest = ingest or IngestService(
            learning_store=learning_store,
            signal_history=self.signal_history,
        )
        self.trigger = trigger or TriggerService()
        self.evidence = evidence or EvidenceService(probe_runner=build_configured_probe_runner(self.config))
        self.investigation = investigation or InvestigationService()
        self.reth_planner = RethInvestigationPlanner(self.config)
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
            from services.observer import LlmObserver, MultiLlmObserver, ObserverConfig
            primary_observer = LlmObserver(ObserverConfig(
                enabled=True,
                base_url=self.config.observer_base_url,
                api_key=self.config.observer_api_key,
                model=self.config.observer_model,
                timeout_seconds=self.config.observer_timeout_seconds,
                max_tokens=self.config.observer_max_tokens,
                provider=self.config.observer_provider,
                prompt_cache_enabled=self.config.observer_prompt_cache_enabled,
                prompt_cache_mode=self.config.observer_prompt_cache_mode,
                prompt_cache_ttl=self.config.observer_prompt_cache_ttl,
            ))
            secondary_observer = None
            if self.config.observer_secondary_model:
                secondary_observer = LlmObserver(ObserverConfig(
                    enabled=True,
                    base_url=self.config.observer_secondary_base_url or self.config.observer_base_url,
                    api_key=self.config.observer_secondary_api_key or self.config.observer_api_key,
                    model=self.config.observer_secondary_model,
                    timeout_seconds=self.config.observer_timeout_seconds,
                    max_tokens=self.config.observer_max_tokens,
                    provider=self.config.observer_secondary_provider or self.config.observer_provider,
                    prompt_cache_enabled=self.config.observer_prompt_cache_enabled,
                    prompt_cache_mode=self.config.observer_prompt_cache_mode,
                    prompt_cache_ttl=self.config.observer_prompt_cache_ttl,
                ))
            llm_observer = MultiLlmObserver(primary_observer, secondary_observer)
        self.decision = decision or DecisionService(
            learning_store=learning_store,
            escalation_reasoner=escalation_reasoner,
            hypothesis_engine=hypothesis_engine,
            llm_proposer=llm_proposer,
            llm_observer=llm_observer,
            signal_history=self.signal_history,
        )
        self.evaluation = evaluation or EvaluationService(config=self.config, state_store=self.state_store)
        self.orchestrator = orchestrator or OrchestratorService(config=self.config)
        self.feedback = feedback or FeedbackService(
            observer=_build_feedback_observer(self.config),
            kubernetes_observer=_build_kubernetes_feedback_observer(self.config),
            require_live_observations=_requires_live_feedback(self.config),
        )
        self.scenario_analysis = ScenarioAnalysisService(
            state_store=None,
            learning_store=learning_store,
            context_store=context_store,
            active_memory=ActiveMemoryStore(self.config.state_directory),
        )

    def run_sync(
        self,
        raw_signal: dict,
        scenario_name: str = "manual",
        *,
        tool_provider: object | None = None,
        registry: object | None = None,
        planner: object | None = None,
    ) -> dict:
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

        investigation_plan = self.reth_planner.plan(trigger=trigger, signal_payload=raw_signal)
        if investigation_plan is not None:
            record_event(
                "evidence_pack_ready",
                "integration_artifact_recorded",
                investigation_plan.to_dict(),
                artifact_key="investigation_plan",
                integration_name="reth_planner",
                status="recorded",
            )

        evidence_pack = self.evidence.assemble(
            trigger=trigger,
            signal_payload=raw_signal,
            investigation_plan=investigation_plan.to_dict() if investigation_plan is not None else None,
        )
        record_event(
            "evidence_pack_ready",
            "evidence_pack_ready",
            evidence_pack.to_dict(),
            artifact_key="evidence_pack",
            status="recorded",
        )

        try:
            investigation_report = self.investigation.investigate(
                trigger=trigger,
                evidence_pack=evidence_pack.to_dict(),
                tool_provider=tool_provider,
                registry=registry,
                planner=planner,
            )
            investigation_status = "recorded"
        except Exception as exc:
            investigation_report = self.investigation.failure_report(trigger=trigger, error=str(exc))
            investigation_status = "failed"
        record_event(
            "investigation_ready",
            "investigation_ready",
            investigation_report.to_dict(),
            artifact_key="investigation_report",
            status=investigation_status,
        )

        scenario_analysis, memory_compaction = self.scenario_analysis.analyze(
            trigger,
            investigation_report=investigation_report.to_dict(),
        )
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
            investigation_report=investigation_report.to_dict(),
        )
        rca_report = build_rca_report(
            trigger=trigger,
            decision=decision,
            evidence_pack=evidence_pack.to_dict(),
        )
        if rca_report is not None:
            decision.reasoning.setdefault("evidence_pack", {})["rca_report"] = {
                "report_id": rca_report.report_id,
                "likely_cause": rca_report.likely_cause,
                "confidence": rca_report.confidence,
                "recommended_next_step": rca_report.recommended_next_step,
            }
            record_event(
                "decision_ready",
                "integration_artifact_recorded",
                rca_report.to_dict(),
                artifact_key="rca_report",
                integration_name="reth_rca",
                status="recorded",
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
        initial_trace_bundle = self.evaluation.evaluate_trace(
            trigger=trigger,
            decision=decision,
            evaluation=evaluation.to_dict(),
            run_events=run_events,
            artifacts={
                "trigger": trigger.to_dict(),
                "evidence_pack": evidence_pack.to_dict(),
                "scenario_analysis": scenario_analysis.to_dict(),
                "decision": decision.to_dict(),
                "evaluation": evaluation.to_dict(),
            },
        )
        for artifact_key in ("task_trace", "trajectory_score", "verifier_output", "phoenix_spans"):
            record_event(
                "evaluation_ready",
                "integration_artifact_recorded",
                initial_trace_bundle[artifact_key],
                artifact_key=artifact_key,
                integration_name="mesh_trajectory",
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
        final_trace_bundle = self.evaluation.evaluate_trace(
            trigger=trigger,
            decision=decision,
            evaluation=evaluation.to_dict(),
            execution=execution.to_dict(),
            feedback=feedback.to_dict(),
            run_events=run_events,
            artifacts={
                "trigger": trigger.to_dict(),
                "evidence_pack": evidence_pack.to_dict(),
                "scenario_analysis": scenario_analysis.to_dict(),
                "decision": decision.to_dict(),
                "evaluation": evaluation.to_dict(),
                "execution": execution.to_dict(),
                "feedback": feedback.to_dict(),
            },
        )
        for artifact_key in ("task_trace", "trajectory_score", "verifier_output", "phoenix_spans"):
            record_event(
                "feedback_ready",
                "integration_artifact_recorded",
                final_trace_bundle[artifact_key],
                artifact_key=artifact_key,
                integration_name="mesh_trajectory",
                status="recorded",
            )
        result = {
            "normalized_event": normalized_event.to_dict(),
            "trigger": trigger.to_dict(),
            "scenario_analysis": scenario_analysis.to_dict(),
            "investigation_plan": investigation_plan.to_dict() if investigation_plan is not None else None,
            "investigation_report": investigation_report.to_dict(),
            "rca_report": rca_report.to_dict() if rca_report is not None else None,
            "decision": decision.to_dict(),
            "evaluation": evaluation.to_dict(),
            "execution": execution.to_dict(),
            "feedback": feedback.to_dict(),
            "task_trace": final_trace_bundle["task_trace"],
            "trajectory_score": final_trace_bundle["trajectory_score"],
            "verifier_output": final_trace_bundle["verifier_output"],
            "phoenix_spans": final_trace_bundle["phoenix_spans"],
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
