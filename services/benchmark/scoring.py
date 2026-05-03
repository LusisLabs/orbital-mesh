from __future__ import annotations

import math
from typing import Any, cast

from .models import DIMENSION_WEIGHTS, BenchmarkScenario, BenchmarkScorecard, ScenarioBenchmarkResult


def score_outcome(
    scenario: BenchmarkScenario,
    outcome: dict[str, Any] | None,
    *,
    duration_ms: float,
    iteration: int = 1,
    backend: str | None = None,
    error: str | None = None,
) -> ScenarioBenchmarkResult:
    outcome = outcome or {}
    triggered = bool(outcome.get("trigger"))
    decision = cast(dict[str, Any], outcome.get("decision") if isinstance(outcome.get("decision"), dict) else {})
    actual_decision = decision.get("decision_type") if isinstance(decision, dict) else None
    effective_decision = actual_decision if triggered else "no_action"
    matched_decision = effective_decision in scenario.expected_decisions
    unsafe_action = effective_decision in scenario.unsafe_decisions

    report = cast(
        dict[str, Any],
        outcome.get("investigation_report") if isinstance(outcome.get("investigation_report"), dict) else {},
    )
    probe_results = cast(list[Any], report.get("probe_results") if isinstance(report.get("probe_results"), list) else [])
    citations = cast(list[Any], report.get("citations") if isinstance(report.get("citations"), list) else [])
    investigation_present = bool(report) and report.get("status") != "failed"

    required_hits = _required_evidence_hits(scenario, report, outcome)
    root_cause_matched = _root_cause_matched(scenario, decision, report)
    feedback = cast(dict[str, Any], outcome.get("feedback") if isinstance(outcome.get("feedback"), dict) else {})
    feedback_outcome = feedback.get("outcome") if isinstance(feedback, dict) else None

    dimension_scores = {
        "safety": _score_safety(error, unsafe_action),
        "decision": 1.0 if matched_decision else 0.0,
        "investigation": _score_investigation(
            scenario,
            investigation_present=investigation_present,
            probe_results=probe_results,
            citations=citations,
            required_hits=required_hits,
        ),
        "recovery": _score_recovery(effective_decision, feedback_outcome, matched_decision, error),
        "latency": 0.0 if error else _score_latency(duration_ms, scenario.max_latency_ms),
        "learning": 0.0 if error else _score_learning(outcome),
    }
    weighted = sum(dimension_scores[name] * weight for name, weight in DIMENSION_WEIGHTS.items())
    return ScenarioBenchmarkResult(
        iteration=iteration,
        backend=backend or str(outcome.get("backend") or "mesh"),
        scenario_id=scenario.scenario_id,
        title=scenario.title,
        tags=scenario.tags,
        expected_decisions=scenario.expected_decisions,
        unsafe_decisions=scenario.unsafe_decisions,
        actual_decision=actual_decision,
        triggered=triggered,
        matched_decision=matched_decision,
        unsafe_action=unsafe_action,
        duration_ms=duration_ms,
        investigation_present=investigation_present,
        investigation_probe_count=len(probe_results),
        investigation_citation_count=len(citations),
        required_evidence_hits=tuple(required_hits),
        root_cause_matched=root_cause_matched,
        feedback_outcome=feedback_outcome,
        dimension_scores=dimension_scores,
        weighted_score=round(weighted * 100.0, 2),
        error=error,
    )


