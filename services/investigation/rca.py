from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from shared.mesh_runtime import Decision, RcaReport, Trigger


def build_rca_report(
    *,
    trigger: Trigger,
    decision: Decision,
    evidence_pack: dict[str, Any] | None,
) -> RcaReport | None:
    if trigger.trigger_type != "reth_node_degraded":
        return None
    ranked = decision.reasoning.get("ranked_hypotheses")
    if not isinstance(ranked, list):
        ranked = []
    top = ranked[0] if ranked and isinstance(ranked[0], dict) else {}
    likely_cause = str(top.get("candidate_cause") or "unknown")
    confidence = _safe_float(top.get("posterior_confidence"), decision.confidence)
    supporting = [str(item) for item in top.get("supporting_evidence", []) if item]
    disconfirming = [str(item) for item in top.get("disconfirming_evidence", []) if item]
    ruled_out = [
        str(item.get("candidate_cause"))
        for item in ranked[1:]
        if isinstance(item, dict)
        and item.get("candidate_cause")
        and item.get("disconfirming_evidence")
    ][:6]
    evidence_checked = _evidence_checked(evidence_pack)
    unknowns = _unknowns(ranked, evidence_pack)
    safety_reason = _safety_reason(decision, evidence_pack, top)
    report = RcaReport(
        report_id=f"rca_{trigger.trigger_id}_{uuid4().hex[:8]}",
        trigger_id=trigger.trigger_id,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        likely_cause=likely_cause,
        confidence=confidence,
        supporting_evidence=supporting,
        disconfirming_evidence=disconfirming,
        ruled_out_causes=ruled_out,
        unknowns=unknowns,
        evidence_checked=evidence_checked,
        recommended_next_step=decision.decision_type,
        safety_reason=safety_reason,
    )
    report.validate()
    return report


def _evidence_checked(evidence_pack: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(evidence_pack, dict):
        return []
    probes = evidence_pack.get("probe_results")
    if not isinstance(probes, list):
        return []
    checked: list[dict[str, Any]] = []
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        checked.append(
            {
                "name": probe.get("name"),
                "source": probe.get("source"),
                "success": probe.get("success"),
                "latency_ms": probe.get("latency_ms"),
                "citations": list(probe.get("citations") or [])[:4],
            }
        )
    return checked


def _unknowns(ranked: list[Any], evidence_pack: dict[str, Any] | None) -> list[str]:
    unknown: list[str] = []
    if isinstance(evidence_pack, dict) and evidence_pack.get("sufficient") is False:
        missing = ", ".join(str(item) for item in evidence_pack.get("missing_fields", []))
        unknown.append(f"evidence pack is insufficient: {missing or 'missing required fields'}")
    for hyp in ranked:
        if not isinstance(hyp, dict):
            continue
        predicates = hyp.get("predicates")
        if not isinstance(predicates, list):
            continue
        for predicate in predicates:
            if isinstance(predicate, dict) and predicate.get("result") == "unknown":
                unknown.append(f"{hyp.get('candidate_cause', 'unknown')}: {predicate.get('kind')}")
            if len(unknown) >= 8:
                return unknown
    return unknown


def _safety_reason(
    decision: Decision,
    evidence_pack: dict[str, Any] | None,
    top_hypothesis: dict[str, Any],
) -> str:
    if isinstance(evidence_pack, dict) and evidence_pack.get("sufficient") is False:
        return "insufficient evidence forces escalation before any node mutation"
    if decision.decision_type == "restart_systemd_service":
        return "restart remains approval-gated and supported by resolved Reth evidence"
    if decision.decision_type == "escalate":
        reason = top_hypothesis.get("recommended_action")
        if reason == "escalate":
            return "top hypothesis recommends escalation; policy keeps production mutation blocked"
        return "decision routes to human review under Reth safety policy"
    return "Reth safety policy and evaluation gates remain authoritative"


def _safe_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(0.0, min(parsed, 1.0))
