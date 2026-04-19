#!/usr/bin/env python3
"""
Multi-scenario Mesh pipeline showcase: run the runtime engine across representative signals,
collect structured metrics, and write an insights report (plus optional MiniMax synthesis).

Usage:
  python3 scripts/mesh_showcase_research.py
  python3 scripts/mesh_showcase_research.py --output .mesh-runtime-state/research/my-showcase
  python3 scripts/mesh_showcase_research.py --minimax   # requires OPENAI_API_KEY or ANTHROPIC_* (see run_minimax_research)

Does not require the HTTP control plane; uses FirstSlicePipeline (same stages as the coordinator loop).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.pipeline import FirstSlicePipeline  # noqa: E402
from shared.mesh_runtime import RuntimeConfig, load_fixture  # noqa: E402


def _event_chain(events: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        et = e.get("event_type", "?")
        st = e.get("stage", "?")
        out.append(f"{st}:{et}")
    return out


def _integration_hits(events: list[dict[str, Any]]) -> list[str]:
    hits: list[str] = []
    for e in events:
        if isinstance(e, dict) and e.get("integration_name"):
            hits.append(str(e["integration_name"]))
    return hits


def _run_scenario(
    name: str,
    signal_builder: Callable[[], dict],
    *,
    evaluation_mode: str,
    orchestration_mode: str,
) -> dict[str, Any]:
    signal = signal_builder()
    tmp = tempfile.mkdtemp(prefix="mesh-showcase-")
    try:
        config = RuntimeConfig(
            state_directory=tmp,
            evaluation_mode=evaluation_mode,
            orchestration_mode=orchestration_mode,
        )
        pipeline = FirstSlicePipeline(config=config)
        t0 = time.perf_counter()
        result = pipeline.run(signal, scenario_name=name)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    events = result.get("run_events") or []
    trig = result.get("trigger")
    dec = result.get("decision")
    ev = result.get("evaluation")
    ex = result.get("execution")
    fb = result.get("feedback")
    meta = result.get("run_metadata") or {}

    return {
        "scenario": name,
        "evaluation_mode": evaluation_mode,
        "orchestration_mode": orchestration_mode,
        "elapsed_ms": elapsed_ms,
        "trigger_emitted": bool(trig),
        "trigger_type": (trig or {}).get("trigger_type") if isinstance(trig, dict) else None,
        "decision_type": (dec or {}).get("decision_type") if isinstance(dec, dict) else None,
        "evaluation_recommendation": (ev or {}).get("final_recommendation") if isinstance(ev, dict) else None,
        "evaluation_passed": (ev or {}).get("passed") if isinstance(ev, dict) else None,
        "execution_status": (ex or {}).get("status") if isinstance(ex, dict) else None,
        "feedback_outcome": (fb or {}).get("outcome") if isinstance(fb, dict) else None,
        "stage_event_count": len(events) if isinstance(events, list) else 0,
        "event_chain": _event_chain(events) if isinstance(events, list) else [],
        "integration_artifacts": _integration_hits(events) if isinstance(events, list) else [],
        "run_id": meta.get("run_id"),
        "blocking_reasons": (ev or {}).get("blocking_reasons") if isinstance(ev, dict) else None,
    }


def _build_scenarios() -> list[tuple[str, Callable[[], dict]]]:
    def latency_happy() -> dict:
        return load_fixture("signals", "search_latency_regression.json")

    def k8s_crashloop() -> dict:
        return load_fixture("signals", "kubernetes_crashloop_patch.json")

    def no_trigger() -> dict:
        s = deepcopy(load_fixture("signals", "search_latency_regression.json"))
        s["request_telemetry"]["sample_size"] = 499
        return s

    return [
        ("feature_flag_latency_happy", latency_happy),
        ("kubernetes_crashloop_remediate", k8s_crashloop),
        ("feature_flag_no_trigger", no_trigger),
    ]


def holistic_eval_orchestration_pairs() -> list[tuple[str, str]]:
    """Semi-aggressive coverage: native + promptfoo × native + goose (Hermes/Goose path when goose)."""
    return [
        ("native", "native"),
        ("native", "goose"),
        ("promptfoo", "native"),
        ("promptfoo", "goose"),
    ]


def _matrix_row_label(name: str, evaluation_mode: str, orchestration_mode: str) -> str:
    return f"{name}__eval-{evaluation_mode}_orch-{orchestration_mode}"


def _run_holistic_matrix_summaries(
    scenarios: Sequence[tuple[str, Callable[[], dict]]],
    pairs: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for evaluation_mode, orchestration_mode in pairs:
        for name, builder in scenarios:
            label = _matrix_row_label(name, evaluation_mode, orchestration_mode)
            try:
                row = _run_scenario(
                    name,
                    builder,
                    evaluation_mode=evaluation_mode,
                    orchestration_mode=orchestration_mode,
                )
                row["matrix_row"] = label
                summaries.append(row)
            except Exception as exc:  # noqa: BLE001 — collect errors per cell, keep sweep going
                summaries.append(
                    {
                        "matrix_row": label,
                        "scenario": name,
                        "evaluation_mode": evaluation_mode,
                        "orchestration_mode": orchestration_mode,
                        "error": f"{type(exc).__name__}: {exc}"[:800],
                        "elapsed_ms": 0.0,
                        "trigger_emitted": False,
                        "trigger_type": None,
                        "decision_type": None,
                        "evaluation_recommendation": None,
                        "evaluation_passed": None,
                        "execution_status": None,
                        "feedback_outcome": None,
                        "stage_event_count": 0,
                        "event_chain": [],
                        "integration_artifacts": [],
                        "run_id": None,
                        "blocking_reasons": None,
                    }
                )
    return summaries


def _write_insights_md(summaries: list[dict[str, Any]], out_dir: Path, modes_label: str) -> None:
    synth = out_dir / "synthesis"
    synth.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# Mesh showcase — empirical run digest",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat()} · modes: {modes_label}_",
        "",
        "## What we exercised",
        "",
        "End-to-end **`FirstSlicePipeline`** runs (same stage sequence as production: ingest → trigger → decision → "
        "evaluation → orchestration → feedback) with **isolated state per scenario** so trigger de-dup does not "
        "skew results.",
        "",
        "## Run table",
        "",
        "| Matrix row | Eval | Orch | Trigger? | Decision | Eval rec | Execution | Feedback | Events | ms |",
        "|--------------|------|------|----------|----------|----------|-----------|----------|--------|-----|",
    ]
    for s in summaries:
        row_label = str(s.get("matrix_row") or s.get("scenario") or "—")
        err = s.get("error")
        if err:
            row_label = f"{row_label} (ERROR)"
        lines.append(
            "| {mr} | {ev} | {oc} | {te} | {dt} | {er} | {xs} | {fo} | {ec} | {ms} |".format(
                mr=row_label.replace("|", "\\|"),
                ev=s.get("evaluation_mode") or "—",
                oc=s.get("orchestration_mode") or "—",
                te="yes" if s.get("trigger_emitted") else "no",
                dt=s.get("decision_type") or "—",
                er=s.get("evaluation_recommendation") or "—",
                xs=s.get("execution_status") or "—",
                fo=s.get("feedback_outcome") or "—",
                ec=s.get("stage_event_count", 0),
                ms=s.get("elapsed_ms", 0),
            )
        )
    lines.extend(
        [
            "",
            "## Stage chains (audit-shaped narrative)",
            "",
        ]
    )
    for s in summaries:
        head = str(s.get("matrix_row") or s.get("scenario") or "run")
        lines.append(f"### {head}")
        if s.get("error"):
            lines.append("")
            lines.append(f"_Pipeline error:_ `{s['error']}`")
        lines.append("")
        lines.append("```")
        ec = s.get("event_chain") or []
        lines.append(" → ".join(ec) if isinstance(ec, list) and ec else "(no events)")
        lines.append("```")
        lines.append("")
    any_rejected = any(s.get("execution_status") == "rejected" for s in summaries)
    any_human = any(s.get("evaluation_recommendation") == "human_review" for s in summaries)
    lines.extend(
        [
            "## Insights — why this implementation matters",
            "",
            "1. **Explicit stage machine** — Scenarios that pass the trigger emit a ordered `run_events` chain from "
            "`normalized_event` through later stages (through `feedback_recorded` when execution completes), which "
            "operators and auditors can replay.",
            "",
            "2. **Multiple signal families, one contract** — Feature-flag regression and Kubernetes deployment issues "
            "share the same pipeline surface; ingest/trigger/decision specialize the signal. That is the core product "
            "boundary (signals in, bounded actions out).",
            "",
            "3. **No-trigger is a first-class outcome** — Low-sample regression ends at `no_trigger` without a "
            "decision, proving the trigger stage filters noise instead of automating every payload.",
            "",
            "4. **Evaluation + execution are separable** — Summaries include `evaluation_recommendation` and "
            "`execution_status` so demos can show policy and quality gates before actuation.",
            "",
        ]
    )
    if any_rejected or any_human:
        lines.extend(
            [
                "5. **Gates block unsafe paths** — This digest includes at least one run where evaluation returns "
                "`human_review` and execution is `rejected`, so Mesh does not silently apply actions that fail "
                "readiness checks (for example repo-patch prerequisites).",
                "",
            ]
        )
    else:
        lines.append(
            "5. **Gates before actuation** — Evaluation can return `human_review` and orchestration `rejected` when "
            "readiness checks fail; re-run with fixtures tuned to your environment to exercise that path.\n"
        )
        lines.append("")
    lines.extend(
        [
            "6. **Richer modes** — The same runner supports `native` / `promptfoo` evaluation and `native` / `goose` "
            "orchestration. Use `--holistic-matrix` to sweep all four combinations across every signal fixture in one session.",
            "",
            f"**Modes this digest:** {modes_label}",
            "",
            "## Data files",
            "",
            "- `data/run_summaries.json` — machine-readable summaries",
            "",
            "---",
            "",
            "*Extend with `python3 services/skills/goose-autoresearch/scripts/run_minimax_research.py --session-dir "
            f"{out_dir.as_posix()}` (use `--minimax` on this script to chain automatically).*",
            "",
        ]
    )
    (synth / "showcase-insights.md").write_text("\n".join(lines), encoding="utf-8")


def _write_manifest(
    out_dir: Path,
    modes_label: str,
    summaries: list[dict[str, Any]],
    *,
    embed_minimax_question: bool,
    pending_minimax_run: bool,
) -> None:
    base_q = (
        f"Empirical Mesh showcase ({modes_label}): multi-scenario pipeline digest — "
        "see synthesis/showcase-insights.md and data/run_summaries.json"
    )
    if embed_minimax_question:
        blob = json.dumps(summaries, indent=2, sort_keys=True)
        cap = 28_000 if len(summaries) > 6 else 14_000
        if len(blob) > cap:
            blob = blob[:cap] + "\n…[truncated]…\n"
        base_q = (
            "You are synthesizing a strategic narrative for Mesh Intelligence using **only** the empirical JSON below "
            "(from real `FirstSlicePipeline` runs: ingest→trigger→decision→evaluation→orchestration→feedback). "
            "Explain why this architecture is strong for policy-guided remediation: staged audit trail, trigger gating, "
            "multiple signal families, separable evaluation vs execution. Avoid hype terms; ground every claim in the metrics. "
            "Call out what would convince a technical buyer vs an executive.\n\n"
            "## Empirical run_summaries\n\n```json\n"
            f"{blob}\n```"
        )
    if pending_minimax_run:
        status = "showcase_ready_for_minimax"
    else:
        status = "showcase_complete"
    manifest = {
        "session_id": out_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner": "mesh_showcase_research",
        "question": base_q,
        "status": status,
        "topology": {"lead": "pipeline", "workers": []},
        "paths": {
            "session_dir": str(out_dir),
            "results_dir": str(out_dir / "data"),
            "synthesis_dir": str(out_dir / "synthesis"),
        },
        "mesh_showcase_modes": modes_label,
        "holistic_matrix": any("matrix_row" in s for s in summaries),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "README.md").write_text(
        f"# {out_dir.name}\n\n"
        "Generated by `scripts/mesh_showcase_research.py`.\n\n"
        "- `data/run_summaries.json`\n"
        "- `synthesis/showcase-insights.md`\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesh multi-scenario showcase and insights digest.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Research session directory (default: .mesh-runtime-state/research/<timestamp>-mesh-showcase)",
    )
    parser.add_argument(
        "--evaluation-mode",
        default="native",
        choices=("native", "promptfoo"),
        help="RuntimeConfig.evaluation_mode for all scenarios",
    )
    parser.add_argument(
        "--orchestration-mode",
        default="native",
        choices=("native", "goose"),
        help="RuntimeConfig.orchestration_mode for all scenarios",
    )
    parser.add_argument(
        "--minimax",
        action="store_true",
        help="After digest, run MiniMax multi-wave research on this session (needs API keys; see run_minimax_research.py)",
    )
    parser.add_argument(
        "--embed-minimax-prompt",
        action="store_true",
        help="Embed the long MiniMax-oriented empirical question in manifest.json but do not invoke MiniMax "
        "(for external orchestrators such as overnight_mesh_autoresearch.py).",
    )
    parser.add_argument(
        "--holistic-matrix",
        action="store_true",
        help="Sweep evaluation ∈ {native, promptfoo} × orchestration ∈ {native, goose} across all built-in "
        "scenarios (12 FirstSlicePipeline runs). Ignores single --evaluation-mode / --orchestration-mode flags.",
    )
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.output
    if out_dir is None:
        cfg = RuntimeConfig.from_env()
        out_dir = Path(cfg.state_directory) / "research" / f"{ts}-mesh-showcase"
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    scenarios = _build_scenarios()
    if args.holistic_matrix:
        if os.environ.get("MESH_SHOWCASE_HOLISTIC_FAST", "").lower() in ("1", "true", "yes"):
            pairs = [("native", "native")]
            modes_label = (
                f"holistic_matrix FAST {len(pairs)}×{len(scenarios)}={len(pairs) * len(scenarios)} "
                "(MESH_SHOWCASE_HOLISTIC_FAST=1)"
            )
        else:
            pairs = holistic_eval_orchestration_pairs()
            modes_label = (
                f"holistic_matrix {len(pairs)}×{len(scenarios)}={len(pairs) * len(scenarios)} "
                "runs (eval×orch × fixtures)"
            )
        summaries = _run_holistic_matrix_summaries(scenarios, pairs)
    else:
        modes_label = f"evaluation={args.evaluation_mode}, orchestration={args.orchestration_mode}"
        summaries = []
        for name, builder in scenarios:
            summaries.append(
                _run_scenario(
                    name,
                    builder,
                    evaluation_mode=args.evaluation_mode,
                    orchestration_mode=args.orchestration_mode,
                )
            )

    (data_dir / "run_summaries.json").write_text(
        json.dumps(summaries, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_insights_md(summaries, out_dir, modes_label)
    embed = bool(args.minimax or args.embed_minimax_prompt)
    _write_manifest(
        out_dir,
        modes_label,
        summaries,
        embed_minimax_question=embed,
        pending_minimax_run=bool(args.minimax),
    )

    print(out_dir)
    print((out_dir / "synthesis" / "showcase-insights.md").as_posix())

    if args.minimax:
        runner = REPO_ROOT / "services/skills/goose-autoresearch/scripts/run_minimax_research.py"
        if not runner.is_file():
            raise SystemExit("MiniMax runner not found; expected services/skills/goose-autoresearch/scripts/run_minimax_research.py")
        proc = subprocess.run(
            [sys.executable, str(runner), "--session-dir", str(out_dir)],
            cwd=REPO_ROOT,
        )
        raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
