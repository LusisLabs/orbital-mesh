from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .connector_certification import (
    DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY,
    STATE_ORDER,
    load_connector_certification_registry,
)
from .schema_validation import SchemaValidationError, validate_payload


PROVIDER_ACTION_SCOPE_PROOF_SCHEMA = "provider-action-scope-proof.schema.json"
PROVIDER_ACTION_SCOPE_PROOF_VERSION = "mesh.provider_action_scope_proof.v1"
PROVIDER_ACTION_SCOPE_VERIFICATION_VERSION = "mesh.provider_action_scope_verification.v1"

_ADVISORY_SCOPES = {
    "contract-check",
    "dry-run",
    "eval-read",
    "feedback-proof",
    "fixture-intake",
    "local-audit",
    "metrics-read",
    "operator-proposal",
    "orchestration-evidence",
    "proposal",
    "read-only",
}
_MUTATING_SCOPES = {
    "alert-intake",
    "append-only-audit-write",
    "incident-write",
    "rollback",
    "rollout-restart",
    "write",
}
_PRODUCTION_LIKE_ENVIRONMENTS = {"staging", "pilot", "production", "prod", "expansion"}


def load_provider_action_scope_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(PROVIDER_ACTION_SCOPE_PROOF_SCHEMA, payload)
    return payload


