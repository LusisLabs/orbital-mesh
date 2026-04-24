#!/usr/bin/env python3
"""Run Mesh sandbox simulations in parallel and write stress-test artifacts.

This harness exercises the control-plane coordinator, not just the first-slice
pipeline. It uses isolated local state by default, creates concurrent simulation
runs, waits for terminal states, and exports a digest of benchmark and
reconciliation artifacts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.control_plane import TERMINAL_STAGES, RunCoordinator  # noqa: E402
from services.simulation import SimulationService  # noqa: E402
from shared.mesh_runtime import RuntimeConfig  # noqa: E402


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scenario_payload(config: RuntimeConfig, scenario_id: str, index: int) -> dict[str, Any]:
    scenario, payload = SimulationService(config).build_run_payload(
        scenario_id,
        {
            "evaluation_mode": "native",
            "orchestration_mode": "native",
            "steering_mode": "interruptible_auto",
            "pause_points": [],
        },
    )
    signal = deepcopy(payload["signal_payload"])
    signal["signal_id"] = f"{signal.get('signal_id', scenario.scenario_id)}_stress_{index:04d}"
    if isinstance(signal.get("related_context"), dict):
        signal["related_context"]["stress_run_index"] = index
    payload["signal_payload"] = signal
    payload["simulation_context"]["stress_run_index"] = index
    return payload


def _wait_for_run(coordinator: RunCoordinator, run_id: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        run = coordinator.get_run(run_id)
        artifacts = run.get("artifacts", {}) if isinstance(run, dict) and isinstance(run.get("artifacts"), dict) else {}
        if run and run.get("stage") in TERMINAL_STAGES | {"awaiting_operator"} and "benchmark_score" in artifacts:
            return run
        time.sleep(0.05)
    run = coordinator.get_run(run_id)
    raise TimeoutError(
        f"run {run_id} did not reach terminal+benchmark state; "
        f"last={run and run.get('stage')} artifacts={sorted((run or {}).get('artifacts', {}).keys()) if run else []}"
    )


def _run_one(
    *,
    base_state_dir: Path,
    export_path: Path,
    scenario_id: str,
    index: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    state_dir = base_state_dir / f"worker-{index:04d}"
    agents_path = state_dir / "service-agents.json"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_path.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "service": "semantic-search",
                        "scope": {"services": ["semantic-search"], "namespaces": ["search"], "deployments": ["semantic-search"]},
                        "preferred_lanes": ["goose", "hermes", "codex", "claudecode", "openclaw", "evo"],
                    },
                    {
                        "service": "api-gateway",
                        "scope": {"services": ["api-gateway"], "flags": ["semantic_search_v2"]},
                        "preferred_lanes": ["goose", "hermes"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    config = RuntimeConfig(
        state_directory=str(state_dir),
        vault_path=str(state_dir / "vault"),
        research_directory=str(state_dir / "research"),
        integrations_config_path=str(state_dir / "integrations.json"),
        evaluation_mode="native",
        orchestration_mode="native",
        simulation_enabled=True,
        simulation_context_allowlist=("mesh-compose",),
        benchmark_export_path=str(export_path),
        agent_reconciliation_enabled=True,
        service_agents_config_path=str(agents_path),
    )
    coordinator = RunCoordinator(config=config)
    payload = _scenario_payload(config, scenario_id, index)
    started = time.perf_counter()
    created = coordinator.create_run(payload)
    run = _wait_for_run(coordinator, created["run_id"], timeout_seconds)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    artifacts = run.get("artifacts", {}) if isinstance(run.get("artifacts"), dict) else {}
    benchmark = artifacts.get("benchmark_score", {}) if isinstance(artifacts.get("benchmark_score"), dict) else {}
    reconciliation = artifacts.get("reconciliation", {}) if isinstance(artifacts.get("reconciliation"), dict) else {}
    evaluation = artifacts.get("evaluation", {}) if isinstance(artifacts.get("evaluation"), dict) else {}
    decision = artifacts.get("decision", {}) if isinstance(artifacts.get("decision"), dict) else {}
    return {
        "index": index,
        "scenario_id": scenario_id,
        "run_id": run["run_id"],
        "stage": run.get("stage"),
        "status": run.get("status"),
        "elapsed_ms": elapsed_ms,
        "event_count": len(run.get("events", [])) if isinstance(run.get("events"), list) else 0,
        "decision_type": decision.get("decision_type"),
        "evaluation_recommendation": evaluation.get("final_recommendation"),
        "blocking_reasons": evaluation.get("blocking_reasons", []),
        "benchmark": benchmark,
        "reconciliation": reconciliation,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    terminal = sum(1 for row in rows if row.get("stage") in TERMINAL_STAGES)
    passed = sum(1 for row in rows if row.get("benchmark", {}).get("passed"))
    scores = [float(row.get("benchmark", {}).get("score", 0.0) or 0.0) for row in rows]
    elapsed = [float(row.get("elapsed_ms", 0.0) or 0.0) for row in rows]
    by_decision: dict[str, int] = {}
    blockers: dict[str, int] = {}
    disagreements = 0
    for row in rows:
        by_decision[str(row.get("decision_type") or "none")] = by_decision.get(str(row.get("decision_type") or "none"), 0) + 1
        if row.get("reconciliation", {}).get("disagreement"):
            disagreements += 1
        for blocker in row.get("blocking_reasons") or []:
            blockers[str(blocker)] = blockers.get(str(blocker), 0) + 1
    return {
        "generated_at": _timestamp(),
        "total_runs": total,
        "terminal_runs": terminal,
        "benchmark_passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "avg_elapsed_ms": round(sum(elapsed) / len(elapsed), 2) if elapsed else 0.0,
        "max_elapsed_ms": max(elapsed) if elapsed else 0.0,
        "decision_counts": by_decision,
        "blocking_reason_counts": blockers,
        "reconciliation_disagreements": disagreements,
    }


def _write_markdown(out_dir: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Mesh parallel simulation stress report",
        "",
        f"_Generated {summary['generated_at']}_",
        "",
        "## Summary",
        "",
        f"- Runs: {summary['terminal_runs']}/{summary['total_runs']} terminal",
        f"- Benchmark pass rate: {summary['pass_rate']}",
        f"- Average benchmark score: {summary['avg_score']}",
        f"- Average elapsed: {summary['avg_elapsed_ms']} ms",
        f"- Max elapsed: {summary['max_elapsed_ms']} ms",
        f"- Reconciliation disagreements: {summary['reconciliation_disagreements']}",
        "",
        "## Improvements surfaced",
        "",
    ]
    blockers = summary.get("blocking_reason_counts", {})
    if blockers:
        lines.append("- Repeated evaluation blockers should become first-class scenario labels so benchmark failures are grouped by policy cause.")
    else:
        lines.append("- No repeated evaluation blockers surfaced in this run.")
    if summary.get("reconciliation_disagreements", 0):
        lines.append("- Agent-lane disagreements should be promoted into UI filters and benchmark dimensions.")
    else:
        lines.append("- Reconciliation stayed stable; add adversarial lanes next to stress disagreement handling.")
    if summary.get("pass_rate", 0.0) < 1.0:
        lines.append("- Failed benchmark rows should be replayed with operator overrides to seed rule-learning suggestions.")
    else:
        lines.append("- All benchmark rows passed; increase chaos variety and introduce adversarial OTLP payloads next.")
    lines.extend(
        [
            "",
            "## Runs",
            "",
            "| # | Scenario | Run | Stage | Decision | Eval | Score | ms |",
            "|---|----------|-----|-------|----------|------|-------|----|",
        ]
    )
    for row in rows:
        score = row.get("benchmark", {}).get("score", 0)
        lines.append(
            f"| {row['index']} | {row['scenario_id']} | `{row['run_id']}` | {row['stage']} | "
            f"{row.get('decision_type') or '-'} | {row.get('evaluation_recommendation') or '-'} | {score} | {row['elapsed_ms']} |"
        )
    out_dir.joinpath("stress-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded Mesh simulations in parallel.")
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=Path(".mesh-runtime-state/simulation-stress/latest"))
    parser.add_argument("--keep-state", action="store_true")
    args = parser.parse_args()

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    state_root = Path(tempfile.mkdtemp(prefix="mesh-simulation-stress-"))
    export_path = out_dir / "dataset.jsonl"
    scenario_config = RuntimeConfig(
        state_directory=str(out_dir / ".scenario-catalog"),
        simulation_enabled=True,
        simulation_context_allowlist=("mesh-compose",),
    )
    scenarios = [item["scenario_id"] for item in SimulationService(scenario_config).list_scenarios()]
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = []
            for index in range(args.iterations):
                futures.append(
                    pool.submit(
                        _run_one,
                        base_state_dir=state_root,
                        export_path=export_path,
                        scenario_id=scenarios[index % len(scenarios)],
                        index=index,
                        timeout_seconds=args.timeout_seconds,
                    )
                )
            for future in as_completed(futures):
                try:
                    rows.append(future.result())
                except Exception as exc:  # noqa: BLE001 - per-cell stress result
                    failures.append({"error": f"{type(exc).__name__}: {exc}"})
    finally:
        if not args.keep_state:
            shutil.rmtree(state_root, ignore_errors=True)

    rows.sort(key=lambda row: row["index"])
    summary = _summarize(rows)
    summary["failures"] = failures
    summary["state_root"] = str(state_root) if args.keep_state else None
    summary["dataset_path"] = str(export_path)
    out_dir.joinpath("summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    out_dir.joinpath("runs.json").write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_dir, summary, rows)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
