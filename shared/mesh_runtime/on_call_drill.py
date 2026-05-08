from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


ON_CALL_DRILL_SCHEMA = "on-call-drill.schema.json"
ON_CALL_DRILL_VERSION = "mesh.on_call_drill.v1"
ON_CALL_DRILL_VERIFICATION_VERSION = "mesh.on_call_drill_verification.v1"


def load_on_call_drill(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(ON_CALL_DRILL_SCHEMA, payload)
    return payload


def verify_on_call_drill(path: str | Path | None, *, expected_environment: str | None = None) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_on_call_drill(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof, expected_environment=expected_environment)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": ON_CALL_DRILL_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "drill_id": proof.get("drill_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(proof: dict[str, Any] | None, *, expected_environment: str | None = None) -> dict[str, bool]:
    expected_environment = (expected_environment or "").strip()
    if proof is None:
        checks = {
            "proof_present": False,
            "schema_valid": False,
            "operator_present": False,
            "environment_present": False,
            "recovery_target_positive": False,
            "recovery_within_target": False,
            "kill_switch_stopped_live_execution": False,
            "kill_switch_paused_watchers": False,
            "kill_switch_forced_approval_gate": False,
            "bad_target_revoked": False,
            "denied_action_proven": False,
            "stuck_run_recovered": False,
            "failed_dependency_rehearsed": False,
            "provider_key_rotation_verified": False,
            "provider_key_break_glass_recorded": False,
            "state_restore_verified": False,
        }
        if expected_environment:
            checks["environment_matches_expected"] = False
        return checks
    environment = str(proof.get("environment") or "").strip()
    kill_switch = _object(proof.get("kill_switch"))
    bad_target = _object(proof.get("bad_target_revocation"))
    stuck_run = _object(proof.get("stuck_run_recovery"))
    failed_dependency = _object(proof.get("failed_dependency"))
    provider_key_rotation = _object(proof.get("provider_key_rotation"))
    state_restore = _object(proof.get("state_restore"))
    checks = {
        "proof_present": True,
        "schema_valid": True,
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "environment_present": bool(environment),
        "recovery_target_positive": _positive_number(proof.get("recovery_target_seconds")),
        "recovery_within_target": _within_recovery_target(proof),
        "kill_switch_stopped_live_execution": kill_switch.get("live_execution_disabled") is True
        and bool(str(kill_switch.get("event_ref") or "").strip()),
        "kill_switch_paused_watchers": kill_switch.get("watchers_paused") is True,
        "kill_switch_forced_approval_gate": kill_switch.get("approval_gate_forced") is True,
        "bad_target_revoked": bad_target.get("revoked") is True
        and bool(str(bad_target.get("target_ref") or "").strip()),
        "denied_action_proven": bool(str(bad_target.get("denied_action_ref") or "").strip()),
        "stuck_run_recovered": stuck_run.get("recovered") is True
        and bool(str(stuck_run.get("run_id") or "").strip())
        and bool(str(stuck_run.get("event_ref") or "").strip()),
        "failed_dependency_rehearsed": failed_dependency.get("degraded_state_visible") is True
        and bool(str(failed_dependency.get("dependency") or "").strip())
        and bool(str(failed_dependency.get("operator_action_ref") or "").strip()),
        "provider_key_rotation_verified": provider_key_rotation.get("status") == "pass"
        and bool(str(provider_key_rotation.get("verification_ref") or "").strip()),
        "provider_key_break_glass_recorded": provider_key_rotation.get("break_glass_recorded") is True,
        "state_restore_verified": state_restore.get("status") == "pass"
        and bool(str(state_restore.get("verification_ref") or "").strip())
        and bool(str(state_restore.get("restore_ref") or "").strip()),
    }
    if expected_environment:
        checks["environment_matches_expected"] = environment == expected_environment
    return checks


def _object(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _positive_number(raw: Any) -> bool:
    return isinstance(raw, (int, float)) and raw > 0


def _within_recovery_target(proof: dict[str, Any]) -> bool:
    measured = proof.get("measured_recovery_seconds")
    target = proof.get("recovery_target_seconds")
    return isinstance(measured, (int, float)) and isinstance(target, (int, float)) and measured <= target


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
