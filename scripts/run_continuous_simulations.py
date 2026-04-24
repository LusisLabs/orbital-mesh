#!/usr/bin/env python3
"""Run bounded simulation benchmark cycles continuously.

The loop is intentionally finite by default. Use ``--cycles 0`` only under an
external supervisor that owns stop/restart policy and artifact retention.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / ".mesh-runtime-state" / "simulation-stress" / "continuous"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _rollup(cycle_dirs: list[Path]) -> dict[str, Any]:
    summaries = [_load_json(path / "summary.json") for path in cycle_dirs]
    summaries = [summary for summary in summaries if summary]
    total_runs = sum(int(summary.get("total_runs", 0) or 0) for summary in summaries)
    passed = sum(int(summary.get("benchmark_passed", 0) or 0) for summary in summaries)
    weighted_score = sum(float(summary.get("avg_score", 0.0) or 0.0) * int(summary.get("total_runs", 0) or 0) for summary in summaries)
    blockers: dict[str, int] = {}
    blocker_classes: dict[str, int] = {}
    decisions: dict[str, int] = {}
    failures: list[Any] = []
    for summary in summaries:
        for key, value in (summary.get("blocking_reason_counts") or {}).items():
            blockers[str(key)] = blockers.get(str(key), 0) + int(value)
        for key, value in (summary.get("blocker_class_counts") or {}).items():
            blocker_classes[str(key)] = blocker_classes.get(str(key), 0) + int(value)
        for key, value in (summary.get("decision_counts") or {}).items():
            decisions[str(key)] = decisions.get(str(key), 0) + int(value)
        failures.extend(summary.get("failures") or [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_count": len(summaries),
        "total_runs": total_runs,
        "benchmark_passed": passed,
        "pass_rate": round(passed / total_runs, 4) if total_runs else 0.0,
        "avg_score": round(weighted_score / total_runs, 4) if total_runs else 0.0,
        "blocking_reason_counts": blockers,
        "blocker_class_counts": blocker_classes,
        "decision_counts": decisions,
        "failures": failures,
    }


def _write_rollup(root: Path, cycle_dirs: list[Path]) -> None:
    rollup = _rollup(cycle_dirs)
    root.joinpath("rollup.json").write_text(json.dumps(rollup, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Mesh continuous simulation rollup",
        "",
        f"_Generated {rollup['generated_at']}_",
        "",
        f"- Cycles: {rollup['cycle_count']}",
        f"- Runs: {rollup['total_runs']}",
        f"- Pass rate: {rollup['pass_rate']}",
        f"- Average score: {rollup['avg_score']}",
        f"- Failures: {len(rollup['failures'])}",
        "",
        "## Top blockers",
        "",
    ]
    blockers = sorted(rollup["blocking_reason_counts"].items(), key=lambda item: (-item[1], item[0]))
    lines.extend([f"- {key}: {value}" for key, value in blockers[:10]] or ["- none"])
    lines.extend(["", "## Blocker Classes", ""])
    blocker_class_rows = sorted(rollup["blocker_class_counts"].items(), key=lambda item: (-item[1], item[0]))
    lines.extend([f"- {key}: {value}" for key, value in blocker_class_rows] or ["- none"])
    lines.extend(["", "## Decision mix", ""])
    decisions = sorted(rollup["decision_counts"].items(), key=lambda item: (-item[1], item[0]))
    lines.extend([f"- {key}: {value}" for key, value in decisions] or ["- none"])
    root.joinpath("rollup-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run continuous bounded Mesh simulation benchmark cycles.")
    parser.add_argument("--cycles", type=int, default=3, help="Number of cycles to run. Use 0 for forever.")
    parser.add_argument("--iterations", type=int, default=32)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--sleep-seconds", type=float, default=60.0)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--no-randomize", action="store_true")
    parser.add_argument("--seed", type=int, default=20260424)
    args = parser.parse_args()

    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    matrix = REPO_ROOT / "scripts" / "run_simulation_matrix.py"
    cycle_dirs: list[Path] = []
    cycle = 0
    exit_code = 0
    try:
        while args.cycles == 0 or cycle < args.cycles:
            cycle += 1
            output = root / f"cycle-{cycle:04d}-{_stamp()}"
            command = [
                sys.executable,
                str(matrix),
                "--iterations",
                str(args.iterations),
                "--workers",
                str(args.workers),
                "--timeout-seconds",
                str(args.timeout_seconds),
                "--output",
                str(output),
            ]
            if not args.no_randomize:
                command.extend(["--randomize", "--seed", str(args.seed + cycle)])
            result = subprocess.run(command, cwd=REPO_ROOT, check=False)
            cycle_dirs.append(output)
            _write_rollup(root, cycle_dirs)
            if result.returncode != 0:
                exit_code = result.returncode
                if args.stop_on_failure:
                    break
            if args.cycles == 0 or cycle < args.cycles:
                time.sleep(max(0.0, args.sleep_seconds))
    except KeyboardInterrupt:
        exit_code = 130
    _write_rollup(root, cycle_dirs)
    print(json.dumps({"root": str(root), **_rollup(cycle_dirs)}, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
