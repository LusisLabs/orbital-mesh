from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Any

from .compare import BenchmarkComparison, compare_benchmark_runs
from .runner import BenchmarkRun, BenchmarkRunConfig, run_benchmark


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GATE_CONFIG_PATH = REPO_ROOT / "benchmarks" / "benchmark_gates.json"


@dataclass(frozen=True)
class BenchmarkGateProfile:
    name: str
    description: str
    suite_split: str | None
    repeat: int
    attempt_artifact_mode: str
    runtime_state_mode: str
    compact_artifacts: bool
    thresholds: dict[str, float]

    @classmethod
    def from_dict(cls, name: str, payload: dict[str, Any]) -> "BenchmarkGateProfile":
        thresholds = payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else {}
        return cls(
            name=name,
            description=str(payload.get("description") or ""),
            suite_split=str(payload["suite_split"]) if payload.get("suite_split") else None,
            repeat=int(payload.get("repeat", 1)),
            attempt_artifact_mode=str(payload.get("attempt_artifact_mode") or "errors"),
            runtime_state_mode=str(payload.get("runtime_state_mode") or "none"),
            compact_artifacts=bool(payload.get("compact_artifacts", True)),
            thresholds={str(key): float(value) for key, value in thresholds.items()},
        )

    def with_threshold_overrides(self, overrides: dict[str, float]) -> "BenchmarkGateProfile":
        if not overrides:
            return self
        return replace(self, thresholds={**self.thresholds, **overrides})


@dataclass(frozen=True)
class BenchmarkGateCheck:
    metric: str
    observed: float | None
    threshold: float
    comparator: str
    passed: bool
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "observed": self.observed,
            "threshold": self.threshold,
            "comparator": self.comparator,
            "passed": self.passed,
            "source": self.source,
        }


@dataclass(frozen=True)
class BenchmarkGateResult:
    profile: BenchmarkGateProfile
    requested_suite: str
    effective_suite: str
    run: BenchmarkRun
    checks: list[BenchmarkGateCheck]
    comparison: BenchmarkComparison | None
    warnings: list[str]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def output_dir(self) -> Path:
        return self.run.output_dir

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mesh.benchmark.gate.v1",
            "profile": self.profile.name,
            "description": self.profile.description,
            "requested_suite": self.requested_suite,
            "effective_suite": self.effective_suite,
            "run_id": self.run.run_id,
            "output_dir": str(self.run.output_dir),
            "passed": self.passed,
            "thresholds": self.profile.thresholds,
            "checks": [check.to_dict() for check in self.checks],
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "warnings": self.warnings,
        }


def load_gate_profiles(path: Path | None = None) -> dict[str, BenchmarkGateProfile]:
    config_path = path or DEFAULT_GATE_CONFIG_PATH
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {}
    if not profiles:
        raise ValueError(f"benchmark gate config has no profiles: {config_path}")
    return {
        str(name): BenchmarkGateProfile.from_dict(str(name), profile)
        for name, profile in profiles.items()
        if isinstance(profile, dict)
    }


def resolve_gate_suite(suite: str, profile: BenchmarkGateProfile) -> str:
    split = profile.suite_split
    if split not in {"dev", "eval"}:
        return suite
    if suite.endswith("_official_dev_full") or suite.endswith("_official_eval_full"):
        prefix = suite.rsplit("_official_", 1)[0]
        return f"{prefix}_official_{split}_full"
    if suite.endswith("_official_full"):
        prefix = suite.removesuffix("_official_full")
        return f"{prefix}_official_{split}_full"
    return suite


def run_benchmark_gate(
    config: BenchmarkRunConfig | None = None,
    *,
    profile_name: str = "ci",
    profile_config_path: Path | None = None,
    baseline_dir: Path | None = None,
    threshold_overrides: dict[str, float] | None = None,
    repeat_override: int | None = None,
    attempt_artifact_mode_override: str | None = None,
    runtime_state_mode_override: str | None = None,
    compact_artifacts_override: bool | None = None,
) -> BenchmarkGateResult:
    profiles = load_gate_profiles(profile_config_path)
    if profile_name not in profiles:
        raise ValueError(f"unknown benchmark gate profile: {profile_name}")
    profile = profiles[profile_name].with_threshold_overrides(threshold_overrides or {})
    requested_config = config or BenchmarkRunConfig()
    effective_suite = resolve_gate_suite(requested_config.suite, profile)
    effective_config = replace(
        requested_config,
        suite=effective_suite,
        repeat=repeat_override if repeat_override is not None else profile.repeat,
        attempt_artifact_mode=attempt_artifact_mode_override or profile.attempt_artifact_mode,
        runtime_state_mode=runtime_state_mode_override or profile.runtime_state_mode,
        compact_artifacts=profile.compact_artifacts if compact_artifacts_override is None else compact_artifacts_override,
    )
    run = run_benchmark(effective_config)
    comparison = compare_benchmark_runs(baseline_dir, run.output_dir) if baseline_dir else None
    result = evaluate_benchmark_gate(
        run,
        profile=profile,
        requested_suite=requested_config.suite,
        effective_suite=effective_suite,
        comparison=comparison,
    )
    write_gate_artifacts(result)
    return result


