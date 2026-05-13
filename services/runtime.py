from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from services.decision.llm_fallback import LlmActionProposer
from services.decision.service import DecisionService
from services.evaluation.service import EvaluationService
from services.evidence import EvidenceService
from services.evidence.runners import build_configured_probe_runner
from services.feedback.service import FeedbackService, KubernetesFeedbackObserver
from services.ingest.service import IngestService
from services.investigation import InvestigationService, RethInvestigationPlanner
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


def _register_root_diagnostic_packs(
    root_registry: object,
    config: RuntimeConfig,
    *,
    infra_graph: object | None = None,
) -> None:
    """Auto-register always-on diagnostic packs onto the engine root.

    Single entrypoint into ``services.investigation.tools`` —
    ``register_root_packs`` walks every always-on pack (Prometheus,
    AWS, kubectl, GitHub, Loki, Jaeger, Postgres, topology) and
    registers each one whose backing config/env signal is present.
    ``topology`` registers unconditionally when ``infra_graph`` is
    supplied — the graph may be empty per-run but the tools are
    always callable so the LLM sees the same surface every run.

    Failures inside any single pack are logged and swallowed: one
    misconfigured Prometheus URL must never keep the engine from
    starting. The registry simply stays empty for that domain and
    the planner never sees its tools.
    """
    from services.investigation.tools import register_root_packs

    register_root_packs(root_registry, config, infra_graph=infra_graph)  # type: ignore[arg-type]


def _overlay_root_registry(per_run_registry: object, root_registry: object | None) -> object:
    """Merge the engine's always-on root tools onto a per-run registry.

    Re-registers each root tool on the per-run instance using
    ``has`` to skip ones the per-run already shadowed (per-run wins
    on conflict — the LLM should see the freshest snapshot tools
    without losing access to root diagnostics that share a name).
    """
    if root_registry is None:
        return per_run_registry
    from services.investigation.harness import ToolRegistry as _ToolRegistry

    if not isinstance(root_registry, _ToolRegistry) or not isinstance(per_run_registry, _ToolRegistry):
        return per_run_registry
    for definition in root_registry.list_definitions():
        if per_run_registry.has(definition.domain, definition.name):
            continue
        entry = root_registry.get(definition.domain, definition.name)
        if entry is None:
            continue
        per_run_registry.register(definition, entry[1])
    return per_run_registry


