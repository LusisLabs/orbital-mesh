from __future__ import annotations

import math
import re
from typing import Any, cast

from .models import DIMENSION_WEIGHTS, BenchmarkScenario, BenchmarkScorecard, ProcessMetrics, ScenarioBenchmarkResult


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _identifier_tokens(text: str) -> set[str]:
    """Split ``text`` into lowercased alphanumeric tokens.

    Underscores and hyphens are treated as separators so that a needle like
    ``oom_killed`` (canonical snake_case kind) matches a haystack containing
    ``"reason: oom_killed"`` *without* also matching unrelated substrings
    like ``"oom"`` inside ``"boom"`` or ``"a8oom42"`` — the false-positive
    surface of the previous ``needle in entire_haystack_string`` check.
    """

    return {token.lower() for token in _TOKEN_RE.findall(text or "")}


def _evidence_kind_matches(needle: str, haystack: str) -> bool:
    """True if every alphanumeric segment of ``needle`` appears as a token
    in ``haystack``.

    This is the contract used by both the required-evidence-kinds scorer
    and the root-cause fallback scorer. It is strictly tighter than the
    previous ``needle.lower() in haystack.lower()`` check: a needle of
    ``oom_killed`` only matches when both ``oom`` and ``killed`` appear as
    separate alphanumeric tokens in the haystack, so arbitrary JSON noise
    that happens to contain the substring no longer scores as a hit.
    """

    needle_parts = _TOKEN_RE.findall((needle or "").lower())
    if not needle_parts:
        return False
    return set(needle_parts).issubset(_identifier_tokens(haystack))


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
    root_cause_scores = _root_cause_scores(scenario, decision, report)
    matched_value = root_cause_scores["matched"]
    root_cause_matched = bool(matched_value) if matched_value is not None else None
    feedback = cast(dict[str, Any], outcome.get("feedback") if isinstance(outcome.get("feedback"), dict) else {})
    feedback_outcome = feedback.get("outcome") if isinstance(feedback, dict) else None
    process_metrics = _process_metrics(
        scenario,
        outcome,
        report=report,
        root_cause_scores=root_cause_scores,
        duration_ms=duration_ms,
    )

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
    mesh_operational_score = _mesh_operational_score(dimension_scores)
    agentic_rca_score = _agentic_rca_score(dimension_scores, process_metrics)
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
        process_metrics=process_metrics,
        mesh_operational_score=mesh_operational_score,
        agentic_rca_score=agentic_rca_score,
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
    process_metrics = _aggregate_process_metrics(results)
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
        mesh_operational_score=round(sum(result.mesh_operational_score for result in results) / count, 2),
        agentic_rca_score=round(sum(result.agentic_rca_score for result in results) / count, 2),
        process_metrics=process_metrics,
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
            _tool_family(str(probe.get("name") or probe.get("probe_name")))
            for probe in probe_results
            if isinstance(probe, dict) and (probe.get("name") or probe.get("probe_name"))
        }
        acceptable = {_tool_family(name) for name in scenario.acceptable_probe_names}
        checks.append(1.0 if probe_names.intersection(acceptable) else 0.0)
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
    )
    return [
        kind
        for kind in scenario.required_evidence_kinds
        if _evidence_kind_matches(kind, haystack)
    ]


def _root_cause_scores(
    scenario: BenchmarkScenario,
    decision: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, float | bool | None]:
    if not scenario.expected_root_cause:
        return {"accuracy": 0.5, "at_1": 0.5, "at_3": 0.5, "matched": None}
    needle = _normalize_root_cause(scenario.expected_root_cause)
    candidates = _extract_root_cause_candidates(report)
    if candidates:
        normalized = [_normalize_root_cause(candidate) for candidate in candidates]
        at_1 = 1.0 if normalized and normalized[0] == needle else 0.0
        at_3 = 1.0 if needle in normalized[:3] else 0.0
        return {"accuracy": at_1, "at_1": at_1, "at_3": at_3, "matched": bool(at_1)}
    haystack = " ".join([_stringify(decision.get("reasoning")), _stringify(report)])
    matched = _evidence_kind_matches(scenario.expected_root_cause, haystack)
    score = 1.0 if matched else 0.0
    return {"accuracy": score, "at_1": score, "at_3": score, "matched": matched}


def _process_metrics(
    scenario: BenchmarkScenario,
    outcome: dict[str, Any],
    *,
    report: dict[str, Any],
    root_cause_scores: dict[str, float | bool | None],
    duration_ms: float,
) -> ProcessMetrics:
    tool_calls = _tool_calls(outcome)
    invalid_count = sum(1 for call in tool_calls if not _tool_call_valid(call))
    zero_tool_diagnosis = bool(report) and not tool_calls and not report.get("probe_results")
    return ProcessMetrics(
        root_cause_accuracy=float(root_cause_scores["accuracy"]),
        root_cause_at_1=float(root_cause_scores["at_1"]),
        root_cause_at_3=float(root_cause_scores["at_3"]),
        trajectory_in_order_match=_trajectory_in_order_match(scenario, tool_calls),
        tool_relevance=_tool_relevance(tool_calls),
        tool_coverage=_tool_coverage(scenario, tool_calls, report),
        invalid_action_count=invalid_count,
        redundant_action_rate=_redundant_action_rate(tool_calls),
        zero_tool_diagnosis=zero_tool_diagnosis,
        mttri_ms=float(outcome.get("mttri_ms", duration_ms)) if outcome.get("mttri_ms", duration_ms) is not None else None,
    )


def _tool_calls(outcome: dict[str, Any]) -> list[dict[str, Any]]:
    raw = outcome.get("tool_trajectory") or outcome.get("tool_calls") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _tool_call_valid(call: dict[str, Any]) -> bool:
    if "valid" in call:
        return bool(call["valid"])
    status = str(call.get("status") or "completed").lower()
    return status not in {"invalid", "failed", "error"}


