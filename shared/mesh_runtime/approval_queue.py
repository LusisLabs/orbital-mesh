from __future__ import annotations

import time
from typing import Any, Iterable, Mapping, Sequence

from .control_plane_models import RunSession
from .run_events import APPROVAL_BLOCKED
from .schema_validation import validate_payload


APPROVAL_QUEUE_SCHEMA = "approval-queue.schema.json"
APPROVAL_QUEUE_VERSION = "mesh.approval_queue.v1"
_APPROVAL_READY_RECOMMENDATIONS = frozenset({"execute", "approve"})


def build_approval_queue_packet(
    sessions: Iterable[RunSession],
    events_by_run: Mapping[str, Sequence[Any]] | None = None,
    *,
    environment: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    events_by_run = events_by_run or {}
    items = [
        item
        for session in sessions
        if (item := _approval_queue_item(session, events_by_run.get(session.run_id, ()), environment=environment))
        is not None
    ]
    blocked_count = sum(1 for item in items if item["approval_state"] == "blocked")
    payload = {
        "schema_version": APPROVAL_QUEUE_VERSION,
        "generated_at": generated_at or _timestamp(),
        "status": "blocked" if blocked_count else "ready" if items else "empty",
        "pending_count": len(items),
        "blocked_count": blocked_count,
        "source_refs": ["state_store://run_sessions", "state_store://run_events"],
        "items": items,
    }
    validate_payload(APPROVAL_QUEUE_SCHEMA, payload)
    return payload


def _approval_queue_item(session: RunSession, events: Sequence[Any], *, environment: str) -> dict[str, Any] | None:
    if session.stage != "awaiting_operator" and session.status != "awaiting_operator":
        return None
    artifacts = session.artifacts if isinstance(session.artifacts, dict) else {}
    decision = _section(artifacts.get("decision"))
    evaluation = _section(artifacts.get("evaluation"))
    ownership = _section(artifacts.get("ownership_boundary"))
    input_signal = _section(artifacts.get("input_signal"))
    requested_by = artifacts.get("operator") if isinstance(artifacts.get("operator"), dict) else None
    blocked_event = _latest_approval_blocked_event(events)
    blockers = _blockers(blocked_event, evaluation)
    final_recommendation = _final_recommendation(blocked_event, evaluation)
    blocked = bool(blocked_event) or _evaluation_blocks_approval(evaluation, final_recommendation)
    return {
        "queue_id": f"approval://{session.run_id}",
        "run_id": session.run_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "scenario_key": session.scenario_key,
        "service": _string_or_none(input_signal.get("service") or ownership.get("service")),
        "namespace": _string_or_none(input_signal.get("namespace") or ownership.get("namespace")),
        "environment": _string_or_none(input_signal.get("environment")) or environment,
        "stage": session.stage,
        "pending_pause_stage": session.pending_pause_stage,
        "steering_mode": session.steering_mode,
        "decision_type": _string_or_none(decision.get("decision_type")),
        "risk_level": _string_or_none(decision.get("risk_level")),
        "final_recommendation": final_recommendation,
        "approval_state": "blocked" if blocked else "pending",
        "blockers": blockers,
        "requested_by": requested_by,
        "owner": ownership.get("owner") if isinstance(ownership.get("owner"), dict) else None,
        "approver_roles": _approver_roles(ownership),
        "allowed_commands": _allowed_commands(blocked),
        "evidence_refs": _evidence_refs(session, decision, evaluation, blocked_event),
        "latest_event_id": session.latest_event_id,
    }


def _latest_approval_blocked_event(events: Sequence[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        record = event.to_dict() if hasattr(event, "to_dict") else event
        if isinstance(record, dict) and record.get("event_type") == APPROVAL_BLOCKED:
            return record
    return None


def _blockers(blocked_event: dict[str, Any] | None, evaluation: dict[str, Any]) -> list[str]:
    event_payload = _section(blocked_event.get("payload") if blocked_event else None)
    raw = event_payload.get("blocking_reasons") or evaluation.get("blocking_reasons") or []
    if not isinstance(raw, list):
        raw = [raw]
    return [str(item) for item in raw if str(item).strip()]


def _final_recommendation(blocked_event: dict[str, Any] | None, evaluation: dict[str, Any]) -> str | None:
    event_payload = _section(blocked_event.get("payload") if blocked_event else None)
    return _string_or_none(event_payload.get("final_recommendation") or evaluation.get("final_recommendation"))


def _evaluation_blocks_approval(evaluation: dict[str, Any], final_recommendation: str | None) -> bool:
    if not evaluation:
        return False
    if evaluation.get("passed") is False:
        return True
    if final_recommendation and final_recommendation not in _APPROVAL_READY_RECOMMENDATIONS:
        return True
    return False


def _approver_roles(ownership: dict[str, Any]) -> list[str]:
    raw_roles = ownership.get("approver_roles")
    if isinstance(raw_roles, list):
        roles = [str(role) for role in raw_roles if str(role).strip()]
        if roles:
            return roles
    return ["approver", "admin"]


def _allowed_commands(blocked: bool) -> list[str]:
    if blocked:
        return ["explain_blockers", "override_decision", "cancel", "handoff"]
    return ["approve", "resume", "cancel", "handoff"]


def _evidence_refs(
    session: RunSession,
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    blocked_event: dict[str, Any] | None,
) -> list[str]:
    refs = [f"run://{session.run_id}"]
    if session.latest_event_id:
        refs.append(f"event://{session.latest_event_id}")
    if blocked_event and blocked_event.get("event_id"):
        refs.append(f"event://{blocked_event['event_id']}")
    for record in (decision, evaluation):
        raw_refs = record.get("evidence_refs") or record.get("required_evidence_refs") or []
        if isinstance(raw_refs, list):
            refs.extend(str(ref) for ref in raw_refs if str(ref).strip())
    return list(dict.fromkeys(refs))


def _section(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
