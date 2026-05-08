from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .connector_certification import (
    DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY,
    STATE_ORDER,
    load_connector_certification_registry,
)
from .contracts import Decision
from .schema_validation import SchemaValidationError


AutonomyPolicyTier = Literal["fully_autonomous", "approval_required", "advisory_only", "denied_always"]

_ADVISORY_SCOPES = {
    "contract-check",
    "eval-read",
    "explain",
    "local-audit",
    "metrics-read",
    "orchestration-evidence",
    "proposal",
    "read-only",
    "review",
}
_MUTATING_SCOPES = {
    "alert-intake",
    "append-only-audit-write",
    "incident-write",
    "patch",
    "rollback",
    "rollout-restart",
    "scale",
    "write",
}
_TARGET_MINIMUM_STATE = {
    "local": "staging-ready",
    "staging": "staging-ready",
    "pilot": "pilot-ready",
    "production": "production-ready",
    "prod": "production-ready",
    "expansion": "production-ready",
}
_SYSTEM_CONNECTOR = {
    "audit_log_sink": "audit_sink",
    "feature_flag_service": "feature_flag_adapter",
    "incident_service": "incident_adapter",
    "kubernetes_service": "kubernetes",
    "repo_patch_service": "codex",
    "systemd_service": "systemd_service",
}
_ACTION_SCOPE = {
    "investigate_and_patch": "proposal",
    "open_incident": "incident-write",
    "patch_resources": "patch",
    "record_defer_until": "local-audit",
    "record_no_action": "local-audit",
    "restart_deployment": "rollout-restart",
    "restart_pod": "rollout-restart",
    "restart_systemd_service": "restart-service",
    "rollback_deployment": "rollback",
    "scale_deployment": "scale",
    "set_rollout": "write",
}


@dataclass(frozen=True)
class AutonomyPolicyVerdict:
    policy_tier: AutonomyPolicyTier
    allowed: bool
    live_execution_allowed: bool
    mock_execution_only: bool
    connector_id: str
    connector_state: str | None
    requested_scope: str
    minimum_state: str
    blockers: tuple[str, ...]
    live_blockers: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    approval_observed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_tier": self.policy_tier,
            "allowed": self.allowed,
            "live_execution_allowed": self.live_execution_allowed,
            "mock_execution_only": self.mock_execution_only,
            "connector_id": self.connector_id,
            "connector_state": self.connector_state,
            "requested_scope": self.requested_scope,
            "minimum_state": self.minimum_state,
            "blockers": list(self.blockers),
            "live_blockers": list(self.live_blockers),
            "evidence_refs": list(self.evidence_refs),
            "approval_observed": self.approval_observed,
        }


