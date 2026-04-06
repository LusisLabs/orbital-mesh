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
    environment: str
    service: str
    endpoint: str
    flag_key: str
    current_rollout_pct: int
    comparison_window: dict[str, str]
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
