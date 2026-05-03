from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class ScenarioDelta:
    scenario_id: str
    baseline_score: float | None
    candidate_score: float | None
    score_delta: float | None
    baseline_decision: str | None
    candidate_decision: str | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "baseline_score": self.baseline_score,
            "candidate_score": self.candidate_score,
            "score_delta": self.score_delta,
            "baseline_decision": self.baseline_decision,
            "candidate_decision": self.candidate_decision,
            "status": self.status,
        }


@dataclass(frozen=True)
class BenchmarkComparison:
    baseline_run_id: str
    candidate_run_id: str
    baseline_suite: str
    candidate_suite: str
    weighted_score_delta: float
    dimension_deltas: dict[str, float]
    pass_rate_delta: float
    unsafe_action_rate_delta: float
    p95_latency_delta_ms: float | None
    scenario_deltas: list[ScenarioDelta]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id,
            "candidate_run_id": self.candidate_run_id,
            "baseline_suite": self.baseline_suite,
            "candidate_suite": self.candidate_suite,
            "weighted_score_delta": self.weighted_score_delta,
            "dimension_deltas": self.dimension_deltas,
            "pass_rate_delta": self.pass_rate_delta,
            "unsafe_action_rate_delta": self.unsafe_action_rate_delta,
            "p95_latency_delta_ms": self.p95_latency_delta_ms,
            "scenario_deltas": [delta.to_dict() for delta in self.scenario_deltas],
            "warnings": self.warnings,
        }