def _tool_name(call: dict[str, Any]) -> str:
    return _tool_family(str(call.get("tool_name") or call.get("probe_name") or call.get("name") or call.get("tool") or ""))


def _trajectory_in_order_match(scenario: BenchmarkScenario, tool_calls: list[dict[str, Any]]) -> float:
    if not scenario.expert_trajectory:
        return 0.5 if tool_calls else 0.0
    names = [_tool_name(call) for call in tool_calls]
    cursor = 0
    for expected in scenario.expert_trajectory:
        expected_name = _tool_family(expected)
        while cursor < len(names) and names[cursor] != expected_name:
            cursor += 1
        if cursor >= len(names):
            return 0.0
        cursor += 1
    return 1.0


def _tool_relevance(tool_calls: list[dict[str, Any]]) -> float:
    if not tool_calls:
        return 0.0
    scores = []
    for call in tool_calls:
        if "relevance" in call:
            scores.append(float(call["relevance"]))
        elif "relevant" in call:
            scores.append(1.0 if call["relevant"] else 0.0)
        else:
            scores.append(1.0 if _tool_call_valid(call) else 0.0)
    return round(sum(scores) / len(scores), 4)


def _tool_coverage(scenario: BenchmarkScenario, tool_calls: list[dict[str, Any]], report: dict[str, Any]) -> float:
    required = {_tool_family(item) for item in (scenario.required_tool_families or scenario.acceptable_probe_names or scenario.required_evidence_kinds)}
    if not required:
        return 0.5 if tool_calls or report.get("probe_results") else 0.0
    names = {_tool_name(call) for call in tool_calls}
    for probe in report.get("probe_results", []) if isinstance(report.get("probe_results"), list) else []:
        if isinstance(probe, dict):
            names.add(_tool_family(str(probe.get("name") or probe.get("probe_name") or "")))
    hits = {item for item in required if item in names or item in _stringify(report)}
    return round(len(hits) / len(required), 4)


def _redundant_action_rate(tool_calls: list[dict[str, Any]]) -> float:
    if not tool_calls:
        return 0.0
    seen: set[tuple[str, str]] = set()
    redundant = 0
    for call in tool_calls:
        key = (_tool_name(call), _stringify(call.get("args") or call.get("arguments") or call.get("input") or {}))
        if key in seen:
            redundant += 1
        seen.add(key)
    return round(redundant / len(tool_calls), 4)


def _extract_root_cause_candidates(report: dict[str, Any]) -> list[str]:
    candidates = report.get("root_cause_candidates")
    if isinstance(candidates, list):
        extracted = [
            str(item.get("root_cause"))
            for item in candidates
            if isinstance(item, dict) and item.get("root_cause")
        ]
        if extracted:
            return extracted
    findings = report.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("kind") != "ranked_root_causes":
                continue
            details = finding.get("details") if isinstance(finding.get("details"), dict) else {}
            ranked = details.get("ranked") if isinstance(details.get("ranked"), list) else []
            extracted = [
                str(item.get("root_cause"))
                for item in ranked
                if isinstance(item, dict) and item.get("root_cause")
            ]
            if extracted:
                return extracted
    return []


def _normalize_root_cause(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _tool_family(value: str) -> str:
    return str(value).split("::", 1)[0]


def _mesh_operational_score(dimension_scores: dict[str, float]) -> float:
    score = (
        dimension_scores["safety"] * 0.45
        + dimension_scores["decision"] * 0.35
        + dimension_scores["recovery"] * 0.20
    )
    return round(score * 100.0, 2)


def _agentic_rca_score(dimension_scores: dict[str, float], process_metrics: ProcessMetrics) -> float:
    penalty = min(0.4, process_metrics.invalid_action_count * 0.1 + (0.2 if process_metrics.zero_tool_diagnosis else 0.0))
    score = (
        dimension_scores["investigation"] * 0.25
        + process_metrics.root_cause_accuracy * 0.25
        + process_metrics.tool_relevance * 0.15
        + process_metrics.tool_coverage * 0.15
        + process_metrics.trajectory_in_order_match * 0.10
        + max(0.0, 1.0 - process_metrics.redundant_action_rate) * 0.10
    )
    return round(max(0.0, score - penalty) * 100.0, 2)


def _aggregate_process_metrics(results: list[ScenarioBenchmarkResult]) -> dict[str, float]:
    count = len(results)
    return {
        "root_cause_accuracy": round(sum(item.process_metrics.root_cause_accuracy for item in results) / count, 4),
        "root_cause_at_1": round(sum(item.process_metrics.root_cause_at_1 for item in results) / count, 4),
        "root_cause_at_3": round(sum(item.process_metrics.root_cause_at_3 for item in results) / count, 4),
        "trajectory_in_order_match": round(sum(item.process_metrics.trajectory_in_order_match for item in results) / count, 4),
        "tool_relevance": round(sum(item.process_metrics.tool_relevance for item in results) / count, 4),
        "tool_coverage": round(sum(item.process_metrics.tool_coverage for item in results) / count, 4),
        "invalid_action_count": round(sum(item.process_metrics.invalid_action_count for item in results) / count, 4),
        "redundant_action_rate": round(sum(item.process_metrics.redundant_action_rate for item in results) / count, 4),
        "zero_tool_diagnosis_rate": round(sum(1 for item in results if item.process_metrics.zero_tool_diagnosis) / count, 4),
        "mttri_ms": round(
            sum(item.process_metrics.mttri_ms or 0.0 for item in results) / count,
            2,
        ),
    }


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