def evaluate_benchmark_gate(
    run: BenchmarkRun,
    *,
    profile: BenchmarkGateProfile,
    requested_suite: str,
    effective_suite: str,
    comparison: BenchmarkComparison | None = None,
) -> BenchmarkGateResult:
    checks: list[BenchmarkGateCheck] = []
    scorecard = run.scorecard.to_dict()
    process_metrics = scorecard.get("process_metrics") if isinstance(scorecard.get("process_metrics"), dict) else {}
    thresholds = profile.thresholds
    _add_min_check(checks, thresholds, "weighted_score_min", "weighted_score", scorecard, "scorecard")
    _add_min_check(checks, thresholds, "mesh_operational_score_min", "mesh_operational_score", scorecard, "scorecard")
    _add_min_check(checks, thresholds, "agentic_rca_score_min", "agentic_rca_score", scorecard, "scorecard")
    _add_min_check(checks, thresholds, "pass_rate_min", "pass_rate", scorecard, "scorecard")
    _add_min_check(checks, thresholds, "decision_match_rate_min", "decision_match_rate", scorecard, "scorecard")
    _add_min_check(
        checks,
        thresholds,
        "investigation_coverage_rate_min",
        "investigation_coverage_rate",
        scorecard,
        "scorecard",
    )
    _add_max_check(checks, thresholds, "unsafe_action_rate_max", "unsafe_action_rate", scorecard, "scorecard")
    _add_max_check(checks, thresholds, "p95_latency_ms_max", "p95_latency_ms", scorecard, "scorecard")
    _add_min_check(checks, thresholds, "root_cause_accuracy_min", "root_cause_accuracy", process_metrics, "process")
    _add_min_check(
        checks,
        thresholds,
        "trajectory_in_order_match_min",
        "trajectory_in_order_match",
        process_metrics,
        "process",
    )
    _add_min_check(checks, thresholds, "tool_coverage_min", "tool_coverage", process_metrics, "process")
    _add_max_check(checks, thresholds, "invalid_action_count_max", "invalid_action_count", process_metrics, "process")
    _add_max_check(checks, thresholds, "zero_tool_diagnosis_rate_max", "zero_tool_diagnosis_rate", process_metrics, "process")
    warnings: list[str] = []
    if comparison is None:
        regression_thresholds = [key for key in thresholds if key.endswith("_regression_max") or key.endswith("_increase_max")]
        if regression_thresholds:
            warnings.append("regression thresholds were configured but no baseline was provided")
    else:
        _add_regression_checks(checks, thresholds, comparison)
    return BenchmarkGateResult(
        profile=profile,
        requested_suite=requested_suite,
        effective_suite=effective_suite,
        run=run,
        checks=checks,
        comparison=comparison,
        warnings=warnings,
    )


def write_gate_artifacts(result: BenchmarkGateResult) -> None:
    result.output_dir.mkdir(parents=True, exist_ok=True)
    (result.output_dir / "gate.json").write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (result.output_dir / "gate.md").write_text(render_gate_markdown(result), encoding="utf-8")


