from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class JsonModel:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoalRecord(JsonModel):
    goal_id: str
    title: str
    objective: str
    success_criteria: list[str]
    status: str
    created_at: str
    updated_at: str
    tags: list[str] = field(default_factory=list)
    note_path: str | None = None


@dataclass
class RunEvent(JsonModel):
    event_id: str
    run_id: str
    sequence: int
    stage: str
    event_type: str
    recorded_at: str
    payload: dict[str, Any]
    summary: dict[str, Any] | None = None
    merkle_leaf_hash: str | None = None
    artifact_key: str | None = None
    integration_name: str | None = None
    status: str | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "stage": self.stage,
            "event_type": self.event_type,
            "recorded_at": self.recorded_at,
            "payload": self.payload,
            "summary": self.summary,
            "artifact_key": self.artifact_key,
            "integration_name": self.integration_name,
            "status": self.status,
        }


@dataclass
class RunSession(JsonModel):
    run_id: str
    created_at: str
    updated_at: str
    goal_id: str | None
    scenario_key: str | None
    stage: str
    status: str
    steering_mode: str
    auto_mode: bool
    pause_points: list[str]
    pending_pause_stage: str | None
    evaluation_mode: str
    orchestration_mode: str
    latest_event_id: str | None
    latest_event_sequence: int
    latest_merkle_root: str | None
    operator_notes: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "goal_id": self.goal_id,
            "scenario_key": self.scenario_key,
            "stage": self.stage,
            "status": self.status,
            "steering_mode": self.steering_mode,
            "auto_mode": self.auto_mode,
            "pause_points": list(self.pause_points),
            "pending_pause_stage": self.pending_pause_stage,
            "evaluation_mode": self.evaluation_mode,
            "orchestration_mode": self.orchestration_mode,
            "latest_event_id": self.latest_event_id,
            "latest_event_sequence": self.latest_event_sequence,
            "latest_merkle_root": self.latest_merkle_root,
            "operator_notes": list(self.operator_notes),
            "artifacts": dict(self.artifacts),
            "error": self.error,
        }

    @classmethod
    def new(
        cls,
        *,
        goal_id: str | None,
        scenario_key: str | None,
        steering_mode: str,
        auto_mode: bool,
        pause_points: list[str],
        evaluation_mode: str,
        orchestration_mode: str,
        artifacts: dict[str, Any],
    ) -> RunSession:
        """Build a brand-new queued RunSession with a generated run_id.

        Shared factory used by every state backend so the construction
        logic lives in one place and backends cannot drift.
        """

        now = datetime.now(timezone.utc).isoformat()
        return cls(
            run_id=f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}",
            created_at=now,
            updated_at=now,
            goal_id=goal_id,
            scenario_key=scenario_key,
            stage="queued",
            status="queued",
            steering_mode=steering_mode,
            auto_mode=auto_mode,
            pause_points=list(pause_points),
            pending_pause_stage=None,
            evaluation_mode=evaluation_mode,
            orchestration_mode=orchestration_mode,
            latest_event_id=None,
            latest_event_sequence=0,
            latest_merkle_root=None,
            operator_notes=[],
            artifacts=deepcopy(artifacts),
            error=None,
        )


@dataclass
class SteeringCommand(JsonModel):
    command_id: str
    run_id: str
    command_type: str
    issued_at: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentAttemptThreadEvent(JsonModel):
    event_id: str
    thread_id: str
    sequence: int
    event_type: str
    recorded_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] | None = None
    status: str | None = None


@dataclass
class AgentAttemptThread(JsonModel):
    thread_id: str
    run_id: str
    task_id: str
    attempt_id: str
    agent: str
    adapter: str
    status: str
    created_at: str
    updated_at: str
    lifecycle: list[str] = field(default_factory=list)
    events: list[AgentAttemptThreadEvent] = field(default_factory=list)
    sandbox_ref: str | None = None
    harness: str | None = None
    released_at: str | None = None
    authority: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentAttempt(JsonModel):
    attempt_id: str
    task_id: str
    run_id: str
    agent: str
    adapter: str
    status: str
    started_at: str
    completed_at: str
    summary: str
    changed_files: list[str] = field(default_factory=list)
    test_results: list[dict[str, Any]] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    recommended_action: str = "human_review"
    output: dict[str, Any] = field(default_factory=dict)
    observations_proposed: list[dict[str, Any]] = field(default_factory=list)
    claims_proposed: list[dict[str, Any]] = field(default_factory=list)
    procedures_proposed: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    contradictions_detected: list[dict[str, Any]] = field(default_factory=list)
    memory_actions_requested: list[str] = field(default_factory=list)


@dataclass
class AgentTask(JsonModel):
    task_id: str
    run_id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    allowed_paths: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    kubernetes_scope: dict[str, Any] = field(default_factory=dict)
    memory_scope: dict[str, Any] = field(default_factory=dict)
    memory_packet: dict[str, Any] = field(default_factory=dict)
    memory_write_policy: dict[str, Any] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    orchestration_topology: dict[str, Any] = field(default_factory=dict)
    lane_routing: dict[str, Any] = field(default_factory=dict)
    attempts: list[AgentAttempt] = field(default_factory=list)
    selected_attempt_id: str | None = None


@dataclass
class IntegrationStatus(JsonModel):
    name: str
    ready: bool
    detail: str
    command: str | None = None
    url: str | None = None
    primary_route: str | None = None
    fallback_route: str | None = None
    warnings: list[str] = field(default_factory=list)
    certification: str = "mock"
    required_before: str = "local"
    posture: str = "configured"


@dataclass
class IntegrationReadiness(JsonModel):
    checked_at: str
    profile: str
    status: str
    required_checks: dict[str, Any]
    optional_checks: dict[str, Any]
    blockers: list[str]
    blocker_details: dict[str, Any]
    connector_certification: dict[str, Any]
    orchestration_topology: dict[str, Any]
    promptfoo: IntegrationStatus
    hermes: IntegrationStatus
    goose: IntegrationStatus
    latentmas: IntegrationStatus
    deepagents: IntegrationStatus
    centaur: IntegrationStatus
    zaxy: IntegrationStatus
    eventloom: IntegrationStatus
    neo4j_projection: IntegrationStatus
    zaxy_mcp: IntegrationStatus
    langgraph_checkpointing: IntegrationStatus
    vault_path: str
    state_path: str
    integrations_config_path: str


@dataclass
class MerkleProofStep(JsonModel):
    position: str
    hash: str


@dataclass
class MerkleSnapshot(JsonModel):
    run_id: str
    root_hash: str
    leaf_count: int
    event_ids: list[str]


@dataclass
class MerkleProof(JsonModel):
    run_id: str
    event_id: str
    leaf_hash: str
    root_hash: str
    proof: list[MerkleProofStep]
    valid: bool
