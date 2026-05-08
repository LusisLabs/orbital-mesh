from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


WATCH_MODE_PROOF_SCHEMA = "watch-mode-proof.schema.json"
WATCH_MODE_PROOF_VERSION = "mesh.watch_mode_proof.v1"
WATCH_MODE_PROOF_VERIFICATION_VERSION = "mesh.watch_mode_proof_verification.v1"


def load_watch_mode_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(WATCH_MODE_PROOF_SCHEMA, payload)
    return payload


def verify_watch_mode_proof(
    path: str | Path | None,
    *,
    expected_environment: str | None = None,
    require_live: bool = False,
) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_watch_mode_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof, expected_environment=expected_environment, require_live=require_live)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": WATCH_MODE_PROOF_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "evidence_level": proof.get("evidence_level") if proof else None,
        "watcher_name": proof.get("watcher_name") if proof else None,
        "run_ids": _run_ids(proof),
        "target_refs": _target_refs(proof),
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(
    proof: dict[str, Any] | None,
    *,
    expected_environment: str | None,
    require_live: bool,
) -> dict[str, bool]:
    expected_environment = (expected_environment or "").strip()
    if proof is None:
        checks = {
            "proof_present": False,
            "schema_valid": False,
            "environment_present": False,
            "live_evidence_required": not require_live,
            "multiple_ticks_recorded": False,
            "multiple_unique_runs_recorded": False,
            "run_ids_unique": False,
            "decisions_recorded": False,
            "evidence_refs_recorded": False,
            "approval_state_recorded": False,
            "duplicate_ticks_suppressed": False,
            "no_repeated_runs": False,
            "healthy_ticks_ignored": False,
            "no_false_positive_runs": False,
            "kill_switch_paused_watchers": False,
            "provider_failure_recovered": False,
            "no_run_created_during_provider_failure": False,
            "all_runs_exported": False,
            "secret_redaction_verified": False,
            "third_party_replay_ref_present": False,
        }
        if expected_environment:
            checks["environment_matches_expected"] = False
        return checks

    ticks = _list(proof.get("ticks"))
    runs = _list(proof.get("runs"))
    duplicate_suppression = _object(proof.get("duplicate_suppression"))
    false_positive_controls = _object(proof.get("false_positive_controls"))
    kill_switch = _object(proof.get("kill_switch"))
    provider_failure = _object(proof.get("provider_failure"))
    audit_exports = _object(proof.get("audit_exports"))
    run_ids = [str(run.get("run_id")) for run in runs if isinstance(run, dict) and run.get("run_id")]
    checks = {
        "proof_present": True,
        "schema_valid": True,
        "environment_present": bool(str(proof.get("environment") or "").strip()),
        "live_evidence_required": (proof.get("evidence_level") == "live") if require_live else True,
        "multiple_ticks_recorded": len(ticks) >= 2,
        "multiple_unique_runs_recorded": len(set(run_ids)) >= 2,
        "run_ids_unique": len(run_ids) == len(set(run_ids)) and bool(run_ids),
        "decisions_recorded": all(bool(str(run.get("decision_type") or "").strip()) for run in runs),
        "evidence_refs_recorded": all(bool(_list(run.get("evidence_refs"))) for run in runs),
        "approval_state_recorded": all(str(run.get("approval_state") or "") in {"not_required", "approved", "blocked", "pending"} for run in runs),
        "duplicate_ticks_suppressed": _nonzero_integer(duplicate_suppression.get("duplicate_ticks_suppressed")),
        "no_repeated_runs": duplicate_suppression.get("repeated_run_count") == 0,
        "healthy_ticks_ignored": _nonzero_integer(false_positive_controls.get("healthy_ticks_ignored")),
        "no_false_positive_runs": false_positive_controls.get("false_positive_run_count") == 0,
        "kill_switch_paused_watchers": kill_switch.get("watchers_paused") is True
        and bool(str(kill_switch.get("event_ref") or "").strip())
        and _nonzero_integer(kill_switch.get("ticks_suppressed_after_pause")),
        "provider_failure_recovered": provider_failure.get("recovered") is True
        and bool(str(provider_failure.get("provider") or "").strip())
        and bool(str(provider_failure.get("operator_visible_ref") or "").strip()),
        "no_run_created_during_provider_failure": provider_failure.get("run_created_during_failure") is False,
        "all_runs_exported": audit_exports.get("all_runs_exported") is True
        and all(bool(str(run.get("run_export_ref") or "").strip()) for run in runs),
        "secret_redaction_verified": audit_exports.get("secret_redaction_verified") is True,
        "third_party_replay_ref_present": bool(str(audit_exports.get("third_party_replay_ref") or "").strip()),
    }
    if expected_environment:
        checks["environment_matches_expected"] = proof.get("environment") == expected_environment
    return checks


def _run_ids(proof: dict[str, Any] | None) -> list[str]:
    if not proof:
        return []
    return [str(run.get("run_id")) for run in _list(proof.get("runs")) if isinstance(run, dict) and run.get("run_id")]


def _target_refs(proof: dict[str, Any] | None) -> list[str]:
    if not proof:
        return []
    refs: set[str] = set()
    for entry in [*_list(proof.get("ticks")), *_list(proof.get("runs"))]:
        if isinstance(entry, dict) and str(entry.get("target_ref") or "").strip():
            refs.add(str(entry["target_ref"]))
    return sorted(refs)


def _object(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _nonzero_integer(raw: Any) -> bool:
    return isinstance(raw, int) and raw > 0


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
