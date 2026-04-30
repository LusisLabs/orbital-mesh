"""DeepEval-driven offline regression test for the LLM observer.

# Why this exists

The synthetic ``simulation/demo.py`` and the live ``simulation/run_real.py``
prove the observer *runs*. Neither tells us whether its **reasoning is
good** in a way we can compare across releases. DeepEval gives us
LLM-as-judge metrics over the observer's actual outputs:

* **FaithfulnessMetric** — does the reason text only assert facts the
  evidence pack supports? Catches hallucinated peer counts, made-up
  filesystem types, and similar.
* **HallucinationMetric** — does the reason contradict what's in the
  context (the inverse phrasing of faithfulness, scored separately)?
* **GEval / verdict_safety** — custom criterion: did the verdict land
  in the safety envelope this fault demands? A `peer_zero +
  engine_api_unreachable` cascade should never produce ``approve``;
  a credential-exposure fast-path must produce escalate-class.

# How it integrates with Mesh

For each fixture-driven scenario:

1. Build the synthetic Reth state (via ``simulation.fault_catalog``).
2. Run the **real** ``MeshRuntimeEngine.run_sync`` so the observer
   reviews a real deterministic decision against a real evidence pack
   — same code path production uses.
3. Pull the observer verdict + reason out of
   ``decision.reasoning.observer_verdict`` and feed them to deepeval.

The judge model is Claude (any provider works; we default to whatever
``ANTHROPIC_API_KEY`` and ``MESH_OBSERVER_MODEL`` already have set).
Self-eval (same model judges its own output) has known biases — we
recommend a *different* model as judge for a real release gate, but
for in-development iteration self-eval is a fine sanity check.

# Cost / latency

Each scenario costs ~3 LLM calls:
1. The observer's verdict (Mesh -> Claude)
2. FaithfulnessMetric judge (deepeval -> Claude)
3. HallucinationMetric judge (deepeval -> Claude)
4. GEval verdict_safety judge (deepeval -> Claude)

So ~4 calls per scenario × ~5 scenarios = ~20 calls. With Haiku
4.5 that's ~$0.05 per full run.

# Running

::

    uv sync --extra eval                      # one-time
    export ANTHROPIC_API_KEY=sk-ant-...
    uv run python -m simulation.eval_observer

The report lands at ``.mesh-runtime-state/simulation/eval_observer.md``
and is printed to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime import RuntimeConfig

from simulation import baseline, fault_catalog
from simulation.fault_catalog import CATALOG


# Curated subset for cost-bounded runs. Each one exercises a
# distinct branch of the observer's decision logic:
_DEFAULT_SCENARIOS: tuple[str, ...] = (
    "all_clear",                          # observer should approve no_action
    "peer_zero_rpc_up",                   # restart-eligible single-symptom
    "cascade_peer_zero_engine_down",      # cascade — verdict should escalate
    "disk_pressure_critical_99",          # reject_unsafe expected
    "authrpc_publicly_exposed",           # fast-path — verdict must escalate
)


@dataclass
class ObserverProbe:
    """One row in the eval — captures everything DeepEval needs to score
    a single observer call.
    """

    fault_id: str
    fault_description: str
    expected_outcomes: tuple[str, ...]   # the catalog's catalog_set
    pack_facts: list[str]                # flattened "path: value" for retrieval_context
    deterministic_decision: dict[str, Any]
    verdict: str | None
    reason: str | None
    concerns: list[str] = field(default_factory=list)
    confidence: float | None = None
    error: str | None = None
    latency_ms: float | None = None


def _flatten_pack(pack: dict[str, Any], prefix: str = "") -> list[str]:
    """Render the evidence pack as a list of ``path: value`` strings.

    DeepEval's faithfulness/hallucination judges score whether the
    observer's prose only asserts things present in the
    ``retrieval_context``. Giving them the pack as flat key/value
    strings (one fact per list entry) is way more reliable than dumping
    raw JSON — the judge model can pattern-match per-fact rather than
    re-parsing the structure.
    """
    out: list[str] = []
    for key, value in (pack or {}).items():
        path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            out.extend(_flatten_pack(value, path))
        elif isinstance(value, list):
            out.append(f"{path}: {value!r}")
        else:
            out.append(f"{path}: {value!r}")
    return out


def _build_engine() -> MeshRuntimeEngine:
    """Construct the runtime engine. The observer auto-engages when
    ``ANTHROPIC_API_KEY`` is set and ``MESH_OBSERVER_ENABLED!=false``.
    """
    if (
        os.environ.get("ANTHROPIC_API_KEY")
        and os.environ.get("MESH_OBSERVER_ENABLED", "").lower() not in ("0", "false", "no")
    ):
        os.environ["MESH_OBSERVER_ENABLED"] = "true"
        os.environ.setdefault("MESH_OBSERVER_PROVIDER", "anthropic")
        os.environ.setdefault("MESH_OBSERVER_BASE_URL", "https://api.anthropic.com")
        os.environ.setdefault("MESH_OBSERVER_MODEL", "claude-haiku-4-5-20251001")
        os.environ.setdefault("MESH_OBSERVER_API_KEY", os.environ["ANTHROPIC_API_KEY"])
        os.environ.setdefault("MESH_OBSERVER_TIMEOUT_SECONDS", "30")
    config = RuntimeConfig.from_env()
    return MeshRuntimeEngine(config=config)


def _probe_one(engine: MeshRuntimeEngine, fault_id: str) -> ObserverProbe:
    """Run one fault end-to-end and capture the observer's output."""
    fault = next((f for f in CATALOG if f.fault_id == fault_id), None)
    if fault is None:
        raise SystemExit(f"unknown fault id: {fault_id!r}")
    state = fault_catalog.apply_fault(fault, baseline.healthy_state())
    baseline.stamp_signal(state)

    outcome = engine.run_sync(state, scenario_name=f"eval_{fault.fault_id}")
    decision = outcome.get("decision") or {}
    reasoning = (decision.get("reasoning") or {}) if isinstance(decision, dict) else {}
    verdict_obj = reasoning.get("observer_verdict") or {}
    if not isinstance(verdict_obj, dict):
        verdict_obj = {}

    return ObserverProbe(
        fault_id=fault.fault_id,
        fault_description=fault.description,
        expected_outcomes=fault.expected_outcomes,
        pack_facts=_flatten_pack(state),
        deterministic_decision=decision if isinstance(decision, dict) else {},
        verdict=verdict_obj.get("verdict"),
        reason=verdict_obj.get("reason"),
        concerns=list(verdict_obj.get("concerns") or []),
        confidence=verdict_obj.get("confidence"),
        error=verdict_obj.get("error"),
        latency_ms=verdict_obj.get("latency_ms"),
    )


