from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .schema_validation import validate_payload


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
    def from_dict(cls, payload: dict[str, Any]):
        validate_payload(cls.schema_name, payload)
        return cls(**payload)


@dataclass
class Trigger(ContractModel):
    schema_name: ClassVar[str] = "trigger.schema.json"
    trigger_id: str
    trigger_type: str
    triggered_at: str
    scope: dict[str, Any]
    symptoms: list[dict[str, Any]]
    dedupe_key: str
    related_changes: dict[str, Any] | None = None
    evidence_quality: dict[str, Any] | None = None


@dataclass
class Diagnosis(ContractModel):
    schema_name: ClassVar[str] = "diagnosis.schema.json"
    diagnosis_id: str
    trigger_id: str
    summary: str
    affected_scope: dict[str, Any]
    hypotheses: list[dict[str, Any]]
    candidate_remediations: list[str]


@dataclass
class RemediationPlan(ContractModel):
    schema_name: ClassVar[str] = "remediation-plan.schema.json"
    plan_id: str
    trigger_id: str
    diagnosis_id: str
    plan_type: str
    autonomy_tier: str
    goal: str
    confidence: float
    risk: dict[str, Any]
    steps: list[dict[str, Any]]
    stop_conditions: list[str]
    human_handoff_conditions: list[str]
    primary_hypothesis_id: str | None = None


@dataclass
class EvaluationResult(ContractModel):
    schema_name: ClassVar[str] = "evaluation-result.schema.json"
    evaluation_id: str
    plan_id: str
    passed: bool
    final_recommendation: str
    plan_results: dict[str, Any]
    step_results: dict[str, Any]
    blocking_reasons: list[str]
    review_route: str | None = None


@dataclass
class ExecutionRecord(ContractModel):
    schema_name: ClassVar[str] = "execution-record.schema.json"
    execution_id: str
    plan_id: str
    status: str
    started_at: str
    executor: str
    step_history: list[dict[str, Any]]
    completed_at: str | None = None
    failure: dict[str, Any] | None = None


@dataclass
class FeedbackRecord(ContractModel):
    schema_name: ClassVar[str] = "feedback-record.schema.json"
    feedback_id: str
    trigger_id: str
    plan_id: str
    execution_id: str
    measured_at: str
    window: str
    outcome: str
    metric_comparison: dict[str, Any]
    diagnosis_accuracy: dict[str, Any]
    plan_effectiveness: dict[str, Any]
    world_model_updates: dict[str, Any]
    recommended_follow_up: str | None = None