def _auto_wire_investigation_harness(
    raw_signal: dict,
    trigger: object,
    config: RuntimeConfig | None = None,
    *,
    root_registry: object | None = None,
    infra_graph: object | None = None,
) -> tuple[object | None, object | None]:
    """Auto-wire harness for **every** trigger, not just CloudOpsBench.

    Mesh's agentic surface should fire on every production incident —
    otel metric regression, feature-flag perf, kubernetes deployment
    health, webhook alert, Reth degraded — not only on the
    ``cloudopsbench_snapshot`` benchmark marker. Three paths in
    priority order:

    1. **CloudOpsBench snapshot present** — register snapshot tools +
       ``CloudOpsRulePack``. Production benchmark path; preserves
       deterministic behavior when the LLM observer is unconfigured.
    2. **Reth node trigger** (``trigger_type == "reth_node_degraded"``) —
       register Reth tools from the audited signal payload + ``RethRulePack``.
       The peer-starvation rule pack runs deterministically; LLM
       overlay if observer is configured.
    3. **Generic** — any other trigger gets the harness when the LLM
       observer is configured AND root-registered tools exist.
       ``GenericRulePack`` carries no rules; the LLM is the only
       decider, choosing from every read-only tool in the registry
       (Prometheus, AWS, kubectl, GitHub, Loki, Jaeger, Postgres, MCP).
       Returns ``(None, None)`` when LLM is off OR root has no tools —
       the legacy deterministic investigation continues unchanged in
       that case so this never silently degrades existing deployments.

    The LLM never gets to call mutating tools — the critic enforces
    read-only at registration AND ``LlmProbeSelector`` filters to
    ``read_only`` definitions before the LLM ever sees the menu.
    """
    from services.investigation.harness.native_selector import LlmProbeSelector
    from services.investigation.harness.registry import ToolRegistry
    from services.investigation.llm_planner import build_llm_decision_provider

    decision_provider = build_llm_decision_provider(config) if config is not None else None
    trigger_type = str(getattr(trigger, "trigger_type", "") or "")

    # Path 1: CloudOpsBench snapshot — most-specific match wins.
    snapshot = raw_signal.get("cloudopsbench_snapshot") if isinstance(raw_signal, dict) else None
    if isinstance(snapshot, dict):
        from services.benchmark.cloudopsbench import CloudOpsSnapshotTools
        from services.investigation.tools import cloudops as cloudops_pack

        registry = ToolRegistry()
        # ``infra_graph`` is consulted by the service-routing analyzer
        # when the populator has covered the trigger namespace — saves
        # two snapshot calls per service and uses graph edges for the
        # ``Endpoints: <none>`` signal. Falls back to kubectl text
        # parsing cleanly when the graph is empty or ``None``.
        cloudops_pack.register(
            registry, CloudOpsSnapshotTools(snapshot), infra_graph=infra_graph
        )
        _overlay_root_registry(registry, root_registry)

        if decision_provider is not None:
            rule_pack = cloudops_pack.CloudOpsRulePack(trigger)
            llm_tool_definitions = registry.list_definitions(mutation_class="read_only")
            planner = LlmProbeSelector(
                rule_pack,
                tool_definitions=llm_tool_definitions,
                decision_provider=decision_provider,
                enabled=True,
            )
        else:
            planner = cloudops_pack.CloudOpsLoopPlanner(trigger)
        return registry, planner

    # Path 2: Reth degraded — domain-specific rule pack with the audited node payload.
    if trigger_type == "reth_node_degraded" and isinstance(raw_signal, dict):
        from services.investigation.tools import reth as reth_pack

        registry = ToolRegistry()
        reth_pack.register(registry, raw_signal)
        _overlay_root_registry(registry, root_registry)

        if decision_provider is not None:
            rule_pack = reth_pack.RethRulePack()
            llm_tool_definitions = registry.list_definitions(mutation_class="read_only")
            planner = LlmProbeSelector(
                rule_pack,
                tool_definitions=llm_tool_definitions,
                decision_provider=decision_provider,
                enabled=True,
            )
        else:
            planner = reth_pack.RethLoopPlanner()
        return registry, planner

    # Path 3: Generic — any trigger gets the harness when the LLM is
    # configured and the root has at least one tool. This is what
    # makes Mesh agentic on production triggers (otel regression,
    # feature flag perf, k8s alert, webhook) instead of only on
    # CloudOpsBench scenarios. Without an LLM there's no chooser, so
    # we fall through to the legacy deterministic path.
    if decision_provider is None:
        return None, None
    registry = ToolRegistry()
    _overlay_root_registry(registry, root_registry)
    if not registry.list_definitions(mutation_class="read_only"):
        # No diagnostic packs configured at root — nothing to invoke.
        # Returning (None, None) keeps the legacy deterministic
        # investigation as the safety floor for ops-light deployments.
        return None, None

    from services.investigation.harness.native_selector import GenericRulePack

    rule_pack = GenericRulePack()
    llm_tool_definitions = registry.list_definitions(mutation_class="read_only")
    planner = LlmProbeSelector(
        rule_pack,
        tool_definitions=llm_tool_definitions,
        decision_provider=decision_provider,
        enabled=True,
    )
    return registry, planner


def _bind_profile_strategies(signal_profiles: Any, *, evidence_service: EvidenceService) -> None:
    profiles = list(signal_profiles.profiles())
    generic = signal_profiles.generic
    if generic is not None:
        profiles.append(generic)
    for profile in profiles:
        bind = getattr(profile.evidence_strategy, "bind", None)
        if callable(bind):
            bind(evidence_service)