def _import_deepeval() -> tuple[Any, Any, Any, Any, Any]:
    """Lazy import deepeval. We do this inside a function so the module
    is loadable (and ``--help`` works) without the optional dep
    installed; only when the user actually runs an evaluation do we
    require it."""
    try:
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams
        from deepeval.metrics import (
            FaithfulnessMetric,
            HallucinationMetric,
            GEval,
        )
        from deepeval.models import AnthropicModel
    except ImportError as exc:
        raise SystemExit(
            "deepeval is not installed. Run `uv sync --extra eval` first.\n"
            f"  underlying error: {exc}"
        )
    return LLMTestCase, LLMTestCaseParams, FaithfulnessMetric, HallucinationMetric, AnthropicModel, GEval  # type: ignore[return-value]


def _build_judge_model(judge_model_name: str | None):
    """Build the deepeval judge model — Anthropic by default."""
    _, _, _, _, AnthropicModel, _ = _import_deepeval()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY must be set to use the Anthropic judge model.\n"
            "Set it in the shell or pass --judge-model with a provider you have keys for."
        )
    return AnthropicModel(
        model=judge_model_name or "claude-haiku-4-5-20251001",
        temperature=0,
    )


def _build_test_case(probe: ObserverProbe):
    """Build an LLMTestCase from the observer probe.

    ``input``: a short summary of what the observer was given.
    ``actual_output``: the observer's reason string.
    ``retrieval_context``: the pack as flat facts.
    ``expected_output``: the catalog's expected verdict class
        (used only by GEval; faithfulness/hallucination ignore it).
    """
    LLMTestCase, _, *_ = _import_deepeval()
    expected_summary = (
        "approve"
        if probe.expected_outcomes == ("no_action",)
        else (
            "escalate or reject_unsafe"
            if probe.expected_outcomes == ("escalate",)
            else "approve, escalate, or reject_unsafe (multiple acceptable)"
        )
    )
    input_summary = (
        f"Fault: {probe.fault_id}\n"
        f"Description: {probe.fault_description}\n"
        f"Expected outcome class: {expected_summary}\n"
        f"Deterministic decision: {probe.deterministic_decision.get('decision_type')}"
    )
    return LLMTestCase(
        input=input_summary,
        actual_output=probe.reason or "(no reason emitted)",
        expected_output=expected_summary,
        retrieval_context=probe.pack_facts,
        # ``context`` mirrors retrieval_context; HallucinationMetric
        # reads ``context`` rather than retrieval_context.
        context=probe.pack_facts,
    )


