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
import shutil
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
        "| Scenario | Trigger? | Decision | Eval | Execution | Feedback | Events | ms |",
        "|----------|----------|----------|------|-----------|----------|--------|-----|",
    ]
    for s in summaries:
        lines.append(
            "| {scenario} | {te} | {dt} | {er} | {xs} | {fo} | {ec} | {ms} |".format(
                scenario=s["scenario"],
                te="yes" if s["trigger_emitted"] else "no",
                dt=s.get("decision_type") or "—",
                er=s.get("evaluation_recommendation") or "—",
                xs=s.get("execution_status") or "—",
                fo=s.get("feedback_outcome") or "—",
                ec=s["stage_event_count"],
                ms=s["elapsed_ms"],
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
        lines.append(f"### {s['scenario']}")
        lines.append("")
        lines.append("```")
        lines.append(" → ".join(s["event_chain"]) if s["event_chain"] else "(no events)")
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
            "orchestration; re-run with `--evaluation-mode promptfoo` or `--orchestration-mode goose` when those "
            "integrations are configured.",
            "",
            f"**Modes this digest:** {modes_label}",
            "",
            "## Data files",
            "",
            "- `data/run_summaries.json` — machine-readable summaries",
            "",
            "---",
            "",
            "*Extend with `python3 .cursor/skills/goose-autoresearch/scripts/run_minimax_research.py --session-dir "
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
    for_minimax: bool,
) -> None:
    base_q = (
        f"Empirical Mesh showcase ({modes_label}): multi-scenario pipeline digest — "
        "see synthesis/showcase-insights.md and data/run_summaries.json"
    )
    if for_minimax:
        blob = json.dumps(summaries, indent=2, sort_keys=True)
        if len(blob) > 14_000:
            blob = blob[:14_000] + "\n…[truncated]…\n"
        base_q = (
            "You are synthesizing a strategic narrative for Mesh Intelligence using **only** the empirical JSON below "
            "(from real `FirstSlicePipeline` runs: ingest→trigger→decision→evaluation→orchestration→feedback). "
            "Explain why this architecture is strong for policy-guided remediation: staged audit trail, trigger gating, "
            "multiple signal families, separable evaluation vs execution. Avoid hype terms; ground every claim in the metrics. "
            "Call out what would convince a technical buyer vs an executive.\n\n"
            "## Empirical run_summaries\n\n```json\n"
            f"{blob}\n```"
        )
    manifest = {
        "session_id": out_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner": "mesh_showcase_research",
        "question": base_q,
        "status": "showcase_complete" if not for_minimax else "showcase_ready_for_minimax",
        "topology": {"lead": "pipeline", "workers": []},
        "paths": {
            "session_dir": str(out_dir),
            "results_dir": str(out_dir / "data"),
            "synthesis_dir": str(out_dir / "synthesis"),
        },
        "mesh_showcase_modes": modes_label,
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

    modes_label = f"evaluation={args.evaluation_mode}, orchestration={args.orchestration_mode}"
    summaries: list[dict[str, Any]] = []
    for name, builder in _build_scenarios():
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
    _write_manifest(out_dir, modes_label, summaries, for_minimax=args.minimax)

    print(out_dir)
    print((out_dir / "synthesis" / "showcase-insights.md").as_posix())

    if args.minimax:
        runner = REPO_ROOT / ".cursor/skills/goose-autoresearch/scripts/run_minimax_research.py"
        if not runner.is_file():
            raise SystemExit("MiniMax runner not found; expected .cursor/skills/goose-autoresearch/scripts/run_minimax_research.py")
        proc = subprocess.run(
            [sys.executable, str(runner), "--session-dir", str(out_dir)],
            cwd=REPO_ROOT,
        )
        raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