def render_gate_markdown(result: BenchmarkGateResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    lines = [
        f"# Mesh Benchmark Gate: {result.profile.name}",
        "",
        f"- Status: **{status}**",
        f"- Run ID: `{result.run.run_id}`",
        f"- Requested suite: `{result.requested_suite}`",
        f"- Effective suite: `{result.effective_suite}`",
        f"- Weighted score: {result.run.scorecard.weighted_score:.2f}",
        f"- Mesh operational score: {result.run.scorecard.mesh_operational_score:.2f}",
        f"- Agentic RCA score: {result.run.scorecard.agentic_rca_score:.2f}",
    ]
    if result.warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in result.warnings:
            lines.append(f"- {warning}")
    lines.extend([
        "",
        "## Checks",
        "",
        "| Source | Metric | Observed | Comparator | Threshold | Status |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ])
    for check in result.checks:
        observed = "" if check.observed is None else f"{check.observed:.4f}"
        lines.append(
            f"| {check.source} | {check.metric} | {observed} | {check.comparator} | {check.threshold:.4f} | "
            f"{'PASS' if check.passed else 'FAIL'} |"
        )
    if result.comparison is not None:
        lines.extend([
            "",
            "## Regression",
            "",
            f"- Baseline: `{result.comparison.baseline_run_id}`",
            f"- Candidate: `{result.comparison.candidate_run_id}`",
            f"- Weighted score delta: {result.comparison.weighted_score_delta:+.2f}",
            f"- Agentic RCA score delta: {result.comparison.agentic_rca_score_delta:+.2f}",
            f"- Pass-rate delta: {result.comparison.pass_rate_delta:+.2%}",
            f"- Unsafe-action-rate delta: {result.comparison.unsafe_action_rate_delta:+.2%}",
        ])
    return "\n".join(lines) + "\n"


def _add_min_check(
    checks: list[BenchmarkGateCheck],
    thresholds: dict[str, float],
    threshold_key: str,
    metric: str,
    values: dict[str, Any],
    source: str,
) -> None:
    if threshold_key not in thresholds:
        return
    observed = _optional_float(values.get(metric))
    threshold = thresholds[threshold_key]
    checks.append(
        BenchmarkGateCheck(
            metric=metric,
            observed=observed,
            threshold=threshold,
            comparator=">=",
            passed=observed is not None and observed >= threshold,
            source=source,
        )
    )


def _add_max_check(
    checks: list[BenchmarkGateCheck],
    thresholds: dict[str, float],
    threshold_key: str,
    metric: str,
    values: dict[str, Any],
    source: str,
) -> None:
    if threshold_key not in thresholds:
        return
    observed = _optional_float(values.get(metric))
    threshold = thresholds[threshold_key]
    checks.append(
        BenchmarkGateCheck(
            metric=metric,
            observed=observed,
            threshold=threshold,
            comparator="<=",
            passed=observed is not None and observed <= threshold,
            source=source,
        )
    )


def _add_regression_checks(
    checks: list[BenchmarkGateCheck],
    thresholds: dict[str, float],
    comparison: BenchmarkComparison,
) -> None:
    _add_regression_check(
        checks,
        thresholds,
        "weighted_score_regression_max",
        "weighted_score_delta",
        comparison.weighted_score_delta,
    )
    _add_regression_check(
        checks,
        thresholds,
        "mesh_operational_score_regression_max",
        "mesh_operational_score_delta",
        comparison.mesh_operational_score_delta,
    )
    _add_regression_check(
        checks,
        thresholds,
        "agentic_rca_score_regression_max",
        "agentic_rca_score_delta",
        comparison.agentic_rca_score_delta,
    )
    _add_regression_check(checks, thresholds, "pass_rate_regression_max", "pass_rate_delta", comparison.pass_rate_delta)
    _add_regression_check(
        checks,
        thresholds,
        "decision_match_rate_regression_max",
        "decision_match_rate_delta",
        comparison.decision_match_rate_delta,
    )
    _add_regression_check(
        checks,
        thresholds,
        "investigation_coverage_rate_regression_max",
        "investigation_coverage_rate_delta",
        comparison.investigation_coverage_rate_delta,
    )
    _add_increase_check(
        checks,
        thresholds,
        "unsafe_action_rate_increase_max",
        "unsafe_action_rate_delta",
        comparison.unsafe_action_rate_delta,
    )
    _add_regression_check(
        checks,
        thresholds,
        "root_cause_accuracy_regression_max",
        "root_cause_accuracy_delta",
        comparison.process_metric_deltas.get("root_cause_accuracy"),
    )
    _add_regression_check(
        checks,
        thresholds,
        "tool_coverage_regression_max",
        "tool_coverage_delta",
        comparison.process_metric_deltas.get("tool_coverage"),
    )
    _add_regression_check(
        checks,
        thresholds,
        "trajectory_in_order_match_regression_max",
        "trajectory_in_order_match_delta",
        comparison.process_metric_deltas.get("trajectory_in_order_match"),
    )


def _add_regression_check(
    checks: list[BenchmarkGateCheck],
    thresholds: dict[str, float],
    threshold_key: str,
    metric: str,
    delta: float | None,
) -> None:
    if threshold_key not in thresholds:
        return
    threshold = thresholds[threshold_key]
    checks.append(
        BenchmarkGateCheck(
            metric=metric,
            observed=delta,
            threshold=threshold,
            comparator=f">= -{threshold}",
            passed=delta is not None and delta >= -threshold,
            source="regression",
        )
    )


def _add_increase_check(
    checks: list[BenchmarkGateCheck],
    thresholds: dict[str, float],
    threshold_key: str,
    metric: str,
    delta: float | None,
) -> None:
    if threshold_key not in thresholds:
        return
    threshold = thresholds[threshold_key]
    checks.append(
        BenchmarkGateCheck(
            metric=metric,
            observed=delta,
            threshold=threshold,
            comparator="<=",
            passed=delta is not None and delta <= threshold,
            source="regression",
        )
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
