#!/usr/bin/env python3
"""Run the simulation matrix and compare it with the prior benchmark trend."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / ".mesh-runtime-state" / "simulation-stress" / "nightly"


def compare_summaries(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if previous is None:
        return {"status": "baseline", "regressions": [], "previous_summary": None}
    regressions: list[str] = []
    if float(current.get("pass_rate", 0.0)) < float(previous.get("pass_rate", 0.0)):
        regressions.append("pass_rate_dropped")
    if float(current.get("avg_score", 0.0)) < float(previous.get("avg_score", 0.0)):
        regressions.append("avg_score_dropped")
    previous_elapsed = float(previous.get("avg_elapsed_ms", 0.0) or 0.0)
    current_elapsed = float(current.get("avg_elapsed_ms", 0.0) or 0.0)
    if previous_elapsed > 0 and current_elapsed > previous_elapsed * 1.25:
        regressions.append("avg_elapsed_regressed")
    if int(current.get("reconciliation_disagreements", 0)) > int(previous.get("reconciliation_disagreements", 0)):
        regressions.append("reconciliation_disagreements_increased")
    return {
        "status": "regressed" if regressions else "stable",
        "regressions": regressions,
        "previous_summary": previous,
    }


def _load_previous(root: Path, current: Path) -> dict[str, Any] | None:
    candidates = sorted(path for path in root.glob("*/summary.json") if path.parent != current)
    for path in reversed(candidates):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _write_report(output: Path, current: dict[str, Any], trend: dict[str, Any]) -> None:
    previous = trend.get("previous_summary") or {}
    lines = [
        "# Mesh nightly benchmark trend",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        f"- Status: {trend['status']}",
        f"- Current pass rate: {current.get('pass_rate', 0.0)}",
        f"- Current average score: {current.get('avg_score', 0.0)}",
        f"- Current average elapsed: {current.get('avg_elapsed_ms', 0.0)} ms",
        f"- Current disagreements: {current.get('reconciliation_disagreements', 0)}",
        f"- Previous pass rate: {previous.get('pass_rate', 'n/a')}",
        f"- Previous average score: {previous.get('avg_score', 'n/a')}",
        f"- Previous average elapsed: {previous.get('avg_elapsed_ms', 'n/a')} ms",
        f"- Previous disagreements: {previous.get('reconciliation_disagreements', 'n/a')}",
        "",
        "## Regression checks",
        "",
    ]
    regressions = trend.get("regressions") or []
    if regressions:
        lines.extend(f"- {item}" for item in regressions)
    else:
        lines.append("- none")
    output.joinpath("trend-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run nightly Mesh simulation benchmarks with trend regression checks.")
    parser.add_argument("--iterations", type=int, default=32)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--allow-regression", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.root.resolve() / stamp
    output.mkdir(parents=True, exist_ok=True)
    matrix = REPO_ROOT / "scripts" / "run_simulation_matrix.py"
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
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    current = json.loads(output.joinpath("summary.json").read_text(encoding="utf-8"))
    trend = compare_summaries(current, _load_previous(args.root.resolve(), output))
    output.joinpath("trend.json").write_text(json.dumps(trend, indent=2, sort_keys=True), encoding="utf-8")
    _write_report(output, current, trend)
    print(json.dumps({"output": str(output), **trend}, indent=2, sort_keys=True))
    return 1 if trend["status"] == "regressed" and not args.allow_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())
