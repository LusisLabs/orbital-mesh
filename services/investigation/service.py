"""Read-only incident investigation before scenario analysis.

This first slice is deliberately deterministic. It gives Mesh an audited
investigation stage without allowing the agentic layer to mutate production or
invent actions. Later LLM planners can propose additional read-only probes
against this same contract.
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


ProbeFn = Callable[[Trigger, dict[str, Any], dict[str, Any]], tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]


class InvestigationService:
    """Build and run bounded read-only investigation probes.

    The service accepts already-normalized Mesh artifacts, runs local
    deterministic probes, and returns a contract-backed report. It performs no
    network I/O and no production mutations in this first implementation.
    """

    def __init__(self, *, max_probes: int = 4, max_total_latency_ms: int = 500) -> None:
        self.max_probes = max_probes
        self.max_total_latency_ms = max_total_latency_ms
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
    ) -> InvestigationReport:
        context = {
            "memory_packet": memory_packet or {},
            "service_context": service_context or {},
            "topology": topology or {},
            "recent_runs": recent_runs or [],
        }
        evidence = evidence_pack or {}
        plan = self._build_plan(trigger, context)
        probe_results: list[InvestigationProbeResult] = []
        findings: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []

        for probe in plan.probes[: self.max_probes]:
            result = self._run_probe(probe, trigger, evidence, context)
            probe_results.append(result)
            findings.extend(result.findings)
            citations.extend(result.citations)

        uncertainty = _estimate_uncertainty(evidence, findings, context)
        stop_reason = (
            "evidence_insufficient_route_to_existing_safety_gates"
            if _evidence_marked_insufficient(evidence)
            else "deterministic_probe_budget_exhausted"
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

    def _build_plan(self, trigger: Trigger, context: dict[str, Any]) -> InvestigationPlan:
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
        plan = InvestigationPlan(
            plan_id=f"plan_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=_now_iso(),
            objective=f"Gather read-only evidence for {trigger.trigger_type} on {trigger.service}.",
            probe_budget={
                "max_probes": self.max_probes,
                "max_total_latency_ms": self.max_total_latency_ms,
                "mode": "deterministic_builtin",
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
