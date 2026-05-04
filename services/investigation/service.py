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
from typing import Any, Callable
from uuid import uuid4

from shared.mesh_runtime import (
    InvestigationPlan,
    InvestigationProbeResult,
    InvestigationReport,
    Trigger,
)

from .cloudops_ontology import RankedCause, rank_root_causes
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
    ) -> InvestigationReport:
        context = {
            "memory_packet": memory_packet or {},
            "service_context": service_context or {},
            "topology": topology or {},
            "recent_runs": recent_runs or [],
        }
        evidence = evidence_pack or {}
        plan = self._build_plan(trigger, context, tool_provider=tool_provider)
        probe_results: list[InvestigationProbeResult] = []
        findings: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []

        deterministic_probes = [probe for probe in plan.probes if "provider" not in probe]
        for probe in deterministic_probes[: self.max_probes]:
            result = self._run_probe(probe, trigger, evidence, context)
            probe_results.append(result)
            findings.extend(result.findings)
            citations.extend(result.citations)

        if tool_provider is not None:
            tool_results, tool_findings, tool_citations = self._run_tool_loop(
                trigger, tool_provider
            )
            probe_results.extend(tool_results)
            findings.extend(tool_findings)
            citations.extend(tool_citations)

        uncertainty = _estimate_uncertainty(evidence, findings, context)
        stop_reason = (
            "evidence_insufficient_route_to_existing_safety_gates"
            if _evidence_marked_insufficient(evidence)
            else (
                "tool_probe_budget_exhausted"
                if tool_provider is not None
                else "deterministic_probe_budget_exhausted"
            )
        )
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
        )
        report.validate()
        return report

    def _run_tool_loop(
        self,
        trigger: Trigger,
        tool_provider: InvestigationToolProvider,
    ) -> tuple[list[InvestigationProbeResult], list[dict[str, Any]], list[dict[str, Any]]]:
        """Bounded hypothesis loop driven by a read-only tool provider.

        Sequence (each step is gated by ``max_tool_probes`` and stops as
        soon as the ranked-cause confidence is high enough):

        1. ``GetResources`` — required in every Cloud-OpsBench case;
           gives the agent eyes on the pod/service inventory.
        2. ``DescribeResource`` on the suspect resource if (1) suggests
           an unhealthy object.
        3. ``GetAppYAML`` if startup looks like the failure mode.
        4. ``GetErrorLogs`` if (2) hints at runtime errors.
        5. ``GetAlerts`` if the trigger carries alert metadata.

        Each invocation produces one ``InvestigationProbeResult`` whose
        ``name`` is the canonical tool family (``GetResources`` etc.) so
        scoring can credit ``tool_coverage``. Findings include both raw
        observations and a ranked-root-cause list from the ontology.
        """

        observed_text: list[str] = []
        results: list[InvestigationProbeResult] = []
        findings: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        suspect = _suspect_resource_hint(trigger)

        plan: list[tuple[str, dict[str, Any]]] = [
            ("GetResources", {"resource_type": "pods", "namespace": _trigger_namespace(trigger)}),
            ("DescribeResource", {"resource_type": "pods", "name": suspect, "namespace": _trigger_namespace(trigger)}),
            ("GetAppYAML", {"resource_type": "deployment", "name": suspect, "namespace": _trigger_namespace(trigger)}),
            ("GetErrorLogs", {"resource_type": "pods", "name": suspect, "namespace": _trigger_namespace(trigger)}),
        ]
        if (trigger.related_context or {}).get("cloudopsbench_alert") or (trigger.related_context or {}).get("alerts"):
            plan.append(("GetAlerts", {"namespace": _trigger_namespace(trigger)}))

        available = set(tool_provider.available_tools())
        for tool_name, args in plan[: self.max_tool_probes]:
            if tool_name not in available:
                continue
            result = self._invoke_tool_probe(trigger, tool_provider, tool_name, args)
            results.append(result)
            findings.extend(result.findings)
            citations.extend(result.citations)
            for finding in result.findings:
                summary = finding.get("summary")
                if isinstance(summary, str):
                    observed_text.append(summary)
                details = finding.get("details") or {}
                output_text = details.get("output_text") if isinstance(details, dict) else None
                if isinstance(output_text, str):
                    observed_text.append(output_text)

        ranked = rank_root_causes(observed_text)
        if ranked:
            findings.append(_ranked_finding(ranked))
            for cause in ranked:
                citations.append(_citation("rca_ontology", cause.root_cause))
        return results, findings, citations

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
        if tool_provider is not None:
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
                "tool_provider": tool_provider.name if tool_provider else None,
                "mode": "tool_loop" if tool_provider is not None else "deterministic_builtin",
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


def _ranked_finding(ranked: list[RankedCause]) -> dict[str, Any]:
    top = ranked[0]
    summary_parts = [cause.root_cause for cause in ranked[:3]]
    return {
        "kind": "ranked_root_causes",
        "summary": top.root_cause,
        "confidence": top.confidence,
        "details": {
            "ranked": [
                {
                    "root_cause": cause.root_cause,
                    "confidence": cause.confidence,
                    "matched_patterns": list(cause.matched_patterns),
                }
                for cause in ranked
            ],
            "top_3": summary_parts,
        },
    }
