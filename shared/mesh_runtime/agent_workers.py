from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .control_plane_models import AgentAttempt, AgentAttemptThread, AgentAttemptThreadEvent, AgentTask


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

MODEL_BOUND_AGENT_WORKERS = (
    "goose",
    "hermes",
    "codex",
    "claudecode",
    "openclaw",
    "deepagents",
    "latentmas",
)

PROPOSAL_ONLY_ATTEMPT_AGENTS = frozenset(
    {
        "goose",
        "hermes",
        "codex",
        "claudecode",
        "openclaw",
        "deepagents",
        "airflow",
        "temporal",
        "dagster",
        "prefect",
        "flyte",
        "luigi",
        "oozie",
        "n8n",
    }
)
ADVISORY_ONLY_ATTEMPT_AGENTS = frozenset({"latentmas"})
PROPOSAL_ONLY_ADAPTERS = frozenset({"deepagents", "langgraph", "centaur"})
ADVISORY_ONLY_ADAPTERS = frozenset({"latentmas_http"})


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
    thread: AgentAttemptThread | dict[str, Any] | None = None,
) -> AgentAttempt:
    now = _timestamp()
    output_payload = dict(output or {})
    output_payload["authority"] = _merge_authority_record(
        output_payload.get("authority"),
        agent=agent,
        adapter=adapter,
    )
    if thread is not None and "thread" not in output_payload:
        output_payload["thread"] = thread.to_dict() if isinstance(thread, AgentAttemptThread) else dict(thread)
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
        output=output_payload,
        observations_proposed=list(observations_proposed or []),
        claims_proposed=list(claims_proposed or []),
        procedures_proposed=list(procedures_proposed or []),
        citations=list(citations or []),
        contradictions_detected=list(contradictions_detected or []),
        memory_actions_requested=list(memory_actions_requested or []),
    )


def build_agent_attempt_thread(
    *,
    attempt_id: str,
    task_id: str,
    run_id: str,
    agent: str,
    adapter: str,
    status: str,
    started_at: str | None = None,
    completed_at: str | None = None,
    sandbox_ref: str | None = None,
    harness: str | None = None,
    events: list[AgentAttemptThreadEvent] | None = None,
    request: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    output: dict[str, Any] | None = None,
    risk_flags: list[str] | None = None,
    test_results: list[dict[str, Any]] | None = None,
    release_status: dict[str, Any] | None = None,
) -> AgentAttemptThread:
    created_at = started_at or _timestamp()
    updated_at = completed_at or created_at
    thread_id = f"thread_{task_id}_{agent}_{adapter}"
    thread_events = list(events or [])
    if not thread_events:
        thread_events.append(
            AgentAttemptThreadEvent(
                event_id=f"{thread_id}_event_1",
                thread_id=thread_id,
                sequence=1,
                event_type="agent_attempt_terminal",
                recorded_at=updated_at,
                payload={
                    "attempt_id": attempt_id,
                    "agent": agent,
                    "adapter": adapter,
                    "status": status,
                    "authority": "mesh_agent_attempt_projection",
                },
                summary={"status": status},
                status=status,
            )
        )
    return AgentAttemptThread(
        thread_id=thread_id,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        agent=agent,
        adapter=adapter,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        lifecycle=["spawn_or_reuse_runtime", "persist_message", "execute", "stream_or_replay_events", "release"],
        events=thread_events,
        sandbox_ref=sandbox_ref,
        harness=harness,
        released_at=updated_at if status in {"completed", "failed", "cancelled"} else None,
        request=dict(request or {}),
        tool_calls=list(tool_calls or []),
        output=dict(output or {}),
        risk_flags=list(risk_flags or []),
        test_results=list(test_results or []),
        release_status=dict(release_status or {}),
        authority={
            "state_slice": "mesh.agent_attempt_thread.v1",
            "mesh_control_plane_authoritative": True,
            "agent_thread_authoritative": False,
            "policy_approval_actuation_allowed": False,
            "production_actuation_allowed": False,
            "final_run_state_owned_by_mesh": True,
        },
    )