def evaluate_autonomy_policy(
    decision: Decision,
    *,
    policy_tier: AutonomyPolicyTier | None = None,
    connector_registry_path: str | Path | None = None,
    target_profile: str = "pilot",
    connector_id: str | None = None,
    requested_scope: str | None = None,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    approval_observed: bool = False,
    live_execution_enabled: bool = False,
    force_approval_gate: bool = False,
) -> AutonomyPolicyVerdict:
    tier = policy_tier or _tier_from_decision(decision)
    connector = connector_id or _connector_id(decision)
    scope = requested_scope or _requested_scope(decision)
    refs = tuple(str(ref) for ref in (evidence_refs or _decision_evidence_refs(decision)) if str(ref).strip())
    minimum_state = _minimum_state(target_profile)
    registry_path = str(connector_registry_path or DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY)

    blockers: list[str] = []
    certification_blockers: list[str] = []
    live_blockers: list[str] = []
    record = _connector_record(registry_path, connector)
    connector_state = str(record.get("state")) if record else None
    allowed_scopes = {str(item) for item in record.get("allowed_scopes", [])} if record else set()

    if tier == "denied_always":
        blockers.append("autonomy_tier_denied_always")
    if record is None:
        certification_blockers.append("connector_not_certified")
    elif not _state_at_least(connector_state or "disabled", minimum_state):
        certification_blockers.append("connector_state_below_target_minimum")
    if scope not in allowed_scopes:
        certification_blockers.append("scope_not_allowed_by_connector_certification")
    if tier == "advisory_only" and scope not in _ADVISORY_SCOPES:
        blockers.append("advisory_only_scope_cannot_mutate")
    if tier == "approval_required" and not approval_observed:
        blockers.append("approval_required_before_execution")
    if tier == "fully_autonomous" and force_approval_gate:
        blockers.append("approval_required_before_execution")
    if _scope_is_mutating(scope) and tier == "fully_autonomous" and not refs:
        blockers.append("evidence_required_before_execution")

    if live_execution_enabled:
        blockers.extend(certification_blockers)
    live_blockers.extend(blockers)
    live_blockers.extend(certification_blockers)
    if _scope_is_mutating(scope) and not live_execution_enabled:
        live_blockers.append("live_execution_disabled")

    allowed = not blockers
    live_execution_allowed = allowed and not live_blockers
    return AutonomyPolicyVerdict(
        policy_tier=tier,
        allowed=allowed,
        live_execution_allowed=live_execution_allowed,
        mock_execution_only=allowed and not live_execution_allowed,
        connector_id=connector,
        connector_state=connector_state,
        requested_scope=scope,
        minimum_state=minimum_state,
        blockers=tuple(sorted(set(blockers))),
        live_blockers=tuple(sorted(set(live_blockers))),
        evidence_refs=refs,
        approval_observed=approval_observed,
    )


def _connector_record(registry_path: str, connector_id: str) -> dict[str, Any] | None:
    try:
        registry = load_connector_certification_registry(registry_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError):
        return None
    for record in (registry or {}).get("connectors", []):
        if isinstance(record, dict) and record.get("connector_id") == connector_id:
            return record
    return None


def _tier_from_decision(decision: Decision) -> AutonomyPolicyTier:
    raw = str(decision.autonomy_tier)
    if raw == "autonomous":
        return "fully_autonomous"
    if raw == "approval_required":
        return "approval_required"
    return "advisory_only"


def _connector_id(decision: Decision) -> str:
    override = _execution_override(decision, "connector_id")
    if override:
        return override
    return _SYSTEM_CONNECTOR.get(str(decision.execution_plan.get("system") or ""), "unknown")


def _requested_scope(decision: Decision) -> str:
    override = _execution_override(decision, "requested_scope")
    if override:
        return override
    return _ACTION_SCOPE.get(str(decision.execution_plan.get("action") or ""), "unknown")


def _execution_override(decision: Decision, key: str) -> str | None:
    parameters = decision.execution_plan.get("parameters", {})
    if isinstance(parameters, dict) and parameters.get(key):
        return str(parameters[key])
    certification = decision.reasoning.get("connector_certification")
    if isinstance(certification, dict) and certification.get(key):
        return str(certification[key])
    return None


def _decision_evidence_refs(decision: Decision) -> tuple[str, ...]:
    refs: list[str] = [decision.decision_id]
    for key in ("source_event_ids", "evidence_event_ids"):
        raw = decision.reasoning.get(key)
        if isinstance(raw, list):
            refs.extend(str(item) for item in raw)
    evidence_pack = decision.reasoning.get("evidence_pack")
    if isinstance(evidence_pack, dict):
        for key in ("artifact_ref", "proof_ref", "run_export_ref"):
            value = evidence_pack.get(key)
            if value:
                refs.append(str(value))
    return tuple(refs)


def _minimum_state(target_profile: str) -> str:
    return _TARGET_MINIMUM_STATE.get(str(target_profile).lower(), "pilot-ready")


def _state_at_least(observed: str, minimum: str) -> bool:
    return STATE_ORDER.get(observed, 0) >= STATE_ORDER.get(minimum, STATE_ORDER["pilot-ready"])


def _scope_is_mutating(scope: str) -> bool:
    return scope in _MUTATING_SCOPES or scope not in _ADVISORY_SCOPES