def verify_provider_action_scope_proof(
    path: str | Path | None,
    *,
    registry_path: str | Path | None = None,
    require_live: bool = False,
) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    registry_error: str | None = None
    try:
        proof = load_provider_action_scope_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    try:
        registry = load_connector_certification_registry(str(registry_path or DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        registry = None
        registry_error = str(exc)

    action_results = _action_results(proof, registry, require_live=require_live)
    checks = _proof_checks(proof, registry, action_results, require_live=require_live)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    if registry_error:
        checks["registry_valid"] = False
    return {
        "schema_version": PROVIDER_ACTION_SCOPE_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "evidence_level": proof.get("evidence_level") if proof else None,
        "checks": checks,
        "run_export_refs": sorted(
            {
                str(result.get("run_export_ref"))
                for result in action_results
                if str(result.get("run_export_ref") or "").strip()
            }
        ),
        "action_results": action_results,
        "error": load_error or registry_error,
    }


def _proof_checks(
    proof: dict[str, Any] | None,
    registry: dict[str, Any] | None,
    action_results: list[dict[str, Any]],
    *,
    require_live: bool,
) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "registry_valid": registry is not None,
            "production_like_environment": False,
            "live_evidence_required": not require_live,
            "action_scopes_present": False,
            "all_actions_allowed": False,
            "all_actions_have_evidence": False,
            "all_mutating_actions_have_rollback": False,
            "approval_behavior_enforced": False,
            "degraded_behavior_recorded": False,
            "secret_material_absent": False,
            "run_exports_recorded": False,
            "credential_governance_recorded": False,
        }
    return {
        "proof_present": True,
        "schema_valid": True,
        "registry_valid": registry is not None,
        "production_like_environment": str(proof.get("environment") or "") in _PRODUCTION_LIKE_ENVIRONMENTS,
        "live_evidence_required": (proof.get("evidence_level") == "live") if require_live else True,
        "action_scopes_present": bool(action_results),
        "all_actions_allowed": all(result["allowed"] for result in action_results),
        "all_actions_have_evidence": all(result["checks"]["evidence_refs_present"] for result in action_results),
        "all_mutating_actions_have_rollback": all(
            result["checks"]["rollback_or_compensation_present"] for result in action_results
        ),
        "approval_behavior_enforced": all(result["checks"]["approval_behavior_valid"] for result in action_results),
        "degraded_behavior_recorded": all(result["checks"]["degraded_behavior_present"] for result in action_results),
        "secret_material_absent": all(result["checks"]["secret_material_absent"] for result in action_results),
        "run_exports_recorded": all(result["checks"]["run_export_recorded"] for result in action_results),
        "credential_governance_recorded": all(result["checks"]["credential_governance_recorded"] for result in action_results),
    }


def _action_results(
    proof: dict[str, Any] | None,
    registry: dict[str, Any] | None,
    *,
    require_live: bool,
) -> list[dict[str, Any]]:
    if proof is None:
        return []
    connectors = _connector_records(registry)
    results: list[dict[str, Any]] = []
    for raw_action in proof.get("action_scopes", []):
        if not isinstance(raw_action, dict):
            continue
        connector_id = str(raw_action.get("connector_id") or "")
        connector = connectors.get(connector_id)
        requested_scope = str(raw_action.get("requested_scope") or "")
        policy_tier = str(raw_action.get("policy_tier") or "")
        checks = {
            "connector_present": connector is not None,
            "connector_has_no_blockers": not _connector_blockers(connector),
            "connector_state_sufficient": _connector_state_sufficient(connector, requested_scope),
            "scope_allowed_by_registry": requested_scope in _allowed_scopes(connector),
            "policy_tier_allows_scope": _policy_tier_allows_scope(policy_tier, requested_scope),
            "evidence_refs_present": bool(_strings(raw_action.get("evidence_refs"))),
            "approval_behavior_valid": _approval_behavior_valid(raw_action, requested_scope),
            "rollback_or_compensation_present": _rollback_or_compensation_present(raw_action, requested_scope),
            "degraded_behavior_present": bool(str(raw_action.get("degraded_behavior_ref") or "").strip())
            and bool(str((connector or {}).get("degraded_behavior") or "").strip()),
            "secret_material_absent": raw_action.get("secret_material_exposed") is False,
            "run_export_recorded": bool(str(raw_action.get("run_export_ref") or "").strip()),
            "credential_governance_recorded": _credential_governance_recorded(raw_action, connector),
            "live_proof_present": bool(str(raw_action.get("live_proof_ref") or "").strip()) if require_live else True,
        }
        blockers = [name for name, passed in checks.items() if not passed]
        results.append(
            {
                "action_id": raw_action.get("action_id"),
                "incident_class": raw_action.get("incident_class"),
                "connector_id": connector_id,
                "requested_scope": requested_scope,
                "policy_tier": policy_tier,
                "connector_state": (connector or {}).get("state"),
                "run_export_ref": raw_action.get("run_export_ref"),
                "allowed": not blockers,
                "checks": checks,
                "blockers": blockers,
            }
        )
    return results


def _connector_records(registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    connectors = (registry or {}).get("connectors")
    if not isinstance(connectors, list):
        return {}
    return {
        str(record.get("connector_id")): record
        for record in connectors
        if isinstance(record, dict) and record.get("connector_id")
    }


def _allowed_scopes(connector: dict[str, Any] | None) -> set[str]:
    if not connector:
        return set()
    scopes = connector.get("allowed_scopes")
    return {str(scope) for scope in scopes} if isinstance(scopes, list) else set()


def _connector_blockers(connector: dict[str, Any] | None) -> list[str]:
    blockers = (connector or {}).get("blockers")
    return [str(blocker) for blocker in blockers] if isinstance(blockers, list) else []


def _connector_state_sufficient(connector: dict[str, Any] | None, requested_scope: str) -> bool:
    if not connector:
        return False
    state = str(connector.get("state") or "disabled")
    minimum = "pilot-ready" if _scope_is_mutating(requested_scope) else "staging-ready"
    return STATE_ORDER.get(state, 0) >= STATE_ORDER[minimum]


def _policy_tier_allows_scope(policy_tier: str, requested_scope: str) -> bool:
    if policy_tier == "denied_always":
        return False
    if policy_tier == "advisory_only":
        return requested_scope in _ADVISORY_SCOPES
    if policy_tier in {"fully_autonomous", "approval_required"}:
        return requested_scope in _ADVISORY_SCOPES or requested_scope in _MUTATING_SCOPES
    return False


def _approval_behavior_valid(action: dict[str, Any], requested_scope: str) -> bool:
    approval_required = action.get("approval_required") is True
    approval_ref_present = bool(str(action.get("approval_behavior_ref") or "").strip())
    policy_tier = str(action.get("policy_tier") or "")
    if policy_tier == "approval_required":
        return approval_required and approval_ref_present
    if _scope_is_mutating(requested_scope) and policy_tier != "fully_autonomous":
        return approval_ref_present
    return action.get("approval_required") is False


def _rollback_or_compensation_present(action: dict[str, Any], requested_scope: str) -> bool:
    if not _scope_is_mutating(requested_scope):
        return True
    return bool(str(action.get("rollback_ref") or "").strip())


def _credential_governance_recorded(action: dict[str, Any], connector: dict[str, Any] | None) -> bool:
    boundary = connector.get("credential_boundary") if isinstance(connector, dict) else None
    if not isinstance(boundary, dict):
        return False
    rotation_required = bool(boundary.get("runtime_secret_mount_required") or boundary.get("production_actuator_credentials_allowed"))
    break_glass_required = bool(boundary.get("break_glass_recording_required"))
    rotation_ok = bool(str(action.get("credential_rotation_ref") or "").strip()) if rotation_required else True
    break_glass_ok = bool(str(action.get("break_glass_ref") or "").strip()) if break_glass_required else True
    return rotation_ok and break_glass_ok


def _scope_is_mutating(scope: str) -> bool:
    return scope in _MUTATING_SCOPES or scope not in _ADVISORY_SCOPES


def _strings(raw: Any) -> list[str]:
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
