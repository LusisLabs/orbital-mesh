from __future__ import annotations

import time
from typing import Any

from .schema_validation import validate_payload


OPERATOR_HANDOFF_SCHEMA = "operator-handoff.schema.json"
OPERATOR_HANDOFF_VERSION = "mesh.operator_handoff.v1"
OPERATOR_HANDOFF_URGENCIES = frozenset({"low", "normal", "high", "critical"})


def build_operator_handoff(
    *,
    run_id: str,
    from_operator: dict[str, Any],
    to_operator: dict[str, Any],
    reason: str,
    next_action: str,
    handoff_id: str,
    related_event_id: str | None = None,
    urgency: str = "normal",
    due_at: str | None = None,
) -> dict[str, Any]:
    if not run_id.strip():
        raise ValueError("run_id is required")
    if not handoff_id.strip():
        raise ValueError("handoff_id is required")
    if not reason.strip():
        raise ValueError("handoff reason is required")
    if not next_action.strip():
        raise ValueError("handoff next_action is required")
    normalized_urgency = urgency.strip().lower() or "normal"
    if normalized_urgency not in OPERATOR_HANDOFF_URGENCIES:
        raise ValueError(f"unsupported handoff urgency: {urgency}")
    packet = {
        "schema_version": OPERATOR_HANDOFF_VERSION,
        "handoff_id": handoff_id.strip(),
        "run_id": run_id.strip(),
        "created_at": _timestamp(),
        "from_operator": _operator_record(from_operator),
        "to_operator": _operator_record(to_operator),
        "reason": reason.strip(),
        "next_action": next_action.strip(),
        "urgency": normalized_urgency,
        "status": "open",
        "related_event_id": related_event_id,
        "due_at": due_at.strip() if isinstance(due_at, str) and due_at.strip() else None,
    }
    validate_payload(OPERATOR_HANDOFF_SCHEMA, packet)
    return packet


def _operator_record(operator: dict[str, Any]) -> dict[str, Any]:
    operator_id = str(operator.get("operator_id") or "").strip()
    if not operator_id:
        raise ValueError("operator_id is required")
    return {
        "operator_id": operator_id,
        "roles": sorted(_roles(operator.get("roles"))),
        "source": str(operator.get("source") or "proxy_header").strip(),
    }


def _roles(raw: Any) -> set[str]:
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