def ensure_agent_attempt_thread(attempt: AgentAttempt, *, task: AgentTask) -> AgentAttempt:
    if isinstance(attempt.output, dict) and isinstance(attempt.output.get("thread"), dict):
        return attempt
    output = dict(attempt.output)
    output["thread"] = build_agent_attempt_thread(
        attempt_id=attempt.attempt_id,
        task_id=task.task_id,
        run_id=task.run_id,
        agent=attempt.agent,
        adapter=attempt.adapter,
        status=attempt.status,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        harness=_harness_for_attempt(attempt),
        request=_thread_request_from_attempt(attempt),
        tool_calls=_thread_tool_calls_from_attempt(attempt),
        output=_thread_output_from_attempt(attempt),
        risk_flags=list(attempt.risk_flags),
        test_results=list(attempt.test_results),
        release_status=_thread_release_status_from_attempt(attempt),
    ).to_dict()
    attempt.output = output
    return attempt


def _harness_for_attempt(attempt: AgentAttempt) -> str:
    if attempt.adapter == "native_contract":
        return "mesh-native-contract"
    if attempt.adapter == "native_orchestration_contract":
        return "mesh-native-orchestration-contract"
    return attempt.adapter


def _thread_request_from_attempt(attempt: AgentAttempt) -> dict[str, Any]:
    output = attempt.output if isinstance(attempt.output, dict) else {}
    request = output.get("sandbox_request") if isinstance(output.get("sandbox_request"), dict) else {}
    return dict(request)


def _thread_tool_calls_from_attempt(attempt: AgentAttempt) -> list[dict[str, Any]]:
    output = attempt.output if isinstance(attempt.output, dict) else {}
    calls = output.get("tool_calls") if isinstance(output.get("tool_calls"), list) else []
    return [dict(item) for item in calls if isinstance(item, dict)]


def _thread_output_from_attempt(attempt: AgentAttempt) -> dict[str, Any]:
    output = attempt.output if isinstance(attempt.output, dict) else {}
    centaur_output = output.get("centaur_output")
    if isinstance(centaur_output, dict):
        return dict(centaur_output)
    proposal_output = output.get("proposal_output")
    return dict(proposal_output) if isinstance(proposal_output, dict) else {}


def _thread_release_status_from_attempt(attempt: AgentAttempt) -> dict[str, Any]:
    thread_output = _thread_output_from_attempt(attempt)
    release = thread_output.get("release")
    if isinstance(release, dict):
        return dict(release)
    return {}


def _merge_authority_record(
    existing: Any,
    *,
    agent: str,
    adapter: str,
) -> dict[str, Any]:
    authority = {
        "state_slice": "mesh.agent_attempt_thread.v1",
        "mesh_control_plane_authoritative": True,
        "agent_attempt_authoritative": False,
        "agent_thread_authoritative": False,
        "policy_approval_actuation_allowed": False,
        "production_actuation_allowed": False,
        "final_run_state_owned_by_mesh": True,
        "boundary": _authority_boundary(agent=agent, adapter=adapter),
    }
    if isinstance(existing, dict):
        authority.update(existing)
        authority["state_slice"] = "mesh.agent_attempt_thread.v1"
        authority["mesh_control_plane_authoritative"] = True
        authority["agent_attempt_authoritative"] = False
        authority["agent_thread_authoritative"] = False
        authority["policy_approval_actuation_allowed"] = False
        authority["production_actuation_allowed"] = False
        authority["final_run_state_owned_by_mesh"] = True
        authority["boundary"] = _authority_boundary(agent=agent, adapter=adapter)
    return authority


def _authority_boundary(*, agent: str, adapter: str) -> str:
    if agent == "kubernetes" and adapter == "native_orchestration_contract":
        return "kubernetes_bounded_action_candidate_requires_mesh_authority_and_allowlists"
    if agent in ADVISORY_ONLY_ATTEMPT_AGENTS or adapter in ADVISORY_ONLY_ADAPTERS:
        return "advisory_only"
    if agent in PROPOSAL_ONLY_ATTEMPT_AGENTS or adapter in PROPOSAL_ONLY_ADAPTERS or adapter == "native_contract":
        return "proposal_only"
    return "mesh_native_projection"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
