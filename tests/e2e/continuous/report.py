"""Render a :class:`SessionResult` as markdown + JSON.

# Shape of the report

The markdown report is designed to be skimmable at three levels:

1. **Top of report** — verdict + hypothesis pass/fail table. If this
   is all the reader sees, they know whether Mesh held up.
2. **Aggregate metrics** — side-by-side predicted vs observed for
   every hypothesis threshold. Breaches are called out inline.
3. **Timeline + per-experiment table** — every injection, Mesh's
   decision, latency, and pass/fail. This is where the operator
   goes to diagnose a failed run.

An **Appendix** carries the full probe history + raw per-experiment
records for the 1% of cases where someone needs to dig.

# Why markdown + JSON, not only one

Markdown is for humans reviewing a session (PR comments, CI
artifacts, the PR this harness lives in). JSON is for machines —
diffing across sessions, building dashboards, feeding into a
higher-level "Mesh quality over time" metric. The JSON is the source
of truth; markdown is a render.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests.e2e.continuous.session import SessionResult


def render_markdown(result: SessionResult) -> str:
    """Render the session's markdown report."""
    lines: list[str] = []

    # --- header --------------------------------------------------------
    verdict_badge = _verdict_badge(result.verdict)
    started = datetime.fromtimestamp(result.started_at, tz=timezone.utc).isoformat()
    lines.append(f"# Chaos Session: `{result.session_id}`")
    lines.append("")
    lines.append(
        f"{verdict_badge} · duration **{result.duration_seconds:.1f}s** · started {started}"
    )
    lines.append("")
    if result.halt_reason:
        lines.append("## Halt reason")
        lines.append("")
        lines.append(f"> {result.halt_reason}")
        lines.append("")

    # --- hypothesis verdict --------------------------------------------
    lines.append("## Hypothesis")
    lines.append("")
    lines.append(
        "> The predictions below were made at session start. The scorer "
        "compares each against the observed aggregate; a single breach "
        "fails the session."
    )
    lines.append("")
    lines.append("| Metric | Predicted | Observed | Result |")
    lines.append("|--------|-----------|----------|--------|")
    metrics = result.hypothesis_result.get("metrics") or {}
    for metric_name, body in metrics.items():
        predicted_kind = next((k for k in body if k.startswith("predicted_")), None)
        predicted = body.get(predicted_kind, "?") if predicted_kind else "?"
        observed = body.get("observed")
        verdict = _metric_verdict(metric_name, body, result.hypothesis_result.get("breaches") or [])
        lines.append(
            f"| `{metric_name}` | {_fmt_threshold(predicted_kind, predicted)} | "
            f"{_fmt_value(observed)} | {verdict} |"
        )
    lines.append("")

    # --- aggregates ----------------------------------------------------
    agg = result.aggregates
    lines.append("## Aggregates")
    lines.append("")
    lines.append(f"- **Experiments:** {agg.experiments_total} total, {agg.experiments_passed} passed "
                 f"(**{agg.pass_rate * 100:.1f}%**)")
    lines.append(f"- **Pipeline crashes:** {agg.pipeline_crashes}")
    lines.append(f"- **Probes:** {agg.probes_total} total, {agg.probes_passed} passed "
                 f"({agg.probe_pass_rate * 100:.1f}%)")
    if agg.decision_latency_p50_seconds is not None:
        lines.append(
            f"- **Decision latency:** P50 {agg.decision_latency_p50_seconds:.3f}s · "
            f"P95 {_fmt_value(agg.decision_latency_p95_seconds)}s"
        )
    lines.append("")

    # --- experiment table ---------------------------------------------
    lines.append("## Experiments")
    lines.append("")
    if result.experiments:
        lines.append("| t (s) | Experiment | Target | Severity | Trigger | Decision | Latency | Verdict |")
        lines.append("|------:|------------|--------|----------|---------|----------|--------:|---------|")
        for e in result.experiments:
            lat = e.decision_latency_seconds
            verdict = "PASS" if e.pass_ else f"FAIL ({e.failure_reason or '—'})"
            lines.append(
                f"| {e.injected_at:.1f} | `{e.experiment_name}` | `{e.target_deployment}` | "
                f"{e.severity} | {'yes' if e.trigger_fired else 'no'} | "
                f"`{e.decision_type or '—'}` | {_fmt_value(lat)}s | {verdict} |"
            )
    else:
        lines.append("_No experiments ran — session halted before any injection._")
    lines.append("")

    # --- probe timeline ------------------------------------------------
    lines.append("## Steady-state probes")
    lines.append("")
    if result.probes:
        lines.append("| t (s) | Label | Cluster | Baseline | Mesh | Latency | Notes |")
        lines.append("|------:|-------|---------|----------|------|--------:|-------|")
        t0 = result.probes[0].taken_at if result.probes else 0.0
        for p in result.probes:
            notes = "; ".join(p.notes) if p.notes else ""
            mesh_lat = p.mesh_pipeline_latency_seconds
            lines.append(
                f"| {(p.taken_at - t0):.1f} | `{p.label}` | "
                f"{_yn(p.cluster_reachable)} | {_yn(p.baseline_ready)} | "
                f"{_yn(p.mesh_pipeline_ok)} | {_fmt_value(mesh_lat)}s | {notes} |"
            )
    else:
        lines.append("_No probes recorded._")
    lines.append("")

    # --- breaches detail ----------------------------------------------
    breaches = result.hypothesis_result.get("breaches") or []
    if breaches:
        lines.append("## Hypothesis breaches")
        lines.append("")
        for b in breaches:
            lines.append(
                f"- `{b['metric']}`: predicted `{b['predicted']}`, observed `{b['observed']}` — {b['reason']}"
            )
        lines.append("")

    # --- appendix ------------------------------------------------------
    lines.append("<details>")
    lines.append("<summary>Appendix: raw session data</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(render_json(result))
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    return "\n".join(lines)


def render_json(result: SessionResult) -> str:
    """Serialize a :class:`SessionResult` as JSON.

    Uses ``dataclasses.asdict`` so nested dataclasses (probes,
    experiments, aggregates) walk correctly. ``frozenset`` fields
    get a ``default=`` fallback because asdict doesn't special-case
    them.
    """
    payload = asdict(result)
    return json.dumps(payload, indent=2, sort_keys=True, default=_json_default)


def write_report(result: SessionResult, output_dir: str | Path) -> dict[str, str]:
    """Persist both formats and return the paths."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    md_path = output / f"{result.session_id}.md"
    json_path = output / f"{result.session_id}.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(render_json(result), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path)}


# ---------------------------------------------------------------- helpers


def _verdict_badge(verdict: str) -> str:
    return {"pass": "**[PASS]**", "fail": "**[FAIL]**"}.get(
        verdict, f"**[{verdict.upper()}]**"
    )


def _metric_verdict(metric_name: str, body: dict[str, Any], breaches: list[dict[str, Any]]) -> str:
    for b in breaches:
        if b.get("metric") == metric_name:
            return "**BREACH**"
    return "ok"


def _fmt_threshold(kind: str | None, value: Any) -> str:
    if kind is None:
        return str(value)
    if "max" in kind:
        return f"≤ {value}"
    if "min" in kind:
        return f"≥ {value}"
    return str(value)


def _fmt_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _yn(flag: bool) -> str:
    return "ok" if flag else "fail"


def _json_default(value: Any) -> Any:
    """Fallback for types dataclasses.asdict doesn't handle natively.

    Most relevant here: ``frozenset`` (used for ``expected_decisions``
    and ``tags``). Converting to a sorted list keeps JSON diffs
    stable across runs.
    """
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return str(value)


__all__ = ["render_json", "render_markdown", "write_report"]
