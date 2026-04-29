"""Explainable remediation safety scoring.

This module is deliberately deterministic. It is a second safety case layered
on top of policy, schema, Mesh trajectory quality, and execution readiness.
It may add blockers; it must not bypass existing blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .contracts import Decision, Trigger


SafetyVerdict = Literal["pass", "needs_more_evidence", "human_review"]

_DEFAULT_THRESHOLD = 0.72
_AUDIT_ACTIONS = {"record_no_action", "open_incident"}
_MUTATING_DECISIONS = {
    "reduce_rollout",
    "disable_flag",
    "investigate_and_patch",
    "rollback_deployment",
    "restart_deployment",
    "restart_pod",
    "scale_deployment",
    "cordon_node",
    "drain_node",
    "argocd_sync",
    "argocd_rollback",
    "restart_systemd_service",
}
_SEVERE_SIGNATURES = {
    "disk_pressure",
    "jwt_missing",
    "jwt_secret_missing",
    "rpc_exposed",
    "authrpc_exposed",
    "engine_api_unreachable",
    "consensus_disconnect",
}
_PROTECTED_TIERS = {"strategic", "platinum"}


@dataclass(frozen=True)
class RemediationSafetyCase:
    """Scored safety case for a proposed remediation."""

    score: float
    threshold: float
    verdict: SafetyVerdict
    passed: bool
    components: dict[str, float]
    hard_stops: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "threshold": self.threshold,
            "verdict": self.verdict,
            "passed": self.passed,
            "components": dict(self.components),
            "hard_stops": list(self.hard_stops),
            "warnings": list(self.warnings),
            "evidence_refs": list(self.evidence_refs),
        }


def evaluate_remediation_safety(
    trigger: Trigger,
    decision: Decision,
    *,
    state_store: Any | None = None,
    prior_blocking_reasons: list[str] | None = None,
    promptfoo_passed: bool = True,
    schema_passed: bool = True,
    policy_passed: bool = True,
    readiness_passed: bool = True,
    threshold: float = _DEFAULT_THRESHOLD,
) -> RemediationSafetyCase:
    """Build an explainable safety case for a decision.

    The score is advisory unless it fails. Existing evaluation blockers are
    treated as hard stops so this layer cannot make a rejected action executable.
    """

    prior_blocking_reasons = list(prior_blocking_reasons or [])
    components = {
        "policy": _bool_score(schema_passed and policy_passed),
        "quality": _bool_score(promptfoo_passed),
        "readiness": _bool_score(readiness_passed),
        "evidence": _evidence_score(trigger, decision),
        "action": _action_score(decision),
        "blast_radius": _blast_radius_score(trigger, decision),
        "history": _history_score(trigger, decision, state_store),
        "recovery": _recovery_score(trigger, decision),
    }
    score = round(
        components["policy"] * 0.18
        + components["quality"] * 0.12
        + components["readiness"] * 0.14
        + components["evidence"] * 0.18
        + components["action"] * 0.14
        + components["blast_radius"] * 0.10
        + components["history"] * 0.08
        + components["recovery"] * 0.06,
        3,
    )
    hard_stops = _hard_stops(
        trigger,
        decision,
        prior_blocking_reasons=prior_blocking_reasons,
        components=components,
        schema_passed=schema_passed,
        policy_passed=policy_passed,
        readiness_passed=readiness_passed,
    )
    warnings = _warnings(trigger, decision, components=components, state_store=state_store)
    if hard_stops:
        verdict: SafetyVerdict = "human_review"
    elif score < threshold:
        verdict = "needs_more_evidence"
    else:
        verdict = "pass"
    return RemediationSafetyCase(
        score=score,
        threshold=threshold,
        verdict=verdict,
        passed=verdict == "pass",
        components={key: round(value, 3) for key, value in components.items()},
        hard_stops=tuple(hard_stops),
        warnings=tuple(warnings),
        evidence_refs=tuple(_evidence_refs(trigger, decision)),
    )


def safety_blocking_reason(case: RemediationSafetyCase) -> str | None:
    """Return the evaluation blocker for a failed safety case."""

    if case.passed:
        return None
    if case.hard_stops:
        return "remediation safety case has hard stops"
    return "remediation safety score below execution threshold"


def _bool_score(value: bool) -> float:
    return 1.0 if value else 0.0


def _evidence_score(trigger: Trigger, decision: Decision) -> float:
    score = 0.2
    if trigger.metrics:
        score += 0.15
    if trigger.related_context:
        score += 0.15
    evidence = decision.reasoning.get("evidence", [])
    if isinstance(evidence, list) and len(evidence) >= 2:
        score += 0.2
    evidence_pack = decision.reasoning.get("evidence_pack")
    if isinstance(evidence_pack, dict) and evidence_pack:
        score += 0.2
        missing = evidence_pack.get("evidence_pack_artifact", {}).get("missing_fields", [])
        if isinstance(missing, list) and missing:
            score -= min(0.25, 0.05 * len(missing))
    if _source_event_ids(decision):
        score += 0.1
    if trigger.trigger_type == "reth_node_degraded":
        signal = _first_dict(decision.reasoning.get("evidence_pack"), trigger.related_context.get("source_signal"))
        for field in ("execution", "consensus", "storage", "rpc", "node"):
            if isinstance(signal.get(field), dict) and signal[field]:
                score += 0.04
    return _clamp(score)


def _action_score(decision: Decision) -> float:
    action = str(decision.execution_plan.get("action") or "")
    decision_type = str(decision.decision_type)
    score = 0.4
    if action in _AUDIT_ACTIONS:
        return 1.0
    if decision.execution_plan.get("rollback_plan"):
        score += 0.2
    if decision.confidence >= 0.85:
        score += 0.2
    elif decision.confidence >= 0.75:
        score += 0.1
    else:
        score -= 0.15
    if decision.risk.get("level") == "low":
        score += 0.1
    if decision.risk.get("level") == "high":
        score -= 0.25
    if decision_type in _MUTATING_DECISIONS and not decision.execution_plan.get("rollback_plan"):
        score -= 0.25
    return _clamp(score)


def _blast_radius_score(trigger: Trigger, decision: Decision) -> float:
    score = 1.0
    blast_radius = str(decision.risk.get("blast_radius") or "")
    if blast_radius.startswith("multi_"):
        score -= 0.45
    if decision.risk.get("level") == "high":
        score -= 0.3
    if trigger.segment.get("customer_tier") in _PROTECTED_TIERS:
        score -= 0.25
    if decision.autonomy_tier in {"approval_required", "escalated"}:
        score -= 0.15
    return _clamp(score)


def _history_score(trigger: Trigger, decision: Decision, state_store: Any | None) -> float:
    if state_store is None or not hasattr(state_store, "get_historical_success_rate"):
        return 0.58
    try:
        rate = state_store.get_historical_success_rate(decision.decision_type, trigger.service)
    except Exception:
        return 0.5
    if rate is None:
        return 0.58
    return _clamp(float(rate))


def _recovery_score(trigger: Trigger, decision: Decision) -> float:
    action = str(decision.execution_plan.get("action") or "")
    if action in _AUDIT_ACTIONS:
        return 1.0
    observations = trigger.related_context.get("post_action_observations") or {}
    if not observations:
        observations = decision.reasoning.get("post_action_observations") or {}
    if isinstance(observations, dict) and observations:
        return 0.85
    expected = decision.expected_outcome.get("target_metrics") if isinstance(decision.expected_outcome, dict) else None
    if expected:
        return 0.65
    return 0.45


def _hard_stops(
    trigger: Trigger,
    decision: Decision,
    *,
    prior_blocking_reasons: list[str],
    components: dict[str, float],
    schema_passed: bool,
    policy_passed: bool,
    readiness_passed: bool,
) -> list[str]:
    stops = []
    if not schema_passed:
        stops.append("schema validation failed")
    if not policy_passed:
        stops.append("policy validation failed")
    if not readiness_passed:
        stops.append("execution readiness failed")
    if decision.autonomy_tier == "autonomous" and decision.risk.get("level") == "high":
        stops.append("autonomous high-risk action is forbidden")
    if str(decision.risk.get("blast_radius") or "").startswith("multi_") and decision.autonomy_tier == "autonomous":
        stops.append("autonomous multi-service action is forbidden")
    if trigger.segment.get("customer_tier") in _PROTECTED_TIERS and decision.autonomy_tier == "autonomous":
        stops.append("autonomous protected-tier action is forbidden")
    signatures = set(_error_signatures(trigger, decision))
    if signatures & _SEVERE_SIGNATURES and decision.decision_type != "escalate":
        stops.append("severe signature requires escalation")
    if decision.decision_type in _MUTATING_DECISIONS and components["evidence"] < 0.55:
        stops.append("mutating action lacks sufficient evidence")
    if decision.decision_type in _MUTATING_DECISIONS and components["history"] < 0.35:
        stops.append("historical success rate is too weak for autonomous remediation")
    return stops


def _warnings(trigger: Trigger, decision: Decision, *, components: dict[str, float], state_store: Any | None) -> list[str]:
    warnings = []
    if components["history"] < 0.6:
        warnings.append("historical support is weak or unavailable")
    if components["recovery"] < 0.6:
        warnings.append("post-action recovery evidence is weak")
    if trigger.related_context.get("conflicting_signals"):
        warnings.append("conflicting signals are present")
    if not _source_event_ids(decision):
        warnings.append("no source run event ids available for analysis provenance")
    if state_store is None:
        warnings.append("state store unavailable for historical prior")
    return warnings


def _evidence_refs(trigger: Trigger, decision: Decision) -> list[str]:
    refs = [trigger.trigger_id, decision.decision_id]
    refs.extend(_source_event_ids(decision))
    return [str(ref) for ref in refs if ref]


def _source_event_ids(decision: Decision) -> list[str]:
    raw = decision.reasoning.get("source_event_ids") or decision.reasoning.get("evidence_event_ids") or []
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _error_signatures(trigger: Trigger, decision: Decision) -> list[str]:
    signatures: list[str] = []
    for source in (
        trigger.related_context,
        decision.reasoning.get("evidence_pack") if isinstance(decision.reasoning.get("evidence_pack"), dict) else {},
    ):
        if not isinstance(source, dict):
            continue
        raw = source.get("error_signatures")
        if raw is None:
            raw = source.get("logs", {}).get("error_signatures") if isinstance(source.get("logs"), dict) else None
        if isinstance(raw, list):
            signatures.extend(str(item) for item in raw)
    return signatures


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _clamp(value: float) -> float:
    return max(0.0, min(float(value), 1.0))