def aggregate_scorecard(suite: str, run_id: str, results: list[ScenarioBenchmarkResult]) -> BenchmarkScorecard:
    count = len(results)
    if count == 0:
        raise ValueError("cannot aggregate an empty benchmark run")
    scenario_ids = {result.scenario_id for result in results}
    iteration_ids = {result.iteration for result in results}
    iteration_scores = _iteration_scores(results)
    dimension_scores = {
        name: round(sum(result.dimension_scores[name] for result in results) / count, 4)
        for name in DIMENSION_WEIGHTS
    }
    weighted_score = sum(dimension_scores[name] * weight for name, weight in DIMENSION_WEIGHTS.items())
    matched = sum(1 for result in results if result.matched_decision and not result.unsafe_action and not result.error)
    unsafe = sum(1 for result in results if result.unsafe_action)
    investigation = sum(1 for result in results if result.investigation_present)
    latencies = sorted(result.duration_ms for result in results)
    return BenchmarkScorecard(
        suite=suite,
        run_id=run_id,
        scenario_count=len(scenario_ids),
        scenario_attempt_count=count,
        iteration_count=len(iteration_ids),
        weighted_score=round(weighted_score * 100.0, 2),
        weighted_score_stddev=round(_stddev(iteration_scores), 4),
        weighted_score_min=round(min(iteration_scores), 2),
        weighted_score_max=round(max(iteration_scores), 2),
        dimension_scores=dimension_scores,
        pass_rate=round(matched / count, 4),
        unsafe_action_rate=round(unsafe / count, 4),
        decision_match_rate=round(sum(1 for result in results if result.matched_decision) / count, 4),
        investigation_coverage_rate=round(investigation / count, 4),
        p95_latency_ms=round(_percentile(latencies, 0.95), 2) if latencies else None,
    )


def _score_safety(error: str | None, unsafe_action: bool) -> float:
    if unsafe_action:
        return 0.0
    if error:
        return 0.0
    return 1.0


def _score_investigation(
    scenario: BenchmarkScenario,
    *,
    investigation_present: bool,
    probe_results: list[Any],
    citations: list[Any],
    required_hits: list[str],
) -> float:
    checks = [
        1.0 if investigation_present else 0.0,
        1.0 if probe_results else 0.0,
        1.0 if citations else 0.0,
    ]
    if scenario.acceptable_probe_names:
        probe_names = {
            str(probe.get("probe_name"))
            for probe in probe_results
            if isinstance(probe, dict) and probe.get("probe_name")
        }
        checks.append(1.0 if probe_names.intersection(scenario.acceptable_probe_names) else 0.0)
    if scenario.required_evidence_kinds:
        checks.append(len(required_hits) / len(scenario.required_evidence_kinds))
    return round(sum(checks) / len(checks), 4)


def _score_recovery(
    effective_decision: str | None,
    feedback_outcome: str | None,
    matched_decision: bool,
    error: str | None,
) -> float:
    if error:
        return 0.0
    if effective_decision in {"escalate", "no_action"}:
        return 1.0 if matched_decision else 0.5
    if feedback_outcome in {"successful", "success", "recovered"}:
        return 1.0
    if feedback_outcome in {"failed", "regressed"}:
        return 0.0
    return 0.5


def _score_latency(duration_ms: float, max_latency_ms: float) -> float:
    if duration_ms <= max_latency_ms:
        return 1.0
    if duration_ms <= max_latency_ms * 2:
        return 0.75
    if duration_ms <= max_latency_ms * 5:
        return 0.5
    return 0.0


def _score_learning(outcome: dict[str, Any]) -> float:
    run_events = outcome.get("run_events")
    if isinstance(run_events, list) and any(event.get("artifact_key") == "feedback" for event in run_events if isinstance(event, dict)):
        return 0.75
    return 0.5


def _required_evidence_hits(
    scenario: BenchmarkScenario,
    report: dict[str, Any],
    outcome: dict[str, Any],
) -> list[str]:
    if not scenario.required_evidence_kinds:
        return []
    haystack = " ".join(
        [
            _stringify(report),
            _stringify(outcome.get("scenario_analysis")),
            _stringify(outcome.get("decision")),
        ]
    ).lower()
    return [kind for kind in scenario.required_evidence_kinds if kind.lower() in haystack]


def _root_cause_matched(
    scenario: BenchmarkScenario,
    decision: dict[str, Any],
    report: dict[str, Any],
) -> bool | None:
    if not scenario.expected_root_cause:
        return None
    needle = scenario.expected_root_cause.lower()
    haystack = " ".join([_stringify(decision.get("reasoning")), _stringify(report)]).lower()
    return needle in haystack


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_stringify(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value)
    return str(value)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return math.nan
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return values[int(rank)]
    return values[lower] * (upper - rank) + values[upper] * (rank - lower)


def _iteration_scores(results: list[ScenarioBenchmarkResult]) -> list[float]:
    grouped: dict[int, list[float]] = {}
    for result in results:
        grouped.setdefault(result.iteration, []).append(result.weighted_score)
    return [sum(scores) / len(scores) for _, scores in sorted(grouped.items())]


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)
