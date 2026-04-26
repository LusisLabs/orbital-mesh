"""Markdown report generator for simulation runs.

Lead with observer behavior — that's the simulation's purpose. The
deterministic-engine accuracy section is kept as background only,
because Mesh's deterministic floor is already covered by unit tests
and is not what the simulation is meant to validate.

Sections (in order):
1. Top-line — accuracy + observer activity at a glance
2. Observer behavior — verdicts, promotions, evidence-citation,
   prompt-cache stats, latency
3. Per-fault detail with observer reasoning
4. Failures (where observer + engine disagreed with the catalog)
5. Background — deterministic decision distribution and latency
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from simulation.driver import RunResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _percent(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{(numerator / denominator) * 100:.1f}%"


def _latency_stats(values: list[float]) -> str:
    if not values:
        return "n/a"
    p50 = statistics.median(values)
    p95 = statistics.quantiles(values, n=20)[-1] if len(values) >= 20 else max(values)
    return f"p50={p50:.0f}ms p95={p95:.0f}ms n={len(values)}"


def _truncate(s: str | None, n: int) -> str:
    if not s:
        return "—"
    s = s.replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def render(results: Iterable[RunResult], *, mode: str, observer_active: bool) -> str:
    rs = list(results)
    total = len(rs)
    triggered = sum(1 for r in rs if r.triggered)
    matched = sum(1 for r in rs if r.matched_expectation)
    errors = sum(1 for r in rs if r.error)

    # Observer-only views
    observer_runs = [r for r in rs if r.observer_verdict and not r.observer_error]
    observer_failed = [r for r in rs if r.observer_error]
    observer_verdict_counter: Counter[str] = Counter(
        r.observer_verdict for r in observer_runs
    )
    promoted = [r for r in observer_runs if r.observer_promoted]
    cited = [r for r in observer_runs if r.observer_cited_evidence]
    promoted_when_expected = [
        r for r in observer_runs if r.observer_promoted_when_expected
    ]
    expected_to_promote = [
        r for r in observer_runs if r.observer_promoted_when_expected is not None
    ]
    missed_promotion = [
        r for r in expected_to_promote if not r.observer_promoted_when_expected
    ]

    observer_latencies = [
        r.observer_latency_ms for r in observer_runs if r.observer_latency_ms
    ]
    observer_confidences = [
        r.observer_confidence for r in observer_runs if r.observer_confidence is not None
    ]

    # Deterministic-engine views (background)
    decision_counter: Counter[str] = Counter()
    for r in rs:
        decision_counter[r.actual_decision_type or "no_trigger"] += 1
    decision_latencies = [r.duration_ms for r in rs if r.duration_ms]

    # Hypothesis ranking views
    hypothesis_runs = [r for r in rs if r.ranked_hypothesis_count > 0]
    top_cause_counter: Counter[str] = Counter(
        r.top_hypothesis_cause for r in hypothesis_runs if r.top_hypothesis_cause
    )

    by_category: dict[str, list[RunResult]] = defaultdict(list)
    for r in rs:
        by_category[r.category].append(r)

    # Compose
    out: list[str] = []
    out.append("# Mesh fault-injection simulation report")
    out.append("")
    out.append(
        f"_Generated {_now_iso()} — mode `{mode}` — observer "
        f"`{'on' if observer_active else 'off'}`_"
    )
    out.append("")

    # ---------- Top-line ----------
    out.append("## Top-line")
    out.append("")
    out.append(f"- Total runs: **{total}**")
    out.append(f"- Triggered (signal cleared thresholds): **{triggered}** ({_percent(triggered, total)})")
    if observer_active:
        out.append(f"- Observer ran successfully: **{len(observer_runs)}** ({_percent(len(observer_runs), triggered)} of triggered)")
        out.append(f"- Observer hard-promoted to escalate-class: **{len(promoted)}** ({_percent(len(promoted), len(observer_runs))} of observer runs)")
        out.append(f"- Observer reason cited evidence by path: **{len(cited)}** ({_percent(len(cited), len(observer_runs))} of observer runs)")
        out.append(f"- Observer promoted on faults where escalate was the only acceptable outcome: **{len(promoted_when_expected)} / {len(expected_to_promote)}** ({_percent(len(promoted_when_expected), len(expected_to_promote))})")
        out.append(f"- Observer latency: **{_latency_stats([float(v) for v in observer_latencies])}**")
        if observer_confidences:
            out.append(f"- Observer mean self-confidence: **{statistics.mean(observer_confidences):.2f}**")
        if observer_failed:
            out.append(f"- Observer errored: **{len(observer_failed)}** (full pipeline still produced a decision)")
    out.append(f"- Catalog accuracy (deterministic + observer combined): **{matched}** ({_percent(matched, total)})")
    out.append(f"- Errors / exceptions: **{errors}**")
    out.append("")

    # ---------- Observer behavior ----------
    if observer_active:
        out.append("## Observer behavior")
        out.append("")
        if observer_verdict_counter:
            out.append("**Verdict distribution:**")
            out.append("")
            out.append("| verdict | count |")
            out.append("|---|---|")
            for verdict, count in observer_verdict_counter.most_common():
                out.append(f"| `{verdict}` | {count} |")
            out.append("")

        if missed_promotion:
            out.append("**Missed escalations** — the fault could only correctly resolve to `escalate`, but the observer said something else:")
            out.append("")
            out.append("| fault | observer verdict | observer reason |")
            out.append("|---|---|---|")
            for r in missed_promotion:
                out.append(
                    f"| `{r.fault_id}` | `{r.observer_verdict}` | {_truncate(r.observer_reason, 140)} |"
                )
            out.append("")
        else:
            out.append("**Missed escalations:** none — every escalate-only fault was promoted by the observer.")
            out.append("")

        # Pull a few good promotion examples for qualitative review.
        good_promotions = [
            r for r in promoted
            if r.observer_promoted_when_expected and r.observer_cited_evidence
        ][:5]
        if good_promotions:
            out.append("**Sample of well-grounded promotions** (observer cited evidence and promoted appropriately):")
            out.append("")
            for r in good_promotions:
                out.append(f"- `{r.fault_id}` — {r.description}")
                out.append(f"  - verdict: `{r.observer_verdict}` (confidence {r.observer_confidence})")
                out.append(f"  - reason: {_truncate(r.observer_reason, 200)}")
                if r.observer_concerns:
                    out.append(f"  - concerns: {', '.join(_truncate(c, 80) for c in r.observer_concerns)}")
            out.append("")

        if observer_failed:
            out.append("**Observer errors** — calls that failed; the deterministic decision stood:")
            out.append("")
            out.append("| fault | error |")
            out.append("|---|---|")
            for r in observer_failed:
                out.append(f"| `{r.fault_id}` | {_truncate(r.observer_error, 160)} |")
            out.append("")

    # ---------- Per-fault detail ----------
    out.append("## Per-fault detail")
    out.append("")
    if observer_active:
        out.append("| fault | category | trigger | engine decision | top hypothesis | observer | promoted? | cited? | latency |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for r in rs:
            decision = r.actual_decision_type or "no_trigger"
            trigger = "✓" if r.triggered else "—"
            top = f"{r.top_hypothesis_cause} ({r.top_hypothesis_id})" if r.top_hypothesis_cause else "—"
            promoted = "✓" if r.observer_promoted else ("—" if r.observer_verdict else "·")
            cited = "✓" if r.observer_cited_evidence else ("—" if r.observer_verdict else "·")
            obs = r.observer_verdict or "—"
            out.append(
                f"| `{r.fault_id}` | {r.category} | {trigger} | `{decision}` | {top} | "
                f"`{obs}` | {promoted} | {cited} | {r.duration_ms:.0f}ms |"
            )
    else:
        out.append("| fault | category | trigger | engine decision | top hypothesis | latency |")
        out.append("|---|---|---|---|---|---|")
        for r in rs:
            decision = r.actual_decision_type or "no_trigger"
            trigger = "✓" if r.triggered else "—"
            top = f"{r.top_hypothesis_cause} ({r.top_hypothesis_id})" if r.top_hypothesis_cause else "—"
            out.append(
                f"| `{r.fault_id}` | {r.category} | {trigger} | `{decision}` | {top} | "
                f"{r.duration_ms:.0f}ms |"
            )
    out.append("")

    # ---------- Failures ----------
    failures = [r for r in rs if not r.matched_expectation]
    if failures:
        out.append("## Failures (Mesh's outcome was not in the fault's acceptable set)")
        out.append("")
        out.append("| fault | expected | actual | observer | observer reason |")
        out.append("|---|---|---|---|---|")
        for r in failures:
            actual = r.actual_decision_type or "no_trigger"
            expected = "/".join(r.expected_outcomes)
            obs = r.observer_verdict or "—"
            out.append(
                f"| `{r.fault_id}` | `{expected}` | `{actual}` | `{obs}` | "
                f"{_truncate(r.observer_reason or r.error, 160)} |"
            )
        out.append("")
    else:
        out.append("## Failures")
        out.append("")
        out.append("None — every fault produced an acceptable outcome.")
        out.append("")

    # ---------- Background: deterministic engine ----------
    out.append("## Background: deterministic engine")
    out.append("")
    out.append(f"- Decision latency (full pipeline): **{_latency_stats(decision_latencies)}**")
    out.append("")
    out.append("**Decision distribution:**")
    out.append("")
    out.append("| decision_type | count |")
    out.append("|---|---|")
    for decision_type, count in decision_counter.most_common():
        out.append(f"| `{decision_type}` | {count} |")
    out.append("")

    if top_cause_counter:
        out.append("**Top hypothesis causes** (when the engine's hypothesis ranking ran):")
        out.append("")
        out.append("| candidate_cause | count |")
        out.append("|---|---|")
        for cause, count in top_cause_counter.most_common():
            out.append(f"| `{cause}` | {count} |")
        out.append("")

    out.append("**Per-category accuracy:**")
    out.append("")
    out.append("| category | runs | matched | accuracy |")
    out.append("|---|---|---|---|")
    for category in sorted(by_category):
        cat_results = by_category[category]
        cat_matched = sum(1 for r in cat_results if r.matched_expectation)
        out.append(
            f"| {category} | {len(cat_results)} | {cat_matched} | "
            f"{_percent(cat_matched, len(cat_results))} |"
        )
    out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_Run with `python -m simulation` to regenerate. "
        "`ANTHROPIC_API_KEY=...` engages the Claude observer by default; "
        "`--no-observer` runs deterministic-only._"
    )
    out.append("")
    return "\n".join(out)
