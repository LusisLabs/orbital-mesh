from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


LOAD_CONCURRENCY_REHEARSAL_SCHEMA = "load-concurrency-rehearsal.schema.json"
LOAD_CONCURRENCY_REHEARSAL_VERSION = "mesh.load_concurrency_rehearsal.v1"
LOAD_CONCURRENCY_VERIFICATION_VERSION = "mesh.load_concurrency_verification.v1"
_PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"staging", "pilot", "production", "prod", "expansion"})


def load_load_concurrency_rehearsal(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(LOAD_CONCURRENCY_REHEARSAL_SCHEMA, payload)
    return payload


def load_concurrency_rehearsal_ready(path: str | Path | None) -> bool:
    return verify_load_concurrency_rehearsal(path)["status"] == "pass"


def verify_load_concurrency_rehearsal(path: str | Path | None) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_load_concurrency_rehearsal(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": LOAD_CONCURRENCY_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "rehearsal_id": proof.get("rehearsal_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(proof: dict[str, Any] | None) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "rehearsal_id_present": False,
            "operator_present": False,
            "production_like_environment": False,
            "postgres_state_backend": False,
            "run_count_positive": False,
            "multiple_operators": False,
            "worker_count_positive": False,
            "queue_capacity_positive": False,
            "queue_depth_within_capacity": False,
            "backpressure_observed": False,
            "rejected_runs_recorded": False,
            "tenant_quota_enforced": False,
            "target_lock_conflicts_observed": False,
            "cancellation_exercised": False,
            "stuck_run_recovery_exercised": False,
            "admission_latency_within_limit": False,
            "event_persistence_latency_within_limit": False,
            "evidence_refs_present": False,
            "no_raw_secret_material": False,
        }
    return {
        "proof_present": True,
        "schema_valid": True,
        "rehearsal_id_present": bool(str(proof.get("rehearsal_id") or "").strip()),
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "production_like_environment": str(proof.get("environment") or "").strip() in _PRODUCTION_LIKE_ENVIRONMENTS,
        "postgres_state_backend": proof.get("state_backend") == "postgres",
        "run_count_positive": isinstance(proof.get("run_count"), int) and proof.get("run_count", 0) > 0,
        "multiple_operators": isinstance(proof.get("concurrent_operators"), int)
        and proof.get("concurrent_operators", 0) >= 2,
        "worker_count_positive": isinstance(proof.get("worker_count"), int) and proof.get("worker_count", 0) > 0,
        "queue_capacity_positive": isinstance(proof.get("queue_size"), int) and proof.get("queue_size", 0) > 0,
        "queue_depth_within_capacity": _queue_depth_within_capacity(proof),
        "backpressure_observed": proof.get("backpressure_observed") is True,
        "rejected_runs_recorded": isinstance(proof.get("rejected_runs"), int) and proof.get("rejected_runs", 0) > 0,
        "tenant_quota_enforced": proof.get("tenant_quota_enforced") is True,
        "target_lock_conflicts_observed": proof.get("target_lock_conflicts_observed") is True,
        "cancellation_exercised": proof.get("cancellation_exercised") is True,
        "stuck_run_recovery_exercised": proof.get("stuck_run_recovery_exercised") is True,
        "admission_latency_within_limit": _number_at_or_below(proof.get("p95_admission_latency_ms"), 1000),
        "event_persistence_latency_within_limit": _number_at_or_below(
            proof.get("p95_event_persistence_latency_ms"),
            1000,
        ),
        "evidence_refs_present": bool(proof.get("evidence_refs"))
        and all(bool(str(ref or "").strip()) for ref in proof.get("evidence_refs", [])),
        "no_raw_secret_material": proof.get("raw_secret_material_present") is False,
    }


def _queue_depth_within_capacity(proof: dict[str, Any]) -> bool:
    queue_size = proof.get("queue_size")
    max_depth = proof.get("max_queue_depth")
    return isinstance(queue_size, int) and isinstance(max_depth, int) and 0 <= max_depth <= queue_size


def _number_at_or_below(value: Any, limit: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= limit


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