def compare_benchmark_runs(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    output_dir: Path | None = None,
) -> BenchmarkComparison:
    baseline = _load_run(baseline_dir)
    candidate = _load_run(candidate_dir)
    comparison = _compare_payloads(baseline, candidate)
    destination = output_dir or candidate_dir
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "comparison.json").write_text(
        json.dumps(comparison.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "comparison.md").write_text(render_comparison_markdown(comparison), encoding="utf-8")
    return comparison


def render_comparison_markdown(comparison: BenchmarkComparison) -> str:
    lines = [
        "# Mesh Benchmark Comparison",
        "",
        f"- Baseline: `{comparison.baseline_run_id}`",
        f"- Candidate: `{comparison.candidate_run_id}`",
        f"- Weighted score delta: **{comparison.weighted_score_delta:+.2f}**",
        f"- Pass-rate delta: {comparison.pass_rate_delta:+.2%}",
        f"- Unsafe-action-rate delta: {comparison.unsafe_action_rate_delta:+.2%}",
    ]
    if comparison.p95_latency_delta_ms is not None:
        lines.append(f"- P95 latency delta: {comparison.p95_latency_delta_ms:+.2f} ms")
    if comparison.warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in comparison.warnings:
            lines.append(f"- {warning}")
    lines.extend([
        "",
        "## Dimension Deltas",
        "",
        "| Dimension | Delta |",
        "| --- | ---: |",
    ])
    for name, delta in comparison.dimension_deltas.items():
        lines.append(f"| {name} | {delta:+.2%} |")
    lines.extend([
        "",
        "## Scenario Deltas",
        "",
        "| Scenario | Baseline | Candidate | Delta | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ])
    for delta in comparison.scenario_deltas:
        baseline = _format_optional_score(delta.baseline_score)
        candidate = _format_optional_score(delta.candidate_score)
        score_delta = "" if delta.score_delta is None else f"{delta.score_delta:+.2f}"
        lines.append(f"| {delta.scenario_id} | {baseline} | {candidate} | {score_delta} | {delta.status} |")
    return "\n".join(lines) + "\n"


def _compare_payloads(baseline: dict[str, Any], candidate: dict[str, Any]) -> BenchmarkComparison:
    baseline_scorecard = cast(dict[str, Any], baseline["scorecard"])
    candidate_scorecard = cast(dict[str, Any], candidate["scorecard"])
    warnings: list[str] = []
    if baseline_scorecard.get("suite") != candidate_scorecard.get("suite"):
        warnings.append(
            f"suite differs: baseline={baseline_scorecard.get('suite')} "
            f"candidate={candidate_scorecard.get('suite')}"
        )
    baseline_scenarios = _scenario_index(cast(list[dict[str, Any]], baseline.get("results", [])))
    candidate_scenarios = _scenario_index(cast(list[dict[str, Any]], candidate.get("results", [])))
    scenario_ids = sorted(set(baseline_scenarios) | set(candidate_scenarios))
    scenario_deltas = [
        _scenario_delta(scenario_id, baseline_scenarios.get(scenario_id), candidate_scenarios.get(scenario_id))
        for scenario_id in scenario_ids
    ]
    return BenchmarkComparison(
        baseline_run_id=str(baseline.get("run_id")),
        candidate_run_id=str(candidate.get("run_id")),
        baseline_suite=str(baseline_scorecard.get("suite")),
        candidate_suite=str(candidate_scorecard.get("suite")),
        weighted_score_delta=round(
            float(candidate_scorecard.get("weighted_score", 0.0))
            - float(baseline_scorecard.get("weighted_score", 0.0)),
            2,
        ),
        dimension_deltas=_dimension_deltas(baseline_scorecard, candidate_scorecard),
        pass_rate_delta=round(float(candidate_scorecard.get("pass_rate", 0.0)) - float(baseline_scorecard.get("pass_rate", 0.0)), 4),
        unsafe_action_rate_delta=round(
            float(candidate_scorecard.get("unsafe_action_rate", 0.0))
            - float(baseline_scorecard.get("unsafe_action_rate", 0.0)),
            4,
        ),
        p95_latency_delta_ms=_optional_delta(
            baseline_scorecard.get("p95_latency_ms"),
            candidate_scorecard.get("p95_latency_ms"),
        ),
        scenario_deltas=scenario_deltas,
        warnings=warnings,
    )


def _load_run(path: Path) -> dict[str, Any]:
    benchmark_path = path / "benchmark.json" if path.is_dir() else path
    if not benchmark_path.exists():
        raise FileNotFoundError(f"benchmark artifact not found: {benchmark_path}")
    payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "scorecard" not in payload or "results" not in payload:
        raise ValueError(f"not a benchmark artifact: {benchmark_path}")
    return cast(dict[str, Any], payload)


def _scenario_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        scenario_id = str(row.get("scenario_id"))
        grouped.setdefault(scenario_id, []).append(row)
    return {scenario_id: _summarize_scenario(attempts) for scenario_id, attempts in grouped.items()}


def _summarize_scenario(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(attempt.get("weighted_score", 0.0)) for attempt in attempts]
    decisions = [str(attempt.get("actual_decision") or "no_action") for attempt in attempts]
    return {
        "score": sum(scores) / len(scores),
        "decision": _mode(decisions),
    }


def _scenario_delta(
    scenario_id: str,
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> ScenarioDelta:
    if baseline is None:
        return ScenarioDelta(
            scenario_id=scenario_id,
            baseline_score=None,
            candidate_score=round(float(candidate["score"]), 2) if candidate else None,
            score_delta=None,
            baseline_decision=None,
            candidate_decision=str(candidate["decision"]) if candidate else None,
            status="added",
        )
    if candidate is None:
        return ScenarioDelta(
            scenario_id=scenario_id,
            baseline_score=round(float(baseline["score"]), 2),
            candidate_score=None,
            score_delta=None,
            baseline_decision=str(baseline["decision"]),
            candidate_decision=None,
            status="removed",
        )
    baseline_score = float(baseline["score"])
    candidate_score = float(candidate["score"])
    return ScenarioDelta(
        scenario_id=scenario_id,
        baseline_score=round(baseline_score, 2),
        candidate_score=round(candidate_score, 2),
        score_delta=round(candidate_score - baseline_score, 2),
        baseline_decision=str(baseline["decision"]),
        candidate_decision=str(candidate["decision"]),
        status="changed" if abs(candidate_score - baseline_score) > 0.001 else "unchanged",
    )


def _dimension_deltas(baseline_scorecard: dict[str, Any], candidate_scorecard: dict[str, Any]) -> dict[str, float]:
    baseline = cast(dict[str, Any], baseline_scorecard.get("dimension_scores", {}))
    candidate = cast(dict[str, Any], candidate_scorecard.get("dimension_scores", {}))
    return {
        name: round(float(candidate.get(name, 0.0)) - float(baseline.get(name, 0.0)), 4)
        for name in sorted(set(baseline) | set(candidate))
    }


def _optional_delta(baseline: Any, candidate: Any) -> float | None:
    if baseline is None or candidate is None:
        return None
    return round(float(candidate) - float(baseline), 2)


def _mode(values: list[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _format_optional_score(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"
