from __future__ import annotations

import time
from typing import Any

from .schema_validation import validate_payload


OVERRIDE_REVIEW_SCHEMA = "override-review.schema.json"
OVERRIDE_REVIEW_VERSION = "mesh.override_review.v1"
OVERRIDE_REVIEW_VERDICTS = frozenset({"accepted", "needs_followup", "rejected"})
OVERRIDE_REVIEW_COMMANDS = frozenset({"override_decision", "override_execution_parameters"})


def build_override_review(
    *,
    run_id: str,
    review_id: str,
    reviewer: dict[str, Any],
    override_command: dict[str, Any],
    verdict: str,
    reason: str,
    findings: list[str],
    action_items: list[str],
    related_event_id: str | None = None,
) -> dict[str, Any]:
    if not run_id.strip():
        raise ValueError("run_id is required")
    if not review_id.strip():
        raise ValueError("review_id is required")
    if not reason.strip():
        raise ValueError("override review reason is required")
    normalized_verdict = verdict.strip().lower()
    if normalized_verdict not in OVERRIDE_REVIEW_VERDICTS:
        raise ValueError(f"unsupported override review verdict: {verdict}")
    reviewer_record = _operator_record(reviewer)
    override_record = _override_command_record(override_command)
    override_operator_id = override_record["operator_id"]
    independent = override_operator_id is None or override_operator_id != reviewer_record["operator_id"]
    if not independent:
        raise ValueError("override reviewer must differ from override operator")
    packet = {
        "schema_version": OVERRIDE_REVIEW_VERSION,
        "review_id": review_id.strip(),
        "run_id": run_id.strip(),
        "created_at": _timestamp(),
        "reviewer": reviewer_record,
        "override_command": override_record,
        "independent_reviewer": independent,
        "verdict": normalized_verdict,
        "reason": reason.strip(),
        "findings": _strings(findings),
        "action_items": _strings(action_items),
        "related_event_id": related_event_id,
    }
    validate_payload(OVERRIDE_REVIEW_SCHEMA, packet)
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


def _override_command_record(command: dict[str, Any]) -> dict[str, Any]:
    event_id = str(command.get("event_id") or "").strip()
    command_id = str(command.get("command_id") or "").strip()
    command_type = str(command.get("command_type") or "").strip()
    issued_at = str(command.get("issued_at") or "").strip()
    if not event_id:
        raise ValueError("override command event_id is required")
    if not command_id:
        raise ValueError("override command command_id is required")
    if command_type not in OVERRIDE_REVIEW_COMMANDS:
        raise ValueError(f"unsupported override command type: {command_type}")
    if not issued_at:
        raise ValueError("override command issued_at is required")
    operator_id = command.get("operator_id")
    normalized_operator_id = str(operator_id).strip() if operator_id is not None and str(operator_id).strip() else None
    return {
        "event_id": event_id,
        "command_id": command_id,
        "command_type": command_type,
        "issued_at": issued_at,
        "operator_id": normalized_operator_id,
    }


def _roles(raw: Any) -> set[str]:
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _strings(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
