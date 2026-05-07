from __future__ import annotations

from pathlib import Path
from typing import Any

from .ownership import build_ownership_boundary
from .schema_validation import SchemaValidationError, validate_payload


WATCHER_OWNERSHIP_SCHEMA = "watcher-ownership.schema.json"
WATCHER_OWNERSHIP_VERSION = "mesh.watcher_ownership.v1"


def build_watcher_ownership_packet(
    *,
    registry_path: str | None,
    watcher_status: dict[str, Any],
    default_environment: str,
) -> dict[str, Any]:
    watchers = watcher_status.get("watchers") if isinstance(watcher_status.get("watchers"), list) else []
    watcher_packets = [
        _watcher_packet(
            watcher,
            registry_path=registry_path,
            default_environment=default_environment,
        )
        for watcher in watchers
        if isinstance(watcher, dict)
    ]
    unresolved_watchers = sorted(
        str(watcher["name"])
        for watcher in watcher_packets
        if watcher.get("blockers")
    )
    packet = {
        "schema_version": WATCHER_OWNERSHIP_VERSION,
        "status": _status(watcher_packets, unresolved_watchers),
        "environment": default_environment or "unknown",
        "watcher_count": len(watcher_packets),
        "resolved_watcher_count": len(watcher_packets) - len(unresolved_watchers),
        "unresolved_watchers": unresolved_watchers,
        "source_refs": [f"file://{Path(registry_path).resolve()}"] if registry_path else [],
        "watchers": watcher_packets,
    }
    validate_payload(WATCHER_OWNERSHIP_SCHEMA, packet)
    return packet


def _watcher_packet(
    watcher: dict[str, Any],
    *,
    registry_path: str | None,
    default_environment: str,
) -> dict[str, Any]:
    detail = watcher.get("detail") if isinstance(watcher.get("detail"), dict) else {}
    raw_targets = detail.get("targets") if isinstance(detail.get("targets"), list) else []
    target_packets = [
        _target_packet(
            target,
            watcher_name=str(watcher.get("name") or "unknown"),
            registry_path=registry_path,
            default_environment=default_environment,
        )
        for target in raw_targets
        if isinstance(target, dict)
    ]
    blockers = sorted(
        {
            blocker
            for target in target_packets
            for blocker in target.get("blockers", [])
            if isinstance(blocker, str) and blocker
        }
    )
    if not target_packets:
        blockers.append("watcher_targets_missing")
    first_resolved = next((target for target in target_packets if target.get("resolved")), None)
    owner = first_resolved.get("owner") if isinstance(first_resolved, dict) else None
    return {
        "name": str(watcher.get("name") or "unknown"),
        "signal_source": str(watcher.get("signal_source") or "unknown"),
        "running": watcher.get("running") is True,
        "target_count": len(target_packets),
        "resolved_target_count": sum(1 for target in target_packets if target.get("resolved") is True),
        "owner": owner or {"owner_id": "unassigned", "source_refs": []},
        "targets": target_packets,
        "blockers": blockers,
    }


def _target_packet(
    target: dict[str, Any],
    *,
    watcher_name: str,
    registry_path: str | None,
    default_environment: str,
) -> dict[str, Any]:
    service = _first_text(target.get("deployment_name"), target.get("service"), watcher_name)
    environment = _first_text(target.get("environment"), default_environment, "unknown")
    try:
        boundary = build_ownership_boundary(
            registry_path=registry_path,
            signal_payload={
                "service": service,
                "deployment_name": service,
                "environment": environment,
                "kubernetes": {
                    "deployment_name": service,
                    "namespace": target.get("namespace"),
                },
            },
            default_environment=environment,
        )
    except (OSError, ValueError, SchemaValidationError) as exc:
        boundary = {
            "resolved": False,
            "record_id": "unresolved",
            "owner": {"owner_id": "unassigned", "source_refs": []},
            "tenant_id": "unknown",
            "customer_id": "unknown",
            "customer_boundary": "unknown",
            "approver_roles": [],
            "rollback_authority": {},
            "escalation_route": "",
            "allowed_action_classes": [],
            "blockers": [f"ownership_registry_invalid:{type(exc).__name__}"],
        }
    return {
        "service": service,
        "namespace": _first_text(target.get("namespace"), "unknown"),
        "kube_context": target.get("kube_context"),
        "environment": environment,
        "resolved": boundary.get("resolved") is True,
        "record_id": str(boundary.get("record_id") or "unresolved"),
        "owner": dict(boundary.get("owner") or {"owner_id": "unassigned", "source_refs": []}),
        "tenant_id": str(boundary.get("tenant_id") or "unknown"),
        "customer_id": str(boundary.get("customer_id") or "unknown"),
        "customer_boundary": str(boundary.get("customer_boundary") or "unknown"),
        "approver_roles": list(boundary.get("approver_roles") or []),
        "rollback_authority": dict(boundary.get("rollback_authority") or {}),
        "escalation_route": str(boundary.get("escalation_route") or ""),
        "allowed_action_classes": list(boundary.get("allowed_action_classes") or []),
        "blockers": list(boundary.get("blockers") or []),
    }


def _status(watchers: list[dict[str, Any]], unresolved_watchers: list[str]) -> str:
    if not watchers:
        return "empty"
    if unresolved_watchers:
        return "blocked"
    return "complete"


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"
