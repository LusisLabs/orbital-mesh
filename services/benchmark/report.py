from __future__ import annotations

from .models import BenchmarkScorecard, ScenarioBenchmarkResult


def render_markdown_report(scorecard: BenchmarkScorecard, results: list[ScenarioBenchmarkResult]) -> str:
    lines = [
        f"# Mesh Architecture Benchmark: {scorecard.suite}",
        "",
        f"- Run ID: `{scorecard.run_id}`",
        f"- Weighted score: **{scorecard.weighted_score:.2f} / 100**",
        f"- Mesh operational score: **{scorecard.mesh_operational_score:.2f} / 100**",
        f"- Agentic RCA score: **{scorecard.agentic_rca_score:.2f} / 100**",
        f"- Scenarios: {scorecard.scenario_count}",
        f"- Attempts: {scorecard.scenario_attempt_count}",
        f"- Iterations: {scorecard.iteration_count}",
        f"- Score stddev: {scorecard.weighted_score_stddev:.4f}",
        f"- Pass rate: {scorecard.pass_rate:.2%}",
        f"- Unsafe action rate: {scorecard.unsafe_action_rate:.2%}",
        f"- Decision match rate: {scorecard.decision_match_rate:.2%}",
        f"- Investigation coverage: {scorecard.investigation_coverage_rate:.2%}",
        f"- P95 latency: {scorecard.p95_latency_ms} ms",
        "",
        "## Dimension Scores",
        "",
        "| Dimension | Score | Weight |",
        "| --- | ---: | ---: |",
    ]
    for name, score in scorecard.dimension_scores.items():
        weight = scorecard.to_dict()["dimension_weights"][name]
        lines.append(f"| {name} | {score:.2%} | {weight:.0%} |")

    lines.extend([
        "",
        "## Process Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ])
    for name, value in scorecard.process_metrics.items():
        lines.append(f"| {name} | {value:.4f} |")

    lines.extend([
        "",
        "## Scenario Results",
        "",
        "| Iteration | Backend | Scenario | Expected | Actual | Score | Ops | RCA | Unsafe | Error |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ])
    for result in results:
        expected = ", ".join(result.expected_decisions)
        unsafe = "yes" if result.unsafe_action else "no"
        error = result.error or ""
        lines.append(
            f"| {result.iteration} | {result.backend} | {result.scenario_id} | {expected} | {result.actual_decision or 'no_action'} | "
            f"{result.weighted_score:.2f} | {result.mesh_operational_score:.2f} | {result.agentic_rca_score:.2f} | {unsafe} | {error} |"
        )

    failures = [result for result in results if result.error or not result.matched_decision or result.unsafe_action]
    if failures:
        lines.extend(["", "## Attention Queue", ""])
        for result in failures:
            reason = result.error or "decision mismatch"
            if result.unsafe_action:
                reason = "unsafe action"
            lines.append(f"- `{result.scenario_id}`: {reason}")
    return "\n".join(lines) + "\n"
