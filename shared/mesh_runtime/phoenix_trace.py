from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_SPAN_ORDER = (
    "trigger_ready",
    "evidence_pack_ready",
    "reasoning_bank_packet",
    "scenario_analysis_ready",
    "decision_ready",
    "evaluation_ready",
    "execution_recorded",
    "feedback_recorded",
    "reasoning_bank",
)


def build_phoenix_spans(task_trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Phoenix/OpenTelemetry-style spans without requiring Phoenix at runtime."""
    events = task_trace.get("events", []) if isinstance(task_trace, dict) else []
    spans: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event_type") == "integration_artifact_recorded" and event.get("artifact_key"):
            name = str(event.get("artifact_key"))
        else:
            name = str(event.get("event_type") or event.get("artifact_key") or event.get("stage") or "")
        if not name or name not in _SPAN_ORDER:
            continue
        spans.append(
            {
                "name": name,
                "span_kind": _span_kind(name),
                "timestamp": event.get("created_at") or _timestamp(),
                "attributes": {
                    "openinference.span.kind": _span_kind(name).upper(),
                    "mesh.stage": event.get("stage"),
                    "mesh.event_type": event.get("event_type"),
                    "mesh.artifact_key": event.get("artifact_key"),
                    "mesh.status": event.get("status"),
                },
                "input": _span_input(task_trace, name),
                "output": event.get("summary") or event.get("payload"),
            }
        )
    if not spans:
        spans.append(
            {
                "name": "mesh.task",
                "span_kind": "agent",
                "timestamp": _timestamp(),
                "attributes": {
                    "openinference.span.kind": "AGENT",
                    "mesh.trace_version": task_trace.get("trace_version"),
                },
                "input": task_trace.get("task"),
                "output": {
                    "failure_cause": task_trace.get("failure_cause"),
                    "tool_call_count": len(task_trace.get("tool_calls", []))
                    if isinstance(task_trace.get("tool_calls"), list)
                    else 0,
                },
            }
        )
    return spans


def _span_kind(name: str) -> str:
    if name in {"evidence_pack_ready", "reasoning_bank_packet"}:
        return "retriever"
    if name in {"decision_ready", "evaluation_ready", "scenario_analysis_ready"}:
        return "llm"
    if name in {"execution_recorded", "feedback_recorded"}:
        return "tool"
    return "agent"


def _span_input(task_trace: dict[str, Any], name: str) -> Any:
    if name == "trigger_ready":
        return task_trace.get("task")
    if name == "decision_ready":
        return task_trace.get("context")
    if name == "evaluation_ready":
        return task_trace.get("decision")
    if name in {"execution_recorded", "feedback_recorded"}:
        return task_trace.get("evaluation")
    return task_trace.get("task")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
