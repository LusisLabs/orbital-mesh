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

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from shared.mesh_runtime import (
    InvestigationPlan,
    InvestigationProbeResult,
    InvestigationReport,
    Trigger,
)

from .cloudops_ontology import RankedCause, rank_root_causes
from .harness import (
    InvestigationLoopState,
    LoopCritic,
    LoopPlanner,
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
        return state, probe_results, findings, citations, root_cause_candidates

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
        """Bounded hypothesis loop driven by a read-only tool provider.

        The loop is adaptive: ``GetResources`` always runs first, and the
        suspect resource for follow-up probes is *discovered* from its
        output rather than guessed from the trigger. In hidden-mode
        snapshots the trigger redacts the real service name, so a fixed
        plan keyed on ``trigger.service`` would miss the cache. Reading
        the inventory text and pulling out the unhealthy object's name
        is what lets ``DescribeResource``/``GetAppYAML``/``GetErrorLogs``
        actually hit a populated cache key.

        Sequence:

        1. ``GetResources`` — gives the agent eyes on the pod/service
           inventory. Required in every Cloud-OpsBench case.
        2. *Observe* — pull the most likely unhealthy resource name from
           the inventory text. Fall back to the trigger hint.
        3. ``DescribeResource`` on the discovered suspect.
        4. ``GetAppYAML`` for the same resource.
        5. ``GetErrorLogs`` for the same resource.
        6. ``GetAlerts`` if the trigger carries alert metadata.

        Each invocation produces one ``InvestigationProbeResult`` whose
        ``name`` is the canonical tool family (``GetResources`` etc.) so
        scoring can credit ``tool_coverage``. Findings include raw
        observations and a ranked-root-cause list from the ontology.
        """

        observed_text: list[str] = []
        observed_tool_text: list[tuple[str, str]] = []
        results: list[InvestigationProbeResult] = []
        findings: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        root_cause_candidates: list[dict[str, Any]] = []
        stop_reason = "tool_probe_budget_exhausted"
        namespace = _trigger_namespace(trigger)
        available = set(tool_provider.available_tools())

        def run(tool_name: str, args: dict[str, Any]) -> str | None:
            if tool_name not in available or len(results) >= self.max_tool_probes:
                return None
            result = self._invoke_tool_probe(trigger, tool_provider, tool_name, args)
            results.append(result)
            findings.extend(result.findings)
            citations.extend(result.citations)
            collected: list[str] = []
            for finding in result.findings:
                summary = finding.get("summary")
                if isinstance(summary, str):
                    observed_text.append(summary)
                    collected.append(summary)
                details = finding.get("details") or {}
                output_text = details.get("output_text") if isinstance(details, dict) else None
                if isinstance(output_text, str):
                    observed_text.append(output_text)
                    observed_tool_text.append((tool_name, output_text))
                    collected.append(output_text)
            return "\n".join(collected) if collected else None

        get_resources_text = run("GetResources", {"resource_type": "pods", "namespace": namespace})
        suspect = _discover_suspect_resource(get_resources_text) or _suspect_resource_hint(trigger)
        if suspect:
            run("DescribeResource", {"resource_type": "pods", "name": suspect, "namespace": namespace})
            run("GetAppYAML", {"resource_type": "deployment", "name": suspect, "namespace": namespace})
            run("GetErrorLogs", {"resource_type": "pods", "name": suspect, "namespace": namespace})
        if (trigger.related_context or {}).get("cloudopsbench_alert") or (trigger.related_context or {}).get("alerts"):
            run("GetAlerts", {"namespace": namespace})

        ranked = rank_root_causes(observed_text)
        if ranked:
            root_cause_candidates = _root_cause_candidates(ranked, observed_tool_text)
            top_candidate = root_cause_candidates[0]
            supported_by_multiple_tools = len(top_candidate.get("supporting_tools") or []) >= 2
            if len(results) >= 2 and supported_by_multiple_tools and ranked[0].confidence >= 0.55:
                stop_reason = "root_cause_candidate_found"

        if root_cause_candidates:
            findings.append(_ranked_finding(root_cause_candidates))
            for candidate in root_cause_candidates:
                citations.append(_citation("rca_ontology", str(candidate.get("root_cause"))))
        return results, findings, citations, root_cause_candidates, stop_reason

    def _invoke_tool_probe(
        self,
        trigger: Trigger,
        tool_provider: InvestigationToolProvider,
        tool_name: str,
        args: dict[str, Any],
    ) -> InvestigationProbeResult:
        # Probe status follows the schema (completed/skipped/failed): a
        # successful tool invocation that returned an empty or error
        # payload is still ``completed`` from the agent's perspective.
        # Whether the result was useful is carried by the ``valid``
        # flag inside the finding details and the citation record.
        started = _now_iso()
        start = time.monotonic()
        status = "completed"
        error: str | None = None
        try:
            response = tool_provider.invoke(tool_name, args)
            output = response.get("output")
            valid = bool(response.get("valid", True))
        except Exception as exc:
            output = None
            valid = False
            status = "failed"
            error = str(exc)
        completed = _now_iso()
        output_text = _summarize_tool_output(output)
        finding = {
            "kind": "diagnostic_observation",
            "summary": f"{tool_name}({_arg_summary(args)}) -> {output_text[:200]}" if output_text else f"{tool_name}({_arg_summary(args)}) returned no data",
            "confidence": 0.7 if valid else 0.2,
            "details": {
                "tool_name": tool_name,
                "args": args,
                "output_text": output_text,
                "valid": valid,
            },
        }
        citations = [_citation(f"{tool_provider.name}:{tool_name}", _arg_summary(args) or tool_name)]
        result = InvestigationProbeResult(
            probe_id=f"probe_tool_{tool_name.lower()}_{uuid4().hex[:6]}",
            name=tool_name,
            status=status,
            started_at=started,
            completed_at=completed,
            latency_ms=round((time.monotonic() - start) * 1000.0, 3),
            summary=str(finding["summary"]),
            findings=[finding],
            citations=citations,
            error=error,
        )
        result.validate()
        return result

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
    if findings:
        uncertainty -= min(len(findings), 4) * 0.03
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


def _trigger_namespace(trigger: Trigger) -> str | None:
    related = trigger.related_context or {}
    namespace = related.get("cloudopsbench_namespace") or related.get("namespace")
    return str(namespace) if namespace else None


_RESOURCE_LINE_RE = re.compile(
    r"^\s*([a-z][a-z0-9-]+(?:-[a-f0-9]+)?)\s+(\d+)/(\d+)\s+([A-Za-z]+)\b"
)
_HEX_SUFFIX_RE = re.compile(r"[a-f0-9]{4,}")


def _discover_suspect_resource(get_resources_text: str | None) -> str | None:
    """Pull the unhealthy resource name out of ``GetResources`` output.

    Cloud-OpsBench tool caches return ``GetResources`` as ``kubectl get
    pods``-style text: ``<name> <ready>/<desired> <status> ...``. The
    suspect for follow-up probes is the first row whose status is not
    ``Running`` or whose ready count is below desired — that's the pod
    the operator would describe next. When everything looks healthy the
    function returns ``None`` and the caller falls back to the trigger
    hint, preserving prior behavior.
    """

    if not get_resources_text:
        return None
    for line in get_resources_text.splitlines():
        match = _RESOURCE_LINE_RE.match(line)
        if not match:
            continue
        name, ready, desired, status = match.groups()
        unhealthy_status = status.lower() not in {"running", "completed", "succeeded"}
        below_ready = int(ready) < int(desired)
        if unhealthy_status or below_ready:
            return _strip_replicaset_suffix(name)
    return None


def _strip_replicaset_suffix(name: str) -> str:
    """``frontend-7c9f-abc12`` → ``frontend``.

    CloudOps tool caches sometimes key on the deployment name and
    sometimes on the pod name. Stripping the trailing replicaset/pod
    suffix lets a single suspect string match either form during
    substring lookup.
    """

    parts = name.split("-")
    while parts and len(parts) > 1 and _HEX_SUFFIX_RE.fullmatch(parts[-1]):
        parts.pop()
    return "-".join(parts) if parts else name


def _suspect_resource_hint(trigger: Trigger) -> str:
    """Heuristic suspect for ``DescribeResource`` / ``GetAppYAML`` calls.

    Falls back to the trigger service when no better hint is available.
    Real CloudOps tool caches key off names, but the snapshot lookup is
    forgiving — passing the service name as ``name_hint`` lets it match
    pod entries that contain the deployment name as a prefix.
    """
    related = trigger.related_context or {}
    for key in ("cloudopsbench_fault_object", "fault_object", "deployment_name", "suspect_resource"):
        value = related.get(key)
        if isinstance(value, str) and value:
            return value.rsplit("/", 1)[-1]
    return trigger.service or ""


def _initial_tool_plan(trigger: Trigger, suspect: str) -> list[tuple[str, dict[str, Any]]]:
    namespace = _trigger_namespace(trigger)
    plan: list[tuple[str, dict[str, Any]]] = [
        ("GetResources", {"resource_type": "pods", "namespace": namespace}),
    ]
    if (trigger.related_context or {}).get("cloudopsbench_alert") or (trigger.related_context or {}).get("alerts"):
        plan.append(("GetAlerts", {"namespace": namespace}))
    plan.append(("DescribeResource", {"resource_type": "pods", "name": suspect, "namespace": namespace}))
    return plan


def _next_tool_plan(
    trigger: Trigger,
    suspect: str,
    observed_text: list[str],
    called: set[tuple[str, str]],
) -> list[tuple[str, dict[str, Any]]]:
    namespace = _trigger_namespace(trigger)
    haystack = "\n".join(observed_text).lower()
    candidates: list[tuple[str, dict[str, Any]]] = []
    if any(token in haystack for token in ("imagepullbackoff", "errimagepull", "createcontainerconfigerror", "configmap", "secret")):
        candidates.append(("GetAppYAML", {"resource_type": "deployment", "name": suspect, "namespace": namespace}))
    if any(token in haystack for token in ("crashloopbackoff", "back-off", "exception", "error", "connection refused", "timeout")):
        candidates.append(("GetErrorLogs", {"resource_type": "pods", "name": suspect, "namespace": namespace}))
        candidates.append(("GetRecentLogs", {"resource_type": "pods", "name": suspect, "namespace": namespace}))
    if any(token in haystack for token in ("no endpoints", "targetport", "connection refused", "dns", "no such host")):
        candidates.append(("CheckServiceConnectivity", {"service": suspect, "namespace": namespace}))
    if any(token in haystack for token in ("0/", "unschedulable", "taint", "affinity", "insufficient", "node")):
        candidates.append(("GetClusterConfiguration", {"namespace": namespace}))
    if not candidates:
        candidates.extend(
            [
                ("GetErrorLogs", {"resource_type": "pods", "name": suspect, "namespace": namespace}),
                ("GetAppYAML", {"resource_type": "deployment", "name": suspect, "namespace": namespace}),
            ]
        )
    return [
        (tool_name, args)
        for tool_name, args in candidates
        if (tool_name, _arg_summary(args)) not in called
    ]


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
