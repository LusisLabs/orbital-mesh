from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DIMENSION_WEIGHTS: dict[str, float] = {
    "safety": 0.25,
    "decision": 0.20,
    "investigation": 0.20,
    "recovery": 0.15,
    "latency": 0.10,
    "learning": 0.10,
}


@dataclass(frozen=True)
class BenchmarkScenario:
    scenario_id: str
    title: str
    suite: str
    signal_fixture: str | None = None
    raw_signal: dict[str, Any] | None = None
    expected_decisions: tuple[str, ...] = ()
    unsafe_decisions: tuple[str, ...] = ()
    required_evidence_kinds: tuple[str, ...] = ()
    acceptable_probe_names: tuple[str, ...] = ()
    expected_root_cause: str | None = None
    tags: tuple[str, ...] = ()
    source: dict[str, Any] = field(default_factory=dict)
    max_latency_ms: float = 1000.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkScenario":
        raw_signal = payload.get("raw_signal")
        if raw_signal is not None and not isinstance(raw_signal, dict):
            raise ValueError("raw_signal must be an object when provided")
        if not payload.get("signal_fixture") and raw_signal is None:
            raise ValueError("benchmark scenario requires signal_fixture or raw_signal")
        return cls(
            scenario_id=str(payload["scenario_id"]),
            title=str(payload["title"]),
            suite=str(payload.get("suite", "golden")),
            signal_fixture=str(payload["signal_fixture"]) if payload.get("signal_fixture") else None,
            raw_signal=raw_signal,
            expected_decisions=tuple(str(item) for item in payload.get("expected_decisions", [])),
            unsafe_decisions=tuple(str(item) for item in payload.get("unsafe_decisions", [])),
            required_evidence_kinds=tuple(str(item) for item in payload.get("required_evidence_kinds", [])),
            acceptable_probe_names=tuple(str(item) for item in payload.get("acceptable_probe_names", [])),
            expected_root_cause=str(payload["expected_root_cause"]) if payload.get("expected_root_cause") else None,
            tags=tuple(str(item) for item in payload.get("tags", [])),
            source=dict(payload.get("source", {})),
            max_latency_ms=float(payload.get("max_latency_ms", 1000.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "suite": self.suite,
            "expected_decisions": list(self.expected_decisions),
            "unsafe_decisions": list(self.unsafe_decisions),
            "required_evidence_kinds": list(self.required_evidence_kinds),
            "acceptable_probe_names": list(self.acceptable_probe_names),
            "expected_root_cause": self.expected_root_cause,
            "tags": list(self.tags),
            "source": self.source,
            "max_latency_ms": self.max_latency_ms,
        }
        if self.signal_fixture:
            payload["signal_fixture"] = self.signal_fixture
        if self.raw_signal is not None:
            payload["raw_signal"] = self.raw_signal
        return payload


@dataclass(frozen=True)
class ScenarioBenchmarkResult:
    iteration: int
    backend: str
    scenario_id: str
    title: str
    tags: tuple[str, ...]
    expected_decisions: tuple[str, ...]
    unsafe_decisions: tuple[str, ...]
    actual_decision: str | None
    triggered: bool
    matched_decision: bool
    unsafe_action: bool
    duration_ms: float
    investigation_present: bool
    investigation_probe_count: int
    investigation_citation_count: int
    required_evidence_hits: tuple[str, ...]
    root_cause_matched: bool | None
    feedback_outcome: str | None
    dimension_scores: dict[str, float]
    weighted_score: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "backend": self.backend,
            "scenario_id": self.scenario_id,
            "title": self.title,
            "tags": list(self.tags),
            "expected_decisions": list(self.expected_decisions),
            "unsafe_decisions": list(self.unsafe_decisions),
            "actual_decision": self.actual_decision,
            "triggered": self.triggered,
            "matched_decision": self.matched_decision,
            "unsafe_action": self.unsafe_action,
            "duration_ms": self.duration_ms,
            "investigation_present": self.investigation_present,
            "investigation_probe_count": self.investigation_probe_count,
            "investigation_citation_count": self.investigation_citation_count,
            "required_evidence_hits": list(self.required_evidence_hits),
            "root_cause_matched": self.root_cause_matched,
            "feedback_outcome": self.feedback_outcome,
            "dimension_scores": self.dimension_scores,
            "weighted_score": self.weighted_score,
            "error": self.error,
        }


@dataclass(frozen=True)
class BenchmarkScorecard:
    suite: str
    run_id: str
    scenario_count: int
    scenario_attempt_count: int
    iteration_count: int
    weighted_score: float
    weighted_score_stddev: float
    weighted_score_min: float
    weighted_score_max: float
    dimension_scores: dict[str, float]
    pass_rate: float
    unsafe_action_rate: float
    decision_match_rate: float
    investigation_coverage_rate: float
    p95_latency_ms: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "run_id": self.run_id,
            "scenario_count": self.scenario_count,
            "scenario_attempt_count": self.scenario_attempt_count,
            "iteration_count": self.iteration_count,
            "weighted_score": self.weighted_score,
            "weighted_score_stddev": self.weighted_score_stddev,
            "weighted_score_min": self.weighted_score_min,
            "weighted_score_max": self.weighted_score_max,
            "dimension_scores": self.dimension_scores,
            "pass_rate": self.pass_rate,
            "unsafe_action_rate": self.unsafe_action_rate,
            "decision_match_rate": self.decision_match_rate,
            "investigation_coverage_rate": self.investigation_coverage_rate,
            "p95_latency_ms": self.p95_latency_ms,
            "dimension_weights": DIMENSION_WEIGHTS,
        }
