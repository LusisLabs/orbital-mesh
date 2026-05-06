from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .control_plane_models import AgentAttempt, AgentTask


NATIVE_ORCHESTRATION_PLATFORM_WORKERS = (
    "airflow",
    "temporal",
    "dagster",
    "prefect",
    "flyte",
    "luigi",
    "oozie",
    "kubernetes",
    "n8n",
)

DEFAULT_AGENT_WORKERS = (
    "goose",
    "hermes",
    "codex",
    "claudecode",
    "openclaw",
    *NATIVE_ORCHESTRATION_PLATFORM_WORKERS,
)


def build_agent_task(
    *,
    run_id: str,
    kind: str,
    allowed_paths: list[str] | None = None,
    test_commands: list[str] | None = None,
    kubernetes_scope: dict[str, Any] | None = None,
    memory_scope: dict[str, Any] | None = None,
    memory_packet: dict[str, Any] | None = None,
    memory_write_policy: dict[str, Any] | None = None,
    open_questions: list[str] | None = None,
    agents: list[str] | None = None,
    orchestration_topology: dict[str, Any] | None = None,
    lane_routing: dict[str, Any] | None = None,
) -> AgentTask:
    now = _timestamp()
    selected_agents = agents or list(DEFAULT_AGENT_WORKERS)
    return AgentTask(
        task_id=f"task_{run_id}_{kind}_{uuid4().hex[:8]}",
        run_id=run_id,
        kind=kind,
        status="queued",
        created_at=now,
        updated_at=now,
        allowed_paths=list(allowed_paths or []),
        test_commands=list(test_commands or []),
        kubernetes_scope=dict(kubernetes_scope or {}),
        memory_scope=dict(memory_scope or {}),
        memory_packet=dict(memory_packet or {}),
        memory_write_policy=dict(memory_write_policy or {}),
        open_questions=list(open_questions or []),
        agents=selected_agents,
        orchestration_topology=dict(orchestration_topology or {}),
        lane_routing=dict(lane_routing or {}),
        attempts=[],
    )


def build_agent_attempt(
    *,
    task_id: str,
    run_id: str,
    agent: str,
    adapter: str,
    status: str,
    summary: str,
    changed_files: list[str] | None = None,
    test_results: list[dict[str, Any]] | None = None,
    risk_flags: list[str] | None = None,
    recommended_action: str = "human_review",
    output: dict[str, Any] | None = None,
    observations_proposed: list[dict[str, Any]] | None = None,
    claims_proposed: list[dict[str, Any]] | None = None,
    procedures_proposed: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    contradictions_detected: list[dict[str, Any]] | None = None,
    memory_actions_requested: list[str] | None = None,
) -> AgentAttempt:
    now = _timestamp()
    return AgentAttempt(
        attempt_id=f"attempt_{task_id}_{agent}_{uuid4().hex[:8]}",
        task_id=task_id,
        run_id=run_id,
        agent=agent,
        adapter=adapter,
        status=status,
        started_at=now,
        completed_at=now,
        summary=summary,
        changed_files=list(changed_files or []),
        test_results=list(test_results or []),
        risk_flags=list(risk_flags or []),
        recommended_action=recommended_action,
        output=dict(output or {}),
        observations_proposed=list(observations_proposed or []),
        claims_proposed=list(claims_proposed or []),
        procedures_proposed=list(procedures_proposed or []),
        citations=list(citations or []),
        contradictions_detected=list(contradictions_detected or []),
        memory_actions_requested=list(memory_actions_requested or []),
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
