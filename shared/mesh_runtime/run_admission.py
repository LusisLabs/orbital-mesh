from __future__ import annotations

import time
from typing import Any

from .schema_validation import validate_payload


def build_run_admission(
    *,
    run_id: str,
    ownership_boundary: dict[str, Any],
    queue_depth: int,
    queue_size: int,
    worker_count: int,
    tenant_active_runs: int,
    tenant_active_run_quota: int,
    target_lock_holder: str | None,
) -> dict[str, Any]:
    tenant_id = str(ownership_boundary.get("tenant_id") or "unknown")
    target_lock_key = build_target_lock_key(ownership_boundary)
    blockers: list[str] = []
    if queue_depth >= queue_size:
        blockers.append("run_queue_full")
    if tenant_active_run_quota > 0 and tenant_active_runs >= tenant_active_run_quota:
        blockers.append("tenant_active_run_quota_exceeded")
    if target_lock_holder:
        blockers.append("target_lock_held")
    packet = {
        "schema_version": "mesh.run_admission.v1",
        "generated_at": _timestamp(),
        "decision": "blocked" if blockers else "admitted",
        "run_id": run_id,
        "tenant_id": tenant_id,
        "target_lock_key": target_lock_key,
        "queue": {
            "current_depth": max(queue_depth, 0),
            "max_size": max(queue_size, 0),
            "worker_count": max(worker_count, 0),
        },
        "quotas": {
            "tenant_active_runs": max(tenant_active_runs, 0),
            "tenant_active_run_quota": max(tenant_active_run_quota, 0),
        },
        "lock": {
            "granted": not target_lock_holder,
            "holder_run_id": target_lock_holder,
        },
        "blockers": blockers,
    }
    validate_payload("run-admission.schema.json", packet)
    return packet


def build_target_lock_key(ownership_boundary: dict[str, Any]) -> str:
    service = str(ownership_boundary.get("service") or "unknown").strip() or "unknown"
    environment = str(ownership_boundary.get("environment") or "unknown").strip() or "unknown"
    tenant_id = str(ownership_boundary.get("tenant_id") or "unknown").strip() or "unknown"
    return f"{tenant_id}:{environment}:{service}"


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