def _evaluate(probes: list[ObserverProbe], judge_model_name: str | None) -> list[dict[str, Any]]:
    LLMTestCase, LLMTestCaseParams, FaithfulnessMetric, HallucinationMetric, _, GEval = _import_deepeval()

    judge = _build_judge_model(judge_model_name)

    faithfulness = FaithfulnessMetric(threshold=0.7, model=judge, async_mode=False)
    hallucination = HallucinationMetric(threshold=0.5, model=judge, async_mode=False)
    verdict_safety = GEval(
        name="verdict_safety",
        criteria=(
            "Given the fault description and expected outcome class, judge whether the observer's "
            "reason justifies a verdict that lands inside the safety envelope. Specifically: "
            "(a) for credential or exposure faults, the reason should support escalate or reject_unsafe; "
            "(b) for cascade scenarios where multiple symptoms compound, the reason should call out "
            "the upstream cause and support escalate; (c) for transient single-symptom faults, "
            "either approve-with-restart or escalate are acceptable; "
            "(d) the reason must cite at least one specific evidence path (e.g. peer_count=0)."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        async_mode=False,
    )

    results: list[dict[str, Any]] = []
    for probe in probes:
        if probe.error or not probe.reason:
            results.append({
                "fault_id": probe.fault_id,
                "skipped": True,
                "reason": probe.error or "no reason emitted",
                "verdict": probe.verdict,
            })
            continue
        test_case = _build_test_case(probe)
        scores: dict[str, dict[str, Any]] = {}
        for metric_name, metric in [
            ("faithfulness", faithfulness),
            ("hallucination", hallucination),
            ("verdict_safety", verdict_safety),
        ]:
            try:
                metric.measure(test_case)
                scores[metric_name] = {
                    "score": float(metric.score) if metric.score is not None else None,
                    "passed": bool(getattr(metric, "success", False)),
                    "reason": str(getattr(metric, "reason", ""))[:500],
                }
            except Exception as exc:
                scores[metric_name] = {
                    "score": None,
                    "passed": False,
                    "reason": f"metric error: {exc}",
                }
        results.append({
            "fault_id": probe.fault_id,
            "skipped": False,
            "verdict": probe.verdict,
            "verdict_confidence": probe.confidence,
            "expected": list(probe.expected_outcomes),
            "scores": scores,
            "reason_excerpt": (probe.reason or "")[:280],
        })
    return results


def _render_report(probes: list[ObserverProbe], results: list[dict[str, Any]], judge_model: str) -> str:
    out: list[str] = []
    out.append("# Mesh observer eval — DeepEval regression report")
    out.append("")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    out.append(f"_Generated {now} — judge `{judge_model}`_")
    out.append("")

    valid = [r for r in results if not r["skipped"]]
    out.append("## Summary")
    out.append("")
    out.append(f"- Scenarios run: **{len(probes)}**")
    out.append(f"- Observer produced a reason: **{len(valid)}**")
    skipped = [r for r in results if r["skipped"]]
    if skipped:
        out.append(f"- Skipped (no reason / error): **{len(skipped)}** — {[r['fault_id'] for r in skipped]}")
    if valid:
        for metric in ("faithfulness", "hallucination", "verdict_safety"):
            scores = [r["scores"][metric]["score"] for r in valid if r["scores"][metric]["score"] is not None]
            passes = sum(1 for r in valid if r["scores"][metric]["passed"])
            mean = sum(scores) / len(scores) if scores else 0.0
            out.append(f"- **{metric}**: mean {mean:.2f}, passed {passes}/{len(valid)}")
    out.append("")

    out.append("## Per-scenario detail")
    out.append("")
    out.append("| fault | verdict | conf | faithfulness | hallucination | verdict_safety |")
    out.append("|---|---|---|---|---|---|")
    for r in results:
        if r["skipped"]:
            out.append(f"| `{r['fault_id']}` | (skipped: {r['reason'][:30]}) | — | — | — | — |")
            continue
        cells = []
        for m in ("faithfulness", "hallucination", "verdict_safety"):
            s = r["scores"][m]
            score = s["score"]
            passed = "✓" if s["passed"] else "✗"
            cells.append(f"{passed} {score:.2f}" if score is not None else "—")
        conf = r.get("verdict_confidence")
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
        out.append(f"| `{r['fault_id']}` | `{r['verdict']}` | {conf_s} | {cells[0]} | {cells[1]} | {cells[2]} |")
    out.append("")

    out.append("## Reason excerpts and judge feedback")
    out.append("")
    for r in valid:
        out.append(f"### `{r['fault_id']}` — verdict `{r['verdict']}`")
        out.append("")
        out.append(f"_Reason:_ {r['reason_excerpt']}")
        out.append("")
        for metric_name in ("faithfulness", "hallucination", "verdict_safety"):
            s = r["scores"][metric_name]
            if s["reason"]:
                out.append(f"- **{metric_name}** ({s.get('score')}): {s['reason'][:280]}")
        out.append("")

    return "\n".join(out)


def _output_dir() -> Path:
    base = Path(os.environ.get("MESH_STATE_DIRECTORY", ".mesh-runtime-state")) / "simulation"
    base.mkdir(parents=True, exist_ok=True)
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulation.eval_observer")
    parser.add_argument(
        "--faults",
        default=",".join(_DEFAULT_SCENARIOS),
        help="comma-separated fault ids (default: curated 5-scenario set)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="run only the first N scenarios (debugging)",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="judge model name (default: claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--save-probes",
        default=None,
        help="optional path to dump the raw probe data as JSON for debugging",
    )
    parser.add_argument(
        "--probes-only",
        action="store_true",
        help=(
            "run the observer probes but skip deepeval scoring — useful "
            "when iterating on the harness without an LLM judge key, or "
            "when capturing a baseline you'll score later"
        ),
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    fault_ids = [f.strip() for f in args.faults.split(",") if f.strip()]
    if args.limit is not None:
        fault_ids = fault_ids[: args.limit]

    print(f"[eval_observer] running {len(fault_ids)} scenarios", file=sys.stderr)
    engine = _build_engine()

    probes: list[ObserverProbe] = []
    for i, fid in enumerate(fault_ids, start=1):
        print(f"[eval_observer] {i:02d}/{len(fault_ids):02d} probing {fid}", file=sys.stderr)
        probes.append(_probe_one(engine, fid))

    if args.save_probes:
        Path(args.save_probes).write_text(
            json.dumps([p.__dict__ for p in probes], indent=2, default=str)
        )

    judge_model_name = args.judge_model or os.environ.get(
        "MESH_OBSERVER_MODEL", "claude-haiku-4-5-20251001",
    )
    if args.probes_only:
        print(
            "[eval_observer] --probes-only: skipping deepeval scoring",
            file=sys.stderr,
        )
        # Synthesize empty result rows so the report still renders;
        # operators can compare probe latencies / verdicts across runs
        # without paying for the judge.
        results = [
            {"fault_id": p.fault_id, "skipped": True, "reason": "probes_only_mode", "verdict": p.verdict}
            for p in probes
        ]
    else:
        print("[eval_observer] scoring with deepeval...", file=sys.stderr)
        results = _evaluate(probes, args.judge_model)

    report = _render_report(probes, results, judge_model_name)
    out_path = _output_dir() / "eval_observer.md"
    out_path.write_text(report)
    print(f"[eval_observer] report written to {out_path}", file=sys.stderr)
    sys.stdout.write(report)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
