from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


PROVIDER_ADAPTER_PROOF_SCHEMA = "provider-adapter-proof.schema.json"
PROVIDER_ADAPTER_PROOF_VERSION = "mesh.provider_adapter_proof.v1"
PROVIDER_ADAPTER_VERIFICATION_VERSION = "mesh.provider_adapter_verification.v1"
SUPPORTED_PROVIDER_ADAPTERS = frozenset({"feature_flag_provider", "incident_provider"})
_PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"staging", "pilot", "production", "prod", "expansion"})
_REQUIRED_ACTIONS = {
    "feature_flag_provider": frozenset({"read_flag", "set_rollout", "rollback_flag"}),
    "incident_provider": frozenset({"read_incident", "create_incident", "update_incident"}),
}


def load_provider_adapter_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(PROVIDER_ADAPTER_PROOF_SCHEMA, payload)
    return payload


def provider_adapter_proof_ready(path: str | Path | None, *, adapter_id: str) -> bool:
    return verify_provider_adapter_proof(path, adapter_id=adapter_id)["status"] == "pass"


def verify_provider_adapter_proof(path: str | Path | None, *, adapter_id: str) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_provider_adapter_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof, adapter_id=adapter_id)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": PROVIDER_ADAPTER_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "adapter_id": adapter_id,
        "provider_name": proof.get("provider_name") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(proof: dict[str, Any] | None, *, adapter_id: str) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "supported_adapter": adapter_id in SUPPORTED_PROVIDER_ADAPTERS,
            "adapter_matches": False,
            "proof_id_present": False,
            "provider_name_present": False,
            "operator_present": False,
            "production_like_environment": False,
            "required_actions_present": False,
            "authority_boundary_present": False,
            "service_account_ref_present": False,
            "credential_rotation_ref_present": False,
            "break_glass_recording_ref_present": False,
            "audit_sink_ref_present": False,
            "dry_run_ref_present": False,
            "rollback_ref_present": False,
            "degraded_behavior_present": False,
            "production_write_enabled": False,
            "proposal_lane_credentials_absent": False,
            "no_raw_secret_material": False,
        }
    return {
        "proof_present": True,
        "schema_valid": True,
        "supported_adapter": adapter_id in SUPPORTED_PROVIDER_ADAPTERS,
        "adapter_matches": proof.get("adapter_id") == adapter_id,
        "proof_id_present": bool(str(proof.get("proof_id") or "").strip()),
        "provider_name_present": bool(str(proof.get("provider_name") or "").strip()),
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "production_like_environment": str(proof.get("environment") or "").strip() in _PRODUCTION_LIKE_ENVIRONMENTS,
        "required_actions_present": _required_actions_present(proof, adapter_id),
        "authority_boundary_present": bool(str(proof.get("authority_boundary") or "").strip()),
        "service_account_ref_present": bool(str(proof.get("service_account_ref") or "").strip()),
        "credential_rotation_ref_present": bool(str(proof.get("credential_rotation_ref") or "").strip()),
        "break_glass_recording_ref_present": bool(str(proof.get("break_glass_recording_ref") or "").strip()),
        "audit_sink_ref_present": bool(str(proof.get("audit_sink_ref") or "").strip()),
        "dry_run_ref_present": bool(str(proof.get("dry_run_ref") or "").strip()),
        "rollback_ref_present": bool(str(proof.get("rollback_ref") or "").strip()),
        "degraded_behavior_present": bool(str(proof.get("degraded_behavior") or "").strip()),
        "production_write_enabled": proof.get("production_write_enabled") is True,
        "proposal_lane_credentials_absent": proof.get("proposal_lane_credentials_absent") is True,
        "no_raw_secret_material": proof.get("raw_secret_material_present") is False,
    }


def _required_actions_present(proof: dict[str, Any], adapter_id: str) -> bool:
    required = _REQUIRED_ACTIONS.get(adapter_id, frozenset())
    actions = {str(action) for action in proof.get("supported_actions", [])}
    return bool(required) and required.issubset(actions)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
