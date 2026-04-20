"""Agent self-observability — compute SLOs from run history.

SLOs computed over rolling windows (24h / 7d / 30d):

    mttr_seconds_p50, p95      — trigger_ready → successful feedback
    false_positive_rate        — runs that escalated to a human who then
                                 set "no_action" outcome
    rollback_rate              — executions that failed retries or were
                                 cancelled via steering
    auto_execution_rate        — runs completed without any steering command
    mean_time_to_detect_seconds — created_at → trigger_ready
    mean_time_to_decide_seconds — trigger_ready → decision_ready

Plus global counters:
    runs_per_hour, active_runs, active_runs_by_stage
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


_WINDOW_BUCKETS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


@dataclass
class SLOWindowMetrics:
    window: str
    total_runs: int = 0
    completed_runs: int = 0
    successful_runs: int = 0
    escalated_runs: int = 0
    false_positive_runs: int = 0
    rolled_back_runs: int = 0
    auto_execution_runs: int = 0
    mttr_p50_seconds: float | None = None
    mttr_p95_seconds: float | None = None
    mean_time_to_detect_seconds: float | None = None
    mean_time_to_decide_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        total = max(self.completed_runs, 1)
        return {
            "window": self.window,
            "total_runs": self.total_runs,
            "completed_runs": self.completed_runs,
            "successful_runs": self.successful_runs,
            "escalated_runs": self.escalated_runs,
            "false_positive_runs": self.false_positive_runs,
            "rolled_back_runs": self.rolled_back_runs,
            "auto_execution_runs": self.auto_execution_runs,
            "success_rate": round(self.successful_runs / total, 3) if self.completed_runs else None,
            "false_positive_rate": round(self.false_positive_runs / total, 3) if self.completed_runs else None,
            "rollback_rate": round(self.rolled_back_runs / total, 3) if self.completed_runs else None,
            "auto_execution_rate": round(self.auto_execution_runs / total, 3) if self.completed_runs else None,
            "mttr_p50_seconds": self.mttr_p50_seconds,
            "mttr_p95_seconds": self.mttr_p95_seconds,
            "mean_time_to_detect_seconds": self.mean_time_to_detect_seconds,
            "mean_time_to_decide_seconds": self.mean_time_to_decide_seconds,
        }


@dataclass
class AgentSLOReport:
    generated_at: str
    by_window: dict[str, SLOWindowMetrics] = field(default_factory=dict)
    active_runs: int = 0
    active_runs_by_stage: dict[str, int] = field(default_factory=dict)
    runs_per_hour_24h: float = 0.0
    per_service: dict[str, dict[str, Any]] = field(default_factory=dict)
    per_decision_type: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "windows": {w: m.to_dict() for w, m in self.by_window.items()},
            "active_runs": self.active_runs,
            "active_runs_by_stage": dict(self.active_runs_by_stage),
            "runs_per_hour_24h": round(self.runs_per_hour_24h, 3),
            "per_service": dict(self.per_service),
            "per_decision_type": dict(self.per_decision_type),
        }


class AgentSLOCalculator:
    """Computes SLO metrics from a list of RunSession-like objects."""

    def __init__(self, now_fn=None):
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def compute(self, runs: Iterable[Any]) -> AgentSLOReport:
        runs_list = list(runs)
        now = self._now()
        report = AgentSLOReport(generated_at=now.isoformat())

        # Classify active vs completed
        active_by_stage: dict[str, int] = defaultdict(int)
        completed: list[tuple[datetime, Any]] = []
        for session in runs_list:
            stage = _get(session, "stage", "unknown")
            status = _get(session, "status", "unknown")
            if status in ("queued", "running"):
                active_by_stage[stage] += 1
                continue
            ts = _parse_ts(_get(session, "updated_at"))
            if ts is not None:
                completed.append((ts, session))

        report.active_runs = sum(active_by_stage.values())
        report.active_runs_by_stage = dict(active_by_stage)

        # Per-window aggregation
        for window_name, delta in _WINDOW_BUCKETS.items():
            cutoff = now - delta
            window_runs = [session for ts, session in completed if ts >= cutoff]
            metrics = self._window_metrics(window_name, window_runs)
            report.by_window[window_name] = metrics

        # Runs per hour over last 24h
        last_24h = [s for ts, s in completed if ts >= now - timedelta(hours=24)]
        report.runs_per_hour_24h = len(last_24h) / 24.0

        # Per-service and per-decision_type breakdowns (last 7d)
        report.per_service = self._per_service(completed, cutoff=now - timedelta(days=7))
        report.per_decision_type = self._per_decision_type(completed, cutoff=now - timedelta(days=7))
        return report

    # ------------------------------------------------------------------

    def _window_metrics(self, window: str, runs: list[Any]) -> SLOWindowMetrics:
        metrics = SLOWindowMetrics(window=window)
        metrics.total_runs = len(runs)
        mttr_samples: list[float] = []
        detect_samples: list[float] = []
        decide_samples: list[float] = []

        for session in runs:
            status = _get(session, "status", "unknown")
            if status not in ("completed", "failed", "cancelled"):
                continue
            metrics.completed_runs += 1

            artifacts = _get(session, "artifacts", {}) or {}
            trigger = artifacts.get("trigger") or {}
            decision = artifacts.get("decision") or {}
            feedback = artifacts.get("feedback") or {}
            outcome = (feedback.get("outcome") if isinstance(feedback, dict) else None) or ""
            decision_type = (decision.get("decision_type") if isinstance(decision, dict) else None) or ""
            autonomy_tier = (decision.get("autonomy_tier") if isinstance(decision, dict) else None) or ""

            if outcome == "successful":
                metrics.successful_runs += 1
            if decision_type == "escalate" or autonomy_tier == "escalated":
                metrics.escalated_runs += 1
            if decision_type == "escalate" and outcome == "no_action_needed":
                metrics.false_positive_runs += 1
            if outcome in ("rolled_back", "regressed"):
                metrics.rolled_back_runs += 1
            if autonomy_tier == "autonomous" and status == "completed":
                metrics.auto_execution_runs += 1

            # MTTR: created_at → last event at resolution
            created_at = _parse_ts(_get(session, "created_at"))
            updated_at = _parse_ts(_get(session, "updated_at"))
            if created_at is not None and updated_at is not None and outcome == "successful":
                mttr_samples.append((updated_at - created_at).total_seconds())

            # Time-to-detect / decide from trigger triggered_at if present
            trigger_ts = _parse_ts(
                trigger.get("triggered_at") if isinstance(trigger, dict) else None
            ) or created_at
            # No separate decision timestamp persisted; use updated_at as upper bound.
            if created_at is not None and trigger_ts is not None and trigger_ts >= created_at:
                detect_samples.append((trigger_ts - created_at).total_seconds())
            if trigger_ts is not None and updated_at is not None and updated_at >= trigger_ts:
                decide_samples.append((updated_at - trigger_ts).total_seconds())

        metrics.mttr_p50_seconds = _percentile(mttr_samples, 0.50)
        metrics.mttr_p95_seconds = _percentile(mttr_samples, 0.95)
        metrics.mean_time_to_detect_seconds = _mean(detect_samples)
        metrics.mean_time_to_decide_seconds = _mean(decide_samples)
        return metrics

    def _per_service(
        self,
        completed: list[tuple[datetime, Any]],
        *,
        cutoff: datetime,
    ) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: {
            "total_runs": 0,
            "successful_runs": 0,
            "escalated_runs": 0,
        })
        for ts, session in completed:
            if ts < cutoff:
                continue
            artifacts = _get(session, "artifacts", {}) or {}
            trigger = artifacts.get("trigger") or {}
            service = (trigger.get("service") if isinstance(trigger, dict) else None) or "unknown"
            feedback = artifacts.get("feedback") or {}
            outcome = feedback.get("outcome") if isinstance(feedback, dict) else None
            decision = artifacts.get("decision") or {}
            decision_type = decision.get("decision_type") if isinstance(decision, dict) else None

            bucket = buckets[service]
            bucket["total_runs"] += 1
            if outcome == "successful":
                bucket["successful_runs"] += 1
            if decision_type == "escalate":
                bucket["escalated_runs"] += 1
        output: dict[str, dict[str, Any]] = {}
        for service, data in buckets.items():
            total = data["total_runs"]
            output[service] = {
                **data,
                "success_rate": round(data["successful_runs"] / total, 3) if total else None,
                "escalation_rate": round(data["escalated_runs"] / total, 3) if total else None,
            }
        return output

    def _per_decision_type(
        self,
        completed: list[tuple[datetime, Any]],
        *,
        cutoff: datetime,
    ) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"total_runs": 0, "successful_runs": 0})
        for ts, session in completed:
            if ts < cutoff:
                continue
            artifacts = _get(session, "artifacts", {}) or {}
            decision = artifacts.get("decision") or {}
            decision_type = (decision.get("decision_type") if isinstance(decision, dict) else None) or "unknown"
            feedback = artifacts.get("feedback") or {}
            outcome = feedback.get("outcome") if isinstance(feedback, dict) else None
            bucket = buckets[decision_type]
            bucket["total_runs"] += 1
            if outcome == "successful":
                bucket["successful_runs"] += 1
        output: dict[str, dict[str, Any]] = {}
        for dtype, data in buckets.items():
            total = data["total_runs"]
            output[dtype] = {
                **data,
                "success_rate": round(data["successful_runs"] / total, 3) if total else None,
            }
        return output


# ----------------------------------------------------------------------
# Prometheus exposition
# ----------------------------------------------------------------------


def report_to_prometheus(report: AgentSLOReport) -> str:
    """Convert an SLO report to Prometheus text-format metrics."""
    lines: list[str] = []

    def _metric(name: str, help_text: str, metric_type: str = "gauge") -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")

    def _sample(name: str, value: Any, labels: dict[str, str] | None = None) -> None:
        if value is None:
            return
        if labels:
            label_str = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")

    # Active gauges
    _metric("mesh_agent_active_runs", "Active (queued or running) mesh runs")
    _sample("mesh_agent_active_runs", report.active_runs)

    _metric("mesh_agent_active_runs_by_stage", "Active runs grouped by stage")
    for stage, count in report.active_runs_by_stage.items():
        _sample("mesh_agent_active_runs_by_stage", count, {"stage": stage})

    _metric("mesh_agent_runs_per_hour_24h", "Completed runs per hour over last 24h")
    _sample("mesh_agent_runs_per_hour_24h", round(report.runs_per_hour_24h, 3))

    # Per-window aggregates
    _metric("mesh_agent_completed_runs", "Completed runs in window", "counter")
    _metric("mesh_agent_success_rate", "Success rate (successful / completed)")
    _metric("mesh_agent_false_positive_rate", "False-positive rate (escalations later marked no_action_needed)")
    _metric("mesh_agent_rollback_rate", "Rollback rate (runs with rolled_back/regressed outcome)")
    _metric("mesh_agent_auto_execution_rate", "Share of runs completing autonomously")
    _metric("mesh_agent_mttr_p50_seconds", "MTTR p50 (created_at -> successful feedback)")
    _metric("mesh_agent_mttr_p95_seconds", "MTTR p95")

    for window, metrics in report.by_window.items():
        labels = {"window": window}
        data = metrics.to_dict()
        _sample("mesh_agent_completed_runs", metrics.completed_runs, labels)
        _sample("mesh_agent_success_rate", _num(data["success_rate"]), labels)
        _sample("mesh_agent_false_positive_rate", _num(data["false_positive_rate"]), labels)
        _sample("mesh_agent_rollback_rate", _num(data["rollback_rate"]), labels)
        _sample("mesh_agent_auto_execution_rate", _num(data["auto_execution_rate"]), labels)
        _sample("mesh_agent_mttr_p50_seconds", _num(metrics.mttr_p50_seconds), labels)
        _sample("mesh_agent_mttr_p95_seconds", _num(metrics.mttr_p95_seconds), labels)

    # Per-service (last 7d)
    _metric("mesh_agent_service_total_runs", "Total runs per service (last 7d)", "counter")
    _metric("mesh_agent_service_success_rate", "Success rate per service (last 7d)")
    for service, data in report.per_service.items():
        labels = {"service": service}
        _sample("mesh_agent_service_total_runs", data["total_runs"], labels)
        _sample("mesh_agent_service_success_rate", _num(data.get("success_rate")), labels)

    # Per-decision-type (last 7d)
    _metric("mesh_agent_decision_total_runs", "Total runs per decision type (last 7d)", "counter")
    _metric("mesh_agent_decision_success_rate", "Success rate per decision type (last 7d)")
    for dtype, data in report.per_decision_type.items():
        labels = {"decision_type": dtype}
        _sample("mesh_agent_decision_total_runs", data["total_runs"], labels)
        _sample("mesh_agent_decision_success_rate", _num(data.get("success_rate")), labels)

    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _get(obj: Any, attr: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


def _percentile(samples: list[float], p: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    k = int(round((len(ordered) - 1) * p))
    return round(ordered[k], 3)


def _mean(samples: list[float]) -> float | None:
    if not samples:
        return None
    return round(sum(samples) / len(samples), 3)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
