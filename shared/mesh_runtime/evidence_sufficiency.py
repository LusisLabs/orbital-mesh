from __future__ import annotations

from typing import Any

from .contracts import Decision, Trigger
from .schema_validation import validate_payload


_MUTATING_ACTIONS = frozenset({
    "disable_flag",
    "reduce_rollout",
    "rollback_deployment",
    "restart_deployment",
    "scale_deployment",
    "patch_resources",
    "restart_systemd_service",
    "investigate_and_patch",
})
_RISK_MINIMUMS = {"low": 1, "medium": 3, "high": 4}


def evaluate_evidence_sufficiency(trigger: Trigger, decision: Decision) -> dict[str, Any]:
    action_class = str(decision.execution_plan.get("action") or decision.decision_type)
    risk_tier = str(decision.risk.get("level") or "high").lower()
    mutating = action_class in _MUTATING_ACTIONS or decision.decision_type in _MUTATING_ACTIONS
    required = _RISK_MINIMUMS.get(risk_tier, 3) if mutating else 1
    refs = _collect_evidence_refs(trigger, decision)
    missing: list[str] = []
    if len(refs) < required:
        missing.append("minimum_evidence_count")
    if mutating and risk_tier in {"medium", "high"} and not _has_rollback_ref(decision):
        missing.append("rollback_reference")
    if mutating and risk_tier == "high" and not _has_structured_evidence(decision):
        missing.append("structured_evidence_pack")
    packet = {
        "schema_version": "mesh.evidence_sufficiency.v1",
        "passed": not missing,
        "action_class": action_class,
        "risk_tier": risk_tier,
        "required_evidence_count": required,
        "observed_evidence_count": len(refs),
        "evidence_refs": refs,
        "missing": missing,
        "notes": _notes(mutating=mutating, risk_tier=risk_tier, required=required),
    }
    validate_payload("evidence-sufficiency.schema.json", packet)
    return packet


def _collect_evidence_refs(trigger: Trigger, decision: Decision) -> list[str]:
    refs: list[str] = []
    if trigger.metrics:
        refs.append("trigger.metrics")
    if trigger.related_context:
        refs.append("trigger.related_context")
    reasoning = decision.reasoning if isinstance(decision.reasoning, dict) else {}
    for index, item in enumerate(reasoning.get("evidence") or []):
        if isinstance(item, str) and item.strip():
            refs.append(f"decision.reasoning.evidence[{index}]")
    evidence_pack = reasoning.get("evidence_pack") if isinstance(reasoning.get("evidence_pack"), dict) else {}
    _extend_list_refs(refs, evidence_pack, "evidence_nodes", "decision.reasoning.evidence_pack.evidence_nodes")
    _extend_list_refs(refs, evidence_pack, "probe_results", "decision.reasoning.evidence_pack.probe_results")
    _extend_list_refs(refs, evidence_pack, "fast_path_signatures", "decision.reasoning.evidence_pack.fast_path_signatures")
    _extend_list_refs(refs, evidence_pack, "citations", "decision.reasoning.evidence_pack.citations")
    _extend_nested_list_refs(
        refs,
        evidence_pack,
        ("scenario_analysis", "evidence_refs"),
        "decision.reasoning.evidence_pack.scenario_analysis.evidence_refs",
    )
    _extend_nested_list_refs(
        refs,
        evidence_pack,
        ("investigation_report", "findings"),
        "decision.reasoning.evidence_pack.investigation_report.findings",
    )
    _extend_nested_list_refs(
        refs,
        evidence_pack,
        ("investigation_report", "root_cause_candidates"),
        "decision.reasoning.evidence_pack.investigation_report.root_cause_candidates",
    )
    if evidence_pack.get("sufficient") is True:
        refs.append("decision.reasoning.evidence_pack.sufficient")
    if isinstance(evidence_pack.get("evidence_pack_artifact"), dict):
        artifact = evidence_pack["evidence_pack_artifact"]
        if artifact.get("sufficient") is True:
            refs.append("decision.reasoning.evidence_pack.evidence_pack_artifact.sufficient")
    return sorted(set(refs))


def _extend_list_refs(refs: list[str], payload: dict[str, Any], key: str, prefix: str) -> None:
    items = payload.get(key)
    if isinstance(items, list):
        refs.extend(f"{prefix}[{index}]" for index, item in enumerate(items) if item)


def _extend_nested_list_refs(
    refs: list[str],
    payload: dict[str, Any],
    keys: tuple[str, str],
    prefix: str,
) -> None:
    current = payload.get(keys[0])
    if not isinstance(current, dict):
        return
    items = current.get(keys[1])
    if isinstance(items, list):
        refs.extend(f"{prefix}[{index}]" for index, item in enumerate(items) if item)


def _has_rollback_ref(decision: Decision) -> bool:
    return bool(decision.execution_plan.get("rollback_plan"))


def _has_structured_evidence(decision: Decision) -> bool:
    reasoning = decision.reasoning if isinstance(decision.reasoning, dict) else {}
    evidence_pack = reasoning.get("evidence_pack") if isinstance(reasoning.get("evidence_pack"), dict) else {}
    return bool(
        evidence_pack.get("sufficient") is True
        or evidence_pack.get("evidence_nodes")
        or evidence_pack.get("probe_results")
        or evidence_pack.get("investigation_report")
        or evidence_pack.get("scenario_analysis")
    )


def _notes(*, mutating: bool, risk_tier: str, required: int) -> list[str]:
    action_note = "mutating action" if mutating else "non-mutating action"
    return [action_note, f"{risk_tier} risk requires {required} evidence refs"]
