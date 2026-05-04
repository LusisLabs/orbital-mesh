from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar, TypeVar

from .schema_validation import validate_payload

ContractModelT = TypeVar("ContractModelT", bound="ContractModel")


@dataclass
class ContractModel:
    schema_name: ClassVar[str]

    def validate(self) -> None:
        validate_payload(self.schema_name, self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        validate_payload(self.schema_name, payload)
        return payload

    @classmethod
    def from_dict(cls: type[ContractModelT], payload: dict[str, Any]) -> ContractModelT:
        validate_payload(cls.schema_name, payload)
        return cls(**payload)


@dataclass
class Trigger(ContractModel):
    schema_name: ClassVar[str] = "trigger.schema.json"
    trigger_id: str
    trigger_type: str
    triggered_at: str
    environment: str
    service: str
    endpoint: str
    flag_key: str | None
    current_rollout_pct: int | None
    comparison_window: dict[str, str] | None
    segment: dict[str, Any]
    metrics: dict[str, Any]
    related_context: dict[str, Any]


@dataclass
class Decision(ContractModel):
    schema_name: ClassVar[str] = "decision.schema.json"
    decision_id: str
    trigger_id: str
    summary: str
    decision_type: str
    autonomy_tier: str
    reasoning: dict[str, Any]
    expected_outcome: dict[str, Any]
    risk: dict[str, Any]
    confidence: float
    execution_plan: dict[str, Any]


@dataclass
class EvidenceNode(ContractModel):
    schema_name: ClassVar[str] = "evidence-node.schema.json"
    evidence_id: str
    run_id: str | None
    analyzer: str
    kind: str
    summary: str
    payload: dict[str, Any]
    source_event_ids: list[str]
    confidence: float
    trusted: bool


@dataclass
class Subdecision(ContractModel):
    schema_name: ClassVar[str] = "subdecision.schema.json"
    subdecision_id: str
    analyzer: str
    recommendation: str
    confidence: float
    risk_level: str
    reasons: list[str]
    evidence_refs: list[str]
    requires_review: bool


@dataclass
class ScenarioAnalysis(ContractModel):
    schema_name: ClassVar[str] = "scenario-analysis.schema.json"
    analysis_id: str
    trigger_id: str
    created_at: str
    suggested_decision_type: str
    confidence: float
    risk_level: str
    autonomy_tier_hint: str
    required_review_reasons: list[str]
    evidence_refs: list[str]
    subdecisions: list[dict[str, Any]]
    evidence_nodes: list[dict[str, Any]]
    merkle_root: str | None = None
    merkle_event_ids: list[str] | None = None
    quality_measurements: dict[str, Any] | None = None


@dataclass
class InvestigationPlan(ContractModel):
    schema_name: ClassVar[str] = "investigation-plan.schema.json"
    plan_id: str
    trigger_id: str
    created_at: str
    objective: str
    probe_budget: dict[str, Any]
    probes: list[dict[str, Any]]


@dataclass
class InvestigationProbeResult(ContractModel):
    schema_name: ClassVar[str] = "investigation-probe-result.schema.json"
    probe_id: str
    name: str
    status: str
    started_at: str
    completed_at: str
    latency_ms: float
    summary: str
    findings: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    error: str | None = None


@dataclass
class InvestigationReport(ContractModel):
    schema_name: ClassVar[str] = "investigation-report.schema.json"
    report_id: str
    trigger_id: str
    created_at: str
    plan: dict[str, Any]
    probe_results: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    uncertainty: float
    stop_reason: str
    recommended_next_step: str
    safety_notes: list[str]


@dataclass
class RcaReport(ContractModel):
    schema_name: ClassVar[str] = "rca-report.schema.json"
    report_id: str
    trigger_id: str
    created_at: str
    likely_cause: str
    confidence: float
    supporting_evidence: list[str]
    disconfirming_evidence: list[str]
    ruled_out_causes: list[str]
    unknowns: list[str]
    evidence_checked: list[dict[str, Any]]
    recommended_next_step: str
    safety_reason: str


@dataclass
class MemoryCompactionRecord(ContractModel):
    schema_name: ClassVar[str] = "memory-compaction.schema.json"
    compaction_id: str
    run_id: str | None
    service: str
    created_at: str
    active_facts: list[dict[str, Any]]
    suppressed_facts: list[dict[str, Any]]
    source_event_ids: list[str]
    merkle_root: str | None = None


@dataclass
class ObservationRecord(ContractModel):
    schema_name: ClassVar[str] = "observation-record.schema.json"
    observation_id: str
    scope: dict[str, Any]
    kind: str
    content: str
    service: str | None
    run_id: str | None
    source_type: str
    source_refs: list[dict[str, Any]]
    created_at: str
    author: str
    tags: list[str]
    metadata: dict[str, Any]


@dataclass
class ClaimRecord(ContractModel):
    schema_name: ClassVar[str] = "claim-record.schema.json"
    claim_id: str
    statement: str
    entity_refs: list[str]
    supporting_observation_ids: list[str]
    contradicting_claim_ids: list[str]
    superseded_by: str | None
    confidence: float
    confidence_factors: dict[str, float]
    freshness: float
    tier: str
    state: str
    created_at: str
    updated_at: str


@dataclass
class RelationshipRecord(ContractModel):
    schema_name: ClassVar[str] = "relationship-record.schema.json"
    relationship_id: str
    from_id: str
    to_id: str
    type: str
    confidence: float
    supporting_observation_ids: list[str]
    state: str


@dataclass
class SupersessionRecord(ContractModel):
    schema_name: ClassVar[str] = "supersession-record.schema.json"
    supersession_id: str
    old_claim_id: str
    new_claim_id: str
    reason: str
    created_at: str
    created_by: str


@dataclass
class RetrievalRecord(ContractModel):
    schema_name: ClassVar[str] = "retrieval-record.schema.json"
    retrieval_id: str
    query: str
    scope: dict[str, Any]
    channels: list[str]
    candidate_ids: list[str]
    verified_ids: list[str]
    discarded_ids: list[str]
    created_at: str


@dataclass
class MemoryPacket(ContractModel):
    schema_name: ClassVar[str] = "memory-packet.schema.json"
    packet_id: str
    scope: dict[str, Any]
    observations: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    procedures: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    generated_at: str


@dataclass
class EvaluationResult(ContractModel):
    schema_name: ClassVar[str] = "evaluation-result.schema.json"
    evaluation_id: str
    decision_id: str
    passed: bool
    final_recommendation: str
    stage_results: dict[str, Any]
    blocking_reasons: list[str]
    review_route: str | None = None


@dataclass
class ExecutionRecord(ContractModel):
    schema_name: ClassVar[str] = "execution-record.schema.json"
    execution_id: str
    decision_id: str
    started_at: str
    completed_at: str
    executor: str
    status: str
    idempotency_key: str
    applied_action: dict[str, Any]
    external_refs: dict[str, Any]
    failure: dict[str, Any] | None = None


@dataclass
class FeedbackRecord(ContractModel):
    schema_name: ClassVar[str] = "feedback-record.schema.json"
    feedback_id: str
    decision_id: str
    execution_id: str
    measured_at: str
    window: str
    outcome: str
    metric_comparison: dict[str, Any]
    prediction_accuracy: dict[str, Any]
    side_effects: list[dict[str, Any] | str]
    world_model_updates: dict[str, Any]
    recommended_follow_up: str | None = None
    quality_measurements: dict[str, Any] | None = None
