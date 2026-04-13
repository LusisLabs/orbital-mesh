from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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


@dataclass
class SteeringCommand(JsonModel):
    command_id: str
    run_id: str
    command_type: str
    issued_at: str
    payload: dict[str, Any] = field(default_factory=dict)


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


@dataclass
class IntegrationReadiness(JsonModel):
    checked_at: str
    promptfoo: IntegrationStatus
    hermes: IntegrationStatus
    goose: IntegrationStatus
    gitnexus: IntegrationStatus
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
