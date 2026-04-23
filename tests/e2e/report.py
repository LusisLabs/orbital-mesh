"""Scenario report generator (markdown + JSON).

# Why two formats

- **Markdown** for humans reviewing e2e results. Rendered in PR
  descriptions, CI artifacts, or piped to ``less``. The markdown report
  tells a story: here's what we broke, here's what Mesh decided, here's
  whether the cluster recovered.
- **JSON** for machines. Suitable for diffing across runs, feeding
  into dashboards, or asserting specific fields in a higher-level
  test. The JSON is the source of truth; the markdown is a render of
  the same data.

Both are emitted from the same :class:`ScenarioRun` so they can't drift.

# Report sections

The markdown follows a consistent order so readers build pattern
recognition across scenarios:

1. **Verdict** at the top — pass / fail / inconclusive. If someone
   only reads the first paragraph they see what matters.
2. **Chaos injected** — what we broke and when.
3. **Mesh response** — trigger type, decision type, decision reasoning.
4. **Timeline** — annotated seconds-scale view of the full scenario.
5. **Cluster state** — before vs after snapshots.
6. **Appendix** — full signal / trigger / decision / evaluation /
   execution / feedback objects for when someone needs the raw data.

Appendix is hidden behind a ``<details>`` collapse so the top of the
report stays readable.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.e2e.harness import ScenarioRun


def render_markdown(run: ScenarioRun) -> str:
    """Render a :class:`ScenarioRun` as a markdown report.

    Every section here is defensive about missing data — a scenario
    that crashes before it collects a signal should still produce a
    readable report that names what's missing. The report is often
    the most useful diagnostic when a scenario breaks, so it has to
    degrade gracefully.
    """
    verdict_badge = _verdict_badge(run.verdict)
    duration = round(run.completed_at - run.started_at, 2)

    lines: list[str] = []
    lines.append(f"# E2E Scenario: `{run.name}`")
    lines.append("")
    lines.append(f"{verdict_badge} · duration: **{duration}s** · generated: {datetime.utcnow().isoformat()}Z")
    lines.append("")

    if run.failure_reason:
        lines.append("## Failure reason")
        lines.append("")
        lines.append(f"```\n{run.failure_reason}\n```")
        lines.append("")

    # --- chaos ---------------------------------------------------------
    lines.append("## Chaos injected")
    lines.append("")
    if run.chaos:
        lines.append("| Mode | Target | Detected after |")
        lines.append("|------|--------|----------------|")
        for inj in run.chaos:
            detected = "—"
            if inj.observed_at is not None:
                detected = f"{round(inj.observed_at - inj.injected_at, 2)}s"
            lines.append(f"| `{inj.mode}` | `{inj.namespace}/{inj.deployment}` | {detected} |")
    else:
        lines.append("_No chaos was injected in this run._")
    lines.append("")

    # --- mesh response -------------------------------------------------
    lines.append("## Mesh response")
    lines.append("")
    if run.trigger:
        lines.append(f"**Trigger type:** `{run.trigger.get('trigger_type', 'unknown')}`")
    else:
        lines.append("**Trigger:** _not emitted_ (Mesh did not find the signal actionable)")
    lines.append("")
    if run.decision:
        lines.append(f"**Decision type:** `{run.decision.get('decision_type', 'unknown')}`  ")
        lines.append(f"**Autonomy tier:** `{run.decision.get('autonomy_tier', 'unknown')}`  ")
        lines.append(f"**Confidence:** {run.decision.get('confidence', '—')}")
        lines.append("")
        reasoning = run.decision.get("reasoning") or {}
        if reasoning.get("primary_hypothesis"):
            lines.append(f"> {reasoning['primary_hypothesis']}")
            lines.append("")
        evidence = reasoning.get("evidence") or []
        if evidence:
            lines.append("**Evidence:**")
            for item in evidence:
                lines.append(f"- {item}")
            lines.append("")
        plan = run.decision.get("execution_plan") or {}
        if plan:
            lines.append(f"**Execution plan:** `{plan.get('system', '?')}` → `{plan.get('action', '?')}`")
            params = plan.get("parameters") or {}
            if params:
                lines.append("```json")
                lines.append(json.dumps(params, indent=2))
                lines.append("```")
            lines.append("")
    else:
        lines.append("_Mesh did not reach the decision stage. See failure reason above._")
        lines.append("")

    # --- feedback ------------------------------------------------------
    if run.feedback:
        lines.append("## Feedback")
        lines.append("")
        outcome = run.feedback.get("outcome", "unknown")
        lines.append(f"**Outcome:** `{outcome}`  ")
        follow_up = run.feedback.get("recommended_follow_up")
        if follow_up:
            lines.append(f"**Recommended follow-up:** `{follow_up}`")
        lines.append("")

    # --- timeline ------------------------------------------------------
    lines.append("## Timeline")
    lines.append("")
    if run.steps:
        lines.append("| t (s) | Step | Status | Notes |")
        lines.append("|------:|------|--------|-------|")
        t0 = run.started_at
        for step in run.steps:
            t = round(step.started_at - t0, 2)
            notes = ", ".join(f"{k}={v}" for k, v in step.payload.items()) if step.payload else ""
            lines.append(f"| {t} | `{step.name}` | {step.status} | {notes} |")
    else:
        lines.append("_No timeline steps were recorded._")
    lines.append("")

    # --- cluster state -------------------------------------------------
    if run.cluster_snapshots:
        lines.append("## Cluster state")
        lines.append("")
        for label, snap in run.cluster_snapshots.items():
            status = snap.get("deployment_status") or {}
            ready = status.get("readyReplicas", 0) or 0
            desired = status.get("replicas", 0) or 0
            lines.append(f"**{label}** — ready `{ready}/{desired}`, revision `{snap.get('deployment_revision', '?')}`")
            if snap.get("pods"):
                lines.append("")
                lines.append("| Pod | Phase | Restarts |")
                lines.append("|-----|-------|---------:|")
                for pod in snap["pods"]:
                    lines.append(f"| `{pod.get('name')}` | {pod.get('phase')} | {pod.get('restarts', 0)} |")
            lines.append("")

    # --- merkle --------------------------------------------------------
    if run.merkle_root:
        lines.append("## Audit anchor")
        lines.append("")
        lines.append(f"Merkle root: `{run.merkle_root}`")
        lines.append("")

    # --- appendix ------------------------------------------------------
    lines.append("<details>")
    lines.append("<summary>Appendix: raw pipeline artifacts</summary>")
    lines.append("")
    for section, value in (
        ("Signal", run.signal),
        ("Trigger", run.trigger),
        ("Decision", run.decision),
        ("Evaluation", run.evaluation),
        ("Execution", run.execution),
        ("Feedback", run.feedback),
    ):
        if value is not None:
            lines.append(f"### {section}")
            lines.append("```json")
            lines.append(json.dumps(value, indent=2, sort_keys=True))
            lines.append("```")
            lines.append("")
    lines.append("</details>")
    lines.append("")

    return "\n".join(lines)


def render_json(run: ScenarioRun) -> str:
    """Serialize a :class:`ScenarioRun` to JSON.

    Uses :func:`dataclasses.asdict` so the output mirrors the in-memory
    shape 1:1. Downstream consumers (CI diffing, dashboards) should
    treat the JSON as the canonical representation and the markdown as
    the view layer.
    """
    # asdict walks nested dataclasses (steps, chaos). The result is
    # pure-data and json.dumps handles it directly.
    return json.dumps(asdict(run), indent=2, sort_keys=True, default=_json_default)


def write_report(run: ScenarioRun, output_dir: str | Path) -> dict[str, str]:
    """Write both report formats to ``output_dir`` and return the paths.

    The caller (driver script) typically adds the paths to a summary
    or uploads them as CI artifacts. We return a dict rather than a
    tuple so extending with new formats later (HTML? PDF?) doesn't
    break callers.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    md_path = output / f"{run.name}.md"
    json_path = output / f"{run.name}.json"
    md_path.write_text(render_markdown(run), encoding="utf-8")
    json_path.write_text(render_json(run), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path)}


# ---------------------------------------------------------------- helpers


def _verdict_badge(verdict: str) -> str:
    """Render a verdict as a text badge with an unmistakable prefix.

    We don't use emoji because they render inconsistently in CI log
    viewers; plain ASCII prefixes like ``[PASS]`` scan well in both
    terminals and markdown renderers.
    """
    label = verdict.upper()
    if verdict == "pass":
        return f"**[PASS]**"
    if verdict == "fail":
        return f"**[FAIL]**"
    return f"**[{label}]**"


def _json_default(value: Any) -> Any:
    """Fallback serializer for types dataclasses.asdict doesn't handle.

    The scenarios only produce plain Python + dict/list/str/number, but
    defensive programming: a future scenario adding a Path or a datetime
    should degrade gracefully to ``str(value)`` rather than crash the
    report.
    """
    return str(value)


__all__ = ["render_json", "render_markdown", "write_report"]