def resolve_signal_profile(signal_profiles: Any, trigger: object, signal_payload: dict | None) -> Any:
    """Resolve the one signal profile every migrated stage should share."""
    trigger_type = str(getattr(trigger, "trigger_type", "") or "")
    if trigger_type:
        profile = signal_profiles.get_for_trigger(trigger_type)
        if profile is not None:
            return profile
    signal_type = signal_payload.get("signal_type") if isinstance(signal_payload, dict) else None
    if signal_type:
        profile = signal_profiles.get(signal_type)
        if profile is not None:
            return profile
    return signal_profiles.get_or_generic(signal_type)


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
        # Signal-profile registry — single source of truth for
        # per-signal-type pipeline behavior. Replaces the silent-skip
        # paths in the Reth-only investigation planner and RCA builder.
        # See docs/architecture/signal-profile-spec.md.
        from services.signal_profiles import build_default_registry

        self.signal_profiles = build_default_registry(self.config)
        self.trigger = trigger or TriggerService()
        self.evidence = evidence or EvidenceService(
            probe_runner=build_configured_probe_runner(self.config),
            signal_profiles=self.signal_profiles,
        )
        _bind_profile_strategies(self.signal_profiles, evidence_service=self.evidence)
        self.investigation = investigation or InvestigationService()
        # Legacy attribute kept so existing callers (control_plane,
        # tests) that reach for ``self.reth_planner`` still work; the
        # profile's ``RethProfileInvestigationPlanner`` wraps the same
        # instance internally.
        self.reth_planner = RethInvestigationPlanner(self.config)
        # InfraGraph is the typed view of K8s relationships (service →
        # pod → node → secret/configmap → ...). The control plane
        # historically owned the only instance; benchmark and
        # standalone runs left it empty. We default-construct one here
        # so every engine — production, benchmark, in-process test —
        # has a graph the topology tools can read and the populator
        # can write to per-run.
        from shared.mesh_runtime.infra_graph import InfraGraph as _InfraGraph

        self.infra_graph: _InfraGraph = infra_graph or _InfraGraph(self.config.state_directory)
        # Root tool registry. Always-on diagnostic packs (Prometheus,
        # AWS, kubectl, GitHub, Loki, Jaeger, Postgres, topology) auto-
        # register here at engine construction time, gated on config /
        # env presence (topology registers unconditionally because the
        # graph is always present). Per-run domain packs (CloudOps
        # snapshot, Reth live probes) are overlaid on top of a clone
        # in ``_auto_wire_investigation_harness``. Mesh deployments
        # without a given backend pay zero cost for it — the registry
        # stays empty for that domain and the planner never sees its
        # tools. See docs/investigation-harness.md for the full map.
        from services.investigation.harness import ToolRegistry as _ToolRegistry

        self.root_registry: _ToolRegistry = _ToolRegistry()
        _register_root_diagnostic_packs(
            self.root_registry, self.config, infra_graph=self.infra_graph,
        )
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
            infra_graph=self.infra_graph,
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

        canonical_signal_payload = (
            normalized_event.payload if isinstance(normalized_event.payload, dict) else raw_signal
        )

        # Populate the topology graph from this trigger's signal so
        # the always-on ``topology`` tool pack has data to query.
        # Idempotent and best-effort: failures are swallowed so a bad
        # snapshot never breaks the run, and signals without parseable
        # structure leave the graph empty (the topology tools return
        # empty results in that case, never crash).
        try:
            from services.investigation.topology_builder import populate as _populate_topology

            _populate_topology(
                self.infra_graph,
                snapshot=raw_signal.get("cloudopsbench_snapshot") if isinstance(raw_signal, dict) else None,
                namespace_hint=(
                    raw_signal.get("related_context", {}).get("cloudopsbench_namespace")
                    if isinstance(raw_signal, dict) and isinstance(raw_signal.get("related_context"), dict)
                    else None
                ),
            )
        except Exception:
            import logging
            logging.getLogger("mesh.runtime").exception(
                "topology populator failed (non-fatal)",
            )

        # Auto-wire the investigation harness when the caller didn't
        # supply one. Without this, every benchmark/test/ad-hoc call hit
        # the tool-loop's "registry+planner are None" short-circuit and
        # skipped investigation entirely (this was the source of
        # 0-of-521 tool-coverage on CloudOpsBench). See
        # ``_auto_wire_investigation_harness`` for the rationale.
        if registry is None and planner is None:
            auto_registry, auto_planner = _auto_wire_investigation_harness(
                raw_signal, trigger, self.config,
                root_registry=self.root_registry,
                infra_graph=self.infra_graph,
            )
            registry = auto_registry
            planner = auto_planner

        record_event(
            "trigger_ready",
            "trigger_ready",
            trigger.to_dict(),
            artifact_key="trigger",
            status="recorded",
        )

        # Investigation plan: dispatched through the profile registry
        # so every signal type produces a plan artifact (invariant 1
        # — no silent skips). Reth gets its specialised multi-probe
        # plan; K8s/OTel/feature-flag/webhook/generic get a
        # harness-driven empty-but-audited plan that signals "the
        # investigation harness owns probe selection for this run."
        signal_profile = resolve_signal_profile(
            self.signal_profiles,
            trigger,
            canonical_signal_payload if isinstance(canonical_signal_payload, dict) else None,
        )
        investigation_plan = signal_profile.investigation_planner.plan(
            trigger=trigger, signal_payload=canonical_signal_payload
        )
        record_event(
            "evidence_pack_ready",
            "integration_artifact_recorded",
            investigation_plan.to_dict(),
            artifact_key="investigation_plan",
            integration_name=f"{signal_profile.signal_source}_planner",
            status="recorded",
        )

        evidence_pack = self.evidence.assemble(
            trigger=trigger,
            signal_payload=canonical_signal_payload,
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
        # RCA report: dispatched through the profile so every signal
        # type emits a report (invariant 1). Reth still uses its
        # specialised RCA builder; K8s/OTel/feature-flag/webhook/
        # generic profiles synthesise from the investigation harness
        # output via ``HarnessDrivenRcaBuilder``.
        rca_report = signal_profile.rca_builder.build(
            trigger=trigger,
            decision=decision,
            evidence_pack=evidence_pack.to_dict(),
        )
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
            integration_name=f"{signal_profile.signal_source}_rca",
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
