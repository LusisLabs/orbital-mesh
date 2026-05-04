"""Read-only incident investigation before scenario analysis.

The investigation service has two modes:

1. **Deterministic** (default) — local probes against already-normalized
   Mesh artifacts. No I/O, no mutation. Used in production and golden
   benchmarks.
2. **Tool-driven** — a caller injects an ``InvestigationToolProvider``
   that exposes read-only diagnostic tools (e.g. CloudOps snapshot
   tools). The service then runs a bounded hypothesis loop: it picks a
   probe, observes output, ranks candidate root causes, and either calls
   another probe or stops. This is what powers benchmark-grade RCA
   without giving the agent any mutation surface.

Both modes return the same ``InvestigationReport`` contract; downstream
stages don't know or care which path produced it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal
from uuid import uuid4

from shared.mesh_runtime import (
    InvestigationPlan,
    InvestigationProbeResult,
    InvestigationReport,
    Trigger,
)

from .cloudops_tools import CLOUDOPS_DOMAIN, CLOUDOPS_TOOL_DEFINITIONS, CloudOpsRulePack
from .cloudops_ontology import RankedCause, rank_root_causes
from .harness import (
    InvestigationLoopState,
    LoopCritic,
    LoopPlanner,
    NativeProbeSelector,
    RawToolOutput,
    ToolRegistry,
    run_investigation_loop,
)
from .tool_provider import InvestigationToolProvider


ProbeFn = Callable[[Trigger, dict[str, Any], dict[str, Any]], tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]


class InvestigationService:
    """Build and run bounded read-only investigation probes.

    The service accepts already-normalized Mesh artifacts, runs local
    deterministic probes, and returns a contract-backed report. When a
    ``tool_provider`` is supplied to ``investigate``, the service also
    runs a bounded diagnostic-tool loop and produces ranked root-cause
    hypotheses from the observed snapshot text.
    """

    def __init__(
        self,
        *,
        max_probes: int = 4,
        max_total_latency_ms: int = 500,
        max_tool_probes: int = 6,
    ) -> None:
        self.max_probes = max_probes
        self.max_total_latency_ms = max_total_latency_ms
        self.max_tool_probes = max_tool_probes
        self._probe_fns: dict[str, ProbeFn] = {
            "evidence_sufficiency": _probe_evidence_sufficiency,
            "trigger_signature_scan": _probe_trigger_signature_scan,
            "memory_context_scan": _probe_memory_context,
            "topology_context_scan": _probe_topology_context,
        }

    def investigate(
        self,
        *,
        trigger: Trigger,
        evidence_pack: dict[str, Any] | None,
        memory_packet: dict[str, Any] | None = None,
        service_context: dict[str, Any] | None = None,
        topology: dict[str, Any] | None = None,
        recent_runs: list[dict[str, Any]] | None = None,
        tool_provider: InvestigationToolProvider | None = None,
        registry: ToolRegistry | None = None,
        planner: LoopPlanner | None = None,
    ) -> InvestigationReport:
        context = {
            "memory_packet": memory_packet or {},
            "service_context": service_context or {},
            "topology": topology or {},
            "recent_runs": recent_runs or [],
        }
        evidence = evidence_pack or {}
        plan = self._build_plan(
            trigger,
            context,
            tool_provider=tool_provider,
            registry=registry,
            planner=planner,
        )
        probe_results: list[InvestigationProbeResult] = []
        findings: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        root_cause_candidates: list[dict[str, Any]] = []
        tool_stop_reason: str | None = None
        loop_state: InvestigationLoopState | None = None

        deterministic_probes = [probe for probe in plan.probes if "provider" not in probe]
        for probe in deterministic_probes[: self.max_probes]:
            result = self._run_probe(probe, trigger, evidence, context)
            probe_results.append(result)
            findings.extend(result.findings)
            citations.extend(result.citations)

        if registry is not None and planner is not None:
            loop_state, harness_probes, harness_findings, harness_citations, harness_candidates = self._run_harness_loop(
                trigger, registry, planner
            )
            probe_results.extend(harness_probes)
            findings.extend(harness_findings)
            citations.extend(harness_citations)
            root_cause_candidates.extend(harness_candidates)
        elif tool_provider is not None:
            tool_results, tool_findings, tool_citations, tool_candidates, tool_stop_reason = self._run_tool_loop(
                trigger, tool_provider
            )
            probe_results.extend(tool_results)
            findings.extend(tool_findings)
            citations.extend(tool_citations)
            root_cause_candidates.extend(tool_candidates)

        uncertainty = _estimate_uncertainty(evidence, findings, context, root_cause_candidates)
        if _evidence_marked_insufficient(evidence):
            stop_reason = "evidence_insufficient_route_to_existing_safety_gates"
        elif loop_state is not None:
            stop_reason = f"harness_{loop_state.stop_reason or 'completed'}"
        elif tool_provider is not None:
            stop_reason = tool_stop_reason or "tool_probe_budget_exhausted"
        else:
            stop_reason = "deterministic_probe_budget_exhausted"
        report = InvestigationReport(
            report_id=f"inv_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=_now_iso(),
            plan=plan.to_dict(),
            probe_results=[item.to_dict() for item in probe_results],
            findings=findings,
            citations=_dedupe_citations(citations),
            uncertainty=uncertainty,
            stop_reason=stop_reason,
            recommended_next_step="continue_to_scenario_analysis",
            safety_notes=[
                "investigation probes are read-only",
                "investigation output is advisory; policy and evaluation remain authoritative",
                "no production mutation is reachable from this stage",
            ],
            root_cause_candidates=root_cause_candidates,
        )
        report.validate()
        return report

    def failure_report(self, *, trigger: Trigger, error: str) -> InvestigationReport:
        """Return a contract-valid report for a failed investigation stage."""
        now = _now_iso()
        plan = InvestigationPlan(
            plan_id=f"plan_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=now,
            objective=f"Investigation failed before probes could complete for {trigger.service}.",
            probe_budget={
                "max_probes": self.max_probes,
                "max_total_latency_ms": self.max_total_latency_ms,
                "mode": "deterministic_builtin",
            },
            probes=[],
        )
        plan.validate()
        report = InvestigationReport(
            report_id=f"inv_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=now,
            plan=plan.to_dict(),
            probe_results=[],
            findings=[
                {
                    "kind": "investigation_failed",
                    "summary": "Investigation failed; existing deterministic path should continue.",
                    "confidence": 0.0,
                    "details": {"error": error},
                }
            ],
            citations=[],
            uncertainty=0.95,
            stop_reason="investigation_failed_existing_path_continues",
            recommended_next_step="continue_to_scenario_analysis",
            safety_notes=[
                "investigation failure is non-fatal",
                "existing deterministic decision path remains authoritative",
            ],
            root_cause_candidates=[],
        )
        report.validate()
        return report

    def _run_harness_loop(
        self,
        trigger: Trigger,
        registry: ToolRegistry,
        planner: LoopPlanner,
    ) -> tuple[
        InvestigationLoopState,
        list[InvestigationProbeResult],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Drive the harness loop and project results into the report shape.

        Each ``ToolResult`` from the harness becomes one
        ``InvestigationProbeResult`` so existing scoring (which reads
        ``probe_results[*].name``) credits tool coverage. The loop's
        observed text feeds the ranked-cause ontology unchanged.
        """
        state = InvestigationLoopState(
            trigger_id=trigger.trigger_id,
            budget_remaining=float(self.max_tool_probes),
        )
        critic = LoopCritic(registry)
        run_investigation_loop(
            state=state,
            planner=planner,
            registry=registry,
            critic=critic,
            trigger_context={"trigger": trigger.to_dict()},
            max_iterations=self.max_tool_probes + 2,
        )
        probe_results, findings, citations, root_cause_candidates = self._project_loop_state(state)
        return state, probe_results, findings, citations, root_cause_candidates

    def _project_loop_state(
        self,
        state: InvestigationLoopState,
    ) -> tuple[
        list[InvestigationProbeResult],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        probe_results: list[InvestigationProbeResult] = []
        findings: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        observed_tool_text: list[tuple[str, str]] = []
        observed_text: list[str] = list(state.observed_text)
        for call, result in zip(state.tool_calls, state.tool_results):
            finding = {
                "kind": "diagnostic_observation",
                "summary": (
                    f"{result.tool_name}({_arg_summary(call.args)}) -> {result.output_summary[:200]}"
                    if result.output_summary
                    else f"{result.tool_name}({_arg_summary(call.args)}) returned no data"
                ),
                "confidence": 0.7 if result.valid else 0.2,
                "details": {
                    "tool_name": result.tool_name,
                    "domain": result.domain,
                    "args": call.args,
                    "output_text": result.output_summary,
                    "valid": result.valid,
                    "call_id": call.call_id,
                    "selection_reason": call.purpose,
                },
            }
            findings.append(finding)
            citations.extend(result.citations)
            if result.output_summary:
                observed_tool_text.append((result.tool_name, result.output_summary))
            harness_status = result.status if result.status in {"completed", "skipped", "failed"} else "completed"
            probe_results.append(
                InvestigationProbeResult(
                    probe_id=call.call_id,
                    name=result.tool_name,
                    status=harness_status,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
                    latency_ms=result.latency_ms,
                    summary=str(finding["summary"]),
                    findings=[finding],
                    citations=list(result.citations),
                    error=result.error,
                )
            )
        ranked = rank_root_causes(observed_text)
        root_cause_candidates: list[dict[str, Any]] = []
        if ranked:
            root_cause_candidates = _root_cause_candidates(ranked, observed_tool_text)
            state.ranked_hypotheses = root_cause_candidates
            findings.append(_ranked_finding(root_cause_candidates))
            for candidate in root_cause_candidates:
                citations.append(_citation("rca_ontology", str(candidate.get("root_cause"))))
        findings.append(_planner_telemetry_finding(state, root_cause_candidates))
        return probe_results, findings, citations, root_cause_candidates

    def _run_tool_loop(
        self,
        trigger: Trigger,
        tool_provider: InvestigationToolProvider,
    ) -> tuple[
        list[InvestigationProbeResult],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        str,
    ]:
        """Run provider-backed CloudOps probes through the native selector."""

        registry = _registry_for_tool_provider(tool_provider)
        selector = NativeProbeSelector(
            CloudOpsRulePack(trigger),
            tool_definitions=registry.list_definitions(domain=CLOUDOPS_DOMAIN, mutation_class="read_only"),
        )
        state = InvestigationLoopState(
            trigger_id=trigger.trigger_id,
            budget_remaining=float(self.max_tool_probes),
        )
        run_investigation_loop(
            state=state,
            planner=selector,
            registry=registry,
            critic=LoopCritic(registry),
            trigger_context={"trigger": trigger.to_dict()},
            max_iterations=self.max_tool_probes + 2,
        )
        results, findings, citations, root_cause_candidates = self._project_loop_state(state)
        stop_reason = _provider_stop_reason(state.stop_reason)
        return results, findings, citations, root_cause_candidates, stop_reason

    def _build_plan(
        self,
        trigger: Trigger,
        context: dict[str, Any],
        *,
        tool_provider: InvestigationToolProvider | None = None,
        registry: ToolRegistry | None = None,
        planner: LoopPlanner | None = None,
    ) -> InvestigationPlan:
        probes = [
            {
                "probe_id": "probe_evidence_sufficiency",
                "name": "evidence_sufficiency",
                "purpose": "Check whether the audited evidence pack is complete enough for downstream reasoning.",
                "read_only": True,
            },
            {
                "probe_id": "probe_trigger_signature_scan",
                "name": "trigger_signature_scan",
                "purpose": "Extract alert signatures, metric deltas, and risk hints from the trigger.",
                "read_only": True,
            },
        ]
        memory_packet = context.get("memory_packet") or {}
        if memory_packet.get("claims") or memory_packet.get("procedures") or context.get("recent_runs"):
            probes.append(
                {
                    "probe_id": "probe_memory_context",
                    "name": "memory_context_scan",
                    "purpose": "Summarize verified memory and recent runs for advisory context.",
                    "read_only": True,
                }
            )
        topology = context.get("topology") or {}
        if topology:
            probes.append(
                {
                    "probe_id": "probe_topology_context",
                    "name": "topology_context_scan",
                    "purpose": "Summarize available topology/dependency context.",
                    "read_only": True,
                }
            )
        if registry is not None and planner is not None:
            for definition in registry.list_definitions(
                domain=getattr(planner, "domain", None),
                mutation_class="read_only",
            ):
                probes.append(
                    {
                        "probe_id": f"probe_tool_{definition.name.lower()}",
                        "name": definition.name,
                        "purpose": definition.description,
                        "read_only": True,
                        "provider": definition.domain,
                    }
                )
        elif tool_provider is not None:
            for tool_name in tool_provider.available_tools():
                probes.append(
                    {
                        "probe_id": f"probe_tool_{tool_name.lower()}",
                        "name": tool_name,
                        "purpose": (
                            f"Read-only diagnostic tool {tool_name} via "
                            f"{tool_provider.name} provider; invoked by "
                            "hypothesis loop when relevant."
                        ),
                        "read_only": True,
                        "provider": tool_provider.name,
                    }
                )
        plan = InvestigationPlan(
            plan_id=f"plan_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=_now_iso(),
            objective=f"Gather read-only evidence for {trigger.trigger_type} on {trigger.service}.",
            probe_budget={
                "max_probes": self.max_probes,
                "max_total_latency_ms": self.max_total_latency_ms,
                "max_tool_probes": self.max_tool_probes,
                "tool_provider": (
                    getattr(planner, "domain", None) if planner is not None
                    else (tool_provider.name if tool_provider else None)
                ),
                "mode": (
                    "harness_loop"
                    if registry is not None and planner is not None
                    else ("tool_loop" if tool_provider is not None else "deterministic_builtin")
                ),
            },
            probes=probes,
        )
        plan.validate()
        return plan

    def _run_probe(
        self,
        probe: dict[str, Any],
        trigger: Trigger,
        evidence_pack: dict[str, Any],
        context: dict[str, Any],
    ) -> InvestigationProbeResult:
        started = _now_iso()
        start = time.monotonic()
        name = str(probe["name"])
        fn = self._probe_fns.get(name)
        try:
            if fn is None:
                summary = f"Probe {name!r} is not implemented in the deterministic harness."
                findings: list[dict[str, Any]] = []
                citations: list[dict[str, Any]] = []
                status = "skipped"
                error = None
            else:
                summary, findings, citations = fn(trigger, evidence_pack, context)
                status = "completed"
                error = None
        except Exception as exc:
            summary = f"Probe {name!r} failed; existing decision path should continue."
            findings = []
            citations = []
            status = "failed"
            error = str(exc)
        completed = _now_iso()
        result = InvestigationProbeResult(
            probe_id=str(probe["probe_id"]),
            name=name,
            status=status,
            started_at=started,
            completed_at=completed,
            latency_ms=round((time.monotonic() - start) * 1000.0, 3),
            summary=summary,
            findings=findings,
            citations=citations,
            error=error,
        )
        result.validate()
        return result


def _registry_for_tool_provider(tool_provider: InvestigationToolProvider) -> ToolRegistry:
    registry = ToolRegistry()
    definitions = {definition.name: definition for definition in CLOUDOPS_TOOL_DEFINITIONS}
    for tool_name in tool_provider.available_tools():
        definition = definitions.get(tool_name)
        if definition is None:
            continue
        registry.register(definition, _make_provider_invoker(tool_provider, tool_name))
    return registry


def _make_provider_invoker(tool_provider: InvestigationToolProvider, tool_name: str) -> Callable[[dict[str, Any]], RawToolOutput]:
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        response = tool_provider.invoke(tool_name, args)
        output = response.get("output") if isinstance(response, dict) else None
        valid = bool(response.get("valid", True)) if isinstance(response, dict) else False
        raw_status = str(response.get("status") or "completed").lower() if isinstance(response, dict) else "failed"
        status: Literal["completed", "failed"] = "failed" if raw_status in {"failed", "error"} else "completed"
        return RawToolOutput(
            output=output,
            output_summary=_summarize_tool_output(output),
            citations=[_citation(f"{tool_provider.name}:{tool_name}", _arg_summary(args) or tool_name)],
            valid=valid,
            redaction_status="clean",
            status=status,
        )

    return invoke


def _provider_stop_reason(stop_reason: str | None) -> str:
    if stop_reason == "budget_exhausted":
        return "tool_probe_budget_exhausted"
    return stop_reason or "evidence_value_exhausted"


def _probe_evidence_sufficiency(
    trigger: Trigger,
    evidence_pack: dict[str, Any],
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    source = evidence_pack.get("source", "unknown")
    sufficient = evidence_pack.get("sufficient")
    missing = list(evidence_pack.get("missing_fields", []) or [])
    finding = {
        "kind": "evidence_sufficiency",
        "summary": f"Evidence pack source={source}, sufficient={sufficient}.",
        "confidence": 0.9 if sufficient is not False else 0.75,
        "details": {
            "source": source,
            "sufficient": sufficient,
            "missing_fields": missing,
            "probe_count": len(evidence_pack.get("probe_results", []) or []),
        },
    }
    if missing:
        finding["summary"] = f"Evidence pack is missing {len(missing)} field(s)."
    return str(finding["summary"]), [finding], [_citation("evidence_pack", "evidence_pack")]


def _probe_trigger_signature_scan(
    trigger: Trigger,
    evidence_pack: dict[str, Any],
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    metrics = trigger.metrics or {}
    related = trigger.related_context or {}
    signatures = list(related.get("error_signatures", []) or [])
    signal_names = list(related.get("trigger_signals", []) or [])
    finding = {
        "kind": "trigger_signature_scan",
        "summary": f"Trigger carries {len(signatures) + len(signal_names)} explicit signature(s).",
        "confidence": 0.78 if signatures or signal_names else 0.55,
        "details": {
            "trigger_type": trigger.trigger_type,
            "service": trigger.service,
            "endpoint": trigger.endpoint,
            "error_signatures": signatures,
            "trigger_signals": signal_names,
            "metric_keys": sorted(metrics.keys()),
        },
    }
    return str(finding["summary"]), [finding], [_citation("trigger", trigger.trigger_id)]


def _probe_memory_context(
    trigger: Trigger,
    evidence_pack: dict[str, Any],
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    packet = context.get("memory_packet") or {}
    claims = list(packet.get("claims", []) or [])
    procedures = list(packet.get("procedures", []) or [])
    recent_runs = list(context.get("recent_runs") or [])
    finding = {
        "kind": "memory_context",
        "summary": (
            f"Memory contributes {len(claims)} claim(s), {len(procedures)} procedure(s), "
            f"and {len(recent_runs)} recent run(s)."
        ),
        "confidence": 0.72 if claims or procedures or recent_runs else 0.5,
        "details": {
            "claim_count": len(claims),
            "procedure_count": len(procedures),
            "recent_run_count": len(recent_runs),
        },
    }
    citations = [_citation("memory_packet", str(packet.get("packet_id", "memory_packet")))]
    return str(finding["summary"]), [finding], citations


def _probe_topology_context(
    trigger: Trigger,
    evidence_pack: dict[str, Any],
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    topology = context.get("topology") or {}
    nodes = list(topology.get("nodes", []) or [])
    edges = list(topology.get("edges", []) or [])
    finding = {
        "kind": "topology_context",
        "summary": f"Topology context contains {len(nodes)} node(s) and {len(edges)} edge(s).",
        "confidence": 0.68 if nodes or edges else 0.5,
        "details": {"node_count": len(nodes), "edge_count": len(edges)},
    }
    return str(finding["summary"]), [finding], [_citation("topology", trigger.service)]


def _estimate_uncertainty(
    evidence_pack: dict[str, Any],
    findings: list[dict[str, Any]],
    context: dict[str, Any],
    root_cause_candidates: list[dict[str, Any]] | None = None,
) -> float:
    uncertainty = 0.55
    if evidence_pack.get("sufficient") is True:
        uncertainty -= 0.18
    if evidence_pack.get("sufficient") is False:
        uncertainty += 0.18
    evidentiary_findings = [finding for finding in findings if finding.get("kind") != "planner_telemetry"]
    if evidentiary_findings:
        uncertainty -= min(len(evidentiary_findings), 4) * 0.03
    memory_packet = context.get("memory_packet") or {}
    if memory_packet.get("claims") or memory_packet.get("procedures"):
        uncertainty -= 0.04
    if root_cause_candidates:
        top_confidence = float(root_cause_candidates[0].get("confidence") or 0.0)
        uncertainty -= min(0.20, top_confidence * 0.16)
    return round(max(0.05, min(0.95, uncertainty)), 3)


def _evidence_marked_insufficient(evidence_pack: dict[str, Any]) -> bool:
    return bool(evidence_pack.get("sufficient") is False)


def _citation(source_type: str, source_ref: str) -> dict[str, Any]:
    return {"source_type": source_type, "source_ref": source_ref}


def _dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for citation in citations:
        key = (str(citation.get("source_type")), str(citation.get("source_ref")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _arg_summary(args: dict[str, Any]) -> str:
    if not args:
        return ""
    return ",".join(f"{key}={value}" for key, value in args.items() if value)


def _summarize_tool_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, dict):
        if "error" in value and len(value) == 1:
            return f"error: {value['error']}"
        return _flatten_json(value)[:1000]
    if isinstance(value, list):
        return _flatten_json(value)[:1000]
    return str(value)[:1000]


def _flatten_json(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key}={_flatten_json(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_json(item) for item in value)
    return str(value)


def _root_cause_candidates(
    ranked: list[RankedCause],
    observed_tool_text: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, cause in enumerate(ranked, start=1):
        supporting_tools = sorted(
            {
                tool_name
                for tool_name, output_text in observed_tool_text
                if any(pattern.lower() in output_text.lower() for pattern in cause.matched_patterns)
            }
        )
        candidates.append(
            {
                "rank": index,
                "root_cause": cause.root_cause,
                "confidence": cause.confidence,
                "matched_patterns": list(cause.matched_patterns),
                "supporting_tools": supporting_tools,
                "citation_ids": [f"rca_ontology:{cause.root_cause}"],
            }
        )
    return candidates


def _ranked_finding(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    top = candidates[0]
    summary_parts = [str(candidate.get("root_cause")) for candidate in candidates[:3]]
    return {
        "kind": "ranked_root_causes",
        "summary": str(top.get("root_cause")),
        "confidence": float(top.get("confidence") or 0.0),
        "details": {
            "ranked": candidates,
            "top_3": summary_parts,
        },
    }


def _planner_telemetry_finding(
    state: InvestigationLoopState,
    final_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    planned_call_count = sum(len(decision.get("planned_calls") or []) for decision in state.planner_decisions)
    rejected_call_count = len(state.rejections)
    attempted_call_count = planned_call_count or (len(state.tool_calls) + rejected_call_count)
    duplicate_rejections = sum(1 for rejection in state.rejections if rejection.reason == "duplicate_call")
    valid_count = sum(1 for result in state.tool_results if result.valid)
    invalid_count = len(state.tool_results) - valid_count
    latency_by_family = _tool_latency_by_family(state)
    details = {
        "critic_rejections_by_reason": _rejections_by_reason(state),
        "tool_latency_ms_by_family": latency_by_family,
        "valid_result_rate": _rate(valid_count, len(state.tool_results)),
        "invalid_result_rate": _rate(invalid_count, len(state.tool_results)),
        "duplicate_call_rejection_rate": _rate(duplicate_rejections, attempted_call_count),
        "budget_exhaustion_rate": 1.0 if state.stop_reason == "budget_exhausted" else 0.0,
        "evidence_value_exhaustion_rate": 1.0 if state.stop_reason == "evidence_value_exhausted" else 0.0,
        "rca_confidence_trace": _rca_confidence_trace(state, final_candidates),
        "planned_call_count": planned_call_count,
        "accepted_call_count": len(state.tool_calls),
        "rejected_call_count": rejected_call_count,
        "stop_reason": state.stop_reason,
        "planner_decisions": list(state.planner_decisions),
    }
    return {
        "kind": "planner_telemetry",
        "summary": (
            f"planner stop={state.stop_reason or 'unknown'} "
            f"valid_rate={details['valid_result_rate']:.3f} "
            f"duplicate_rejection_rate={details['duplicate_call_rejection_rate']:.3f}"
        ),
        "confidence": 1.0,
        "details": details,
    }


def _rejections_by_reason(state: InvestigationLoopState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rejection in state.rejections:
        counts[rejection.reason] = counts.get(rejection.reason, 0) + 1
    return counts


def _tool_latency_by_family(state: InvestigationLoopState) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[float]] = {}
    for result in state.tool_results:
        grouped.setdefault(result.tool_name, []).append(float(result.latency_ms))
    return {
        tool_name: {
            "count": len(values),
            "avg_ms": round(sum(values) / len(values), 3),
            "max_ms": round(max(values), 3),
            "total_ms": round(sum(values), 3),
        }
        for tool_name, values in sorted(grouped.items())
        if values
    }


def _rca_confidence_trace(
    state: InvestigationLoopState,
    final_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for decision in state.planner_decisions:
        debug = decision.get("debug") if isinstance(decision.get("debug"), dict) else {}
        top = debug.get("top_root_cause") if isinstance(debug.get("top_root_cause"), dict) else None
        trace.append(
            {
                "iteration": decision.get("iteration"),
                "phase": "before_planner_decision",
                "root_cause": top.get("root_cause") if top else None,
                "confidence": float(top.get("confidence") or 0.0) if top else 0.0,
            }
        )
    top_final = final_candidates[0] if final_candidates else None
    trace.append(
        {
            "iteration": state.iteration,
            "phase": "after_probes",
            "root_cause": top_final.get("root_cause") if top_final else None,
            "confidence": float(top_final.get("confidence") or 0.0) if top_final else 0.0,
        }
    )
    return trace


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
