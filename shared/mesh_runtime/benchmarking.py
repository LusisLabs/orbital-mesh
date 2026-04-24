from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .json_store import LockedJsonFile


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SimulationScenario:
    scenario_id: str
    title: str
    signal_payload: dict[str, Any]
    expected_decision_type: str | None = None
    expected_outcome: str | None = None
    fault_type: str = "synthetic_signal"
    sandbox: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    standards_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SimulationScenario":
        return cls(
            scenario_id=str(payload["scenario_id"]),
            title=str(payload.get("title") or payload["scenario_id"]),
            signal_payload=dict(payload["signal_payload"]),
            expected_decision_type=payload.get("expected_decision_type"),
            expected_outcome=payload.get("expected_outcome"),
            fault_type=str(payload.get("fault_type") or "synthetic_signal"),
            sandbox=dict(payload.get("sandbox") or {}),
            tags=[str(item) for item in payload.get("tags", [])],
            standards_refs=[str(item) for item in payload.get("standards_refs", [])],
        )


@dataclass
class BenchmarkRecord:
    benchmark_id: str
    run_id: str
    scenario_id: str
    recorded_at: str
    score: float
    passed: bool
    dimensions: dict[str, Any]
    dataset_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkRecord":
        return cls(
            benchmark_id=str(payload["benchmark_id"]),
            run_id=str(payload["run_id"]),
            scenario_id=str(payload["scenario_id"]),
            recorded_at=str(payload["recorded_at"]),
            score=float(payload.get("score", 0.0)),
            passed=bool(payload.get("passed", False)),
            dimensions=dict(payload.get("dimensions") or {}),
            dataset_ref=payload.get("dataset_ref"),
        )


def score_run(
    *,
    scenario: SimulationScenario,
    session: dict[str, Any],
    events: list[dict[str, Any]],
) -> BenchmarkRecord:
    artifacts = session.get("artifacts", {}) if isinstance(session.get("artifacts"), dict) else {}
    decision = artifacts.get("decision", {}) if isinstance(artifacts.get("decision"), dict) else {}
    feedback = artifacts.get("feedback", {}) if isinstance(artifacts.get("feedback"), dict) else {}
    evaluation = artifacts.get("evaluation", {}) if isinstance(artifacts.get("evaluation"), dict) else {}
    no_trigger = session.get("status") in {"no_trigger", "completed"} and session.get("stage") == "no_trigger"
    no_action_control = scenario.expected_decision_type == "no_action" and no_trigger
    decision_match = (
        scenario.expected_decision_type is None
        or decision.get("decision_type") == scenario.expected_decision_type
        or no_action_control
    )
    outcome_match = (
        scenario.expected_outcome is None
        or feedback.get("outcome") == scenario.expected_outcome
        or (no_action_control and scenario.expected_outcome == "no_action_needed")
    )
    triggered = any(event.get("event_type") == "trigger_ready" for event in events)
    completed = session.get("status") in {"completed", "no_trigger"} or session.get("stage") in {"completed", "no_trigger"}
    no_hidden_reconciliation = "reconciliation" in artifacts or not artifacts.get("agent_tasks")
    dimensions = {
        "decision_match": decision_match,
        "outcome_match": outcome_match,
        "triggered": triggered,
        "completed": completed,
        "evaluation_recommendation": evaluation.get("final_recommendation"),
        "blocking_reason_count": len(evaluation.get("blocking_reasons", []))
        if isinstance(evaluation.get("blocking_reasons"), list)
        else 0,
        "reconciliation_recorded": "reconciliation" in artifacts,
    }
    trigger_ok = triggered or scenario.expected_decision_type == "no_action"
    blocking_reason_count = (
        len(evaluation.get("blocking_reasons", []))
        if isinstance(evaluation.get("blocking_reasons"), list)
        else 0
    )
    weights = {
        "decision_match": 0.35,
        "outcome_match": 0.2,
        "triggered": 0.15,
        "completed": 0.15,
        "reconciliation_visible": 0.1,
        "evaluation_unblocked": 0.05,
    }
    checks = {
        "decision_match": decision_match,
        "outcome_match": outcome_match,
        "triggered": trigger_ok,
        "completed": completed,
        "reconciliation_visible": no_hidden_reconciliation,
        "evaluation_unblocked": blocking_reason_count == 0,
    }
    hard_failures: list[str] = []
    if scenario.expected_decision_type and not decision_match:
        hard_failures.append("decision_mismatch")
    if not completed:
        hard_failures.append("run_incomplete")
    return BenchmarkRecord(
        benchmark_id=f"bench_{uuid4().hex[:12]}",
        run_id=str(session["run_id"]),
        scenario_id=scenario.scenario_id,
        recorded_at=utc_now(),
        score=round(sum(weights[name] for name, ok in checks.items() if ok), 4),
        passed=not hard_failures and sum(weights[name] for name, ok in checks.items() if ok) >= 0.8,
        dimensions={
            **dimensions,
            "blocking_reason_count": blocking_reason_count,
            "weighted_checks": checks,
            "weights": weights,
            "hard_failures": hard_failures,
        },
    )


class BenchmarkStore:
    def __init__(self, state_directory: str | Path, export_path: str | Path):
        self._state_dir = Path(state_directory)
        self._path = self._state_dir / "benchmarks" / "records.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._export_path = Path(export_path)
        self._export_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def export_path(self) -> Path:
        return self._export_path

    def record(self, record: BenchmarkRecord, dataset_row: dict[str, Any]) -> BenchmarkRecord:
        with LockedJsonFile(self._path) as payload:
            rows = payload.setdefault("benchmarks", [])
            rows.insert(0, record.to_dict())
            payload["benchmarks"] = rows[:1000]
        with self._export_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dataset_row, sort_keys=True, default=str) + "\n")
        return record

    def list(self, limit: int = 100) -> list[BenchmarkRecord]:
        if not self._path.exists():
            return []
        with LockedJsonFile(self._path) as payload:
            rows = payload.get("benchmarks", [])
        return [BenchmarkRecord.from_dict(row) for row in rows[:limit] if isinstance(row, dict)]

    def get(self, benchmark_id: str) -> BenchmarkRecord | None:
        for record in self.list(limit=1000):
            if record.benchmark_id == benchmark_id:
                return record
        return None


def dataset_row(
    *,
    scenario: SimulationScenario,
    session: dict[str, Any],
    events: list[dict[str, Any]],
    merkle: dict[str, Any],
    record: BenchmarkRecord,
) -> dict[str, Any]:
    artifacts = session.get("artifacts", {}) if isinstance(session.get("artifacts"), dict) else {}
    return {
        "benchmark": record.to_dict(),
        "simulation_context": artifacts.get("simulation_context", {}),
        "run": {
            "run_id": session.get("run_id"),
            "scenario_key": session.get("scenario_key"),
            "stage": session.get("stage"),
            "status": session.get("status"),
            "evaluation_mode": session.get("evaluation_mode"),
            "orchestration_mode": session.get("orchestration_mode"),
        },
        "scenario": scenario.to_dict(),
        "signal": artifacts.get("input_signal"),
        "decision": artifacts.get("decision"),
        "evaluation": artifacts.get("evaluation"),
        "agent_tasks": artifacts.get("agent_tasks", []),
        "service_agent": artifacts.get("service_agent"),
        "lane_routing": artifacts.get("lane_routing"),
        "reconciliation": artifacts.get("reconciliation"),
        "execution": artifacts.get("execution"),
        "feedback": artifacts.get("feedback"),
        "events": events,
        "merkle": merkle,
    }
