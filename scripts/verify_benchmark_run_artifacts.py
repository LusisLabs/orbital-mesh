#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.benchmark_artifacts import (
    BENCHMARK_RUN_ARTIFACTS_VERSION,
    verify_benchmark_run_artifacts,
)

if BENCHMARK_RUN_ARTIFACTS_VERSION != "mesh.benchmark_run_artifacts_verification.v1":
    raise RuntimeError("unexpected benchmark artifact verification schema version")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Mesh benchmark run artifacts.")
    parser.add_argument("--run-dir", required=True, help="Benchmark run directory containing benchmark.json.")
    parser.add_argument("--expected-suite", default=None, help="Expected benchmark suite name.")
    parser.add_argument("--expected-scenario-id", action="append", default=[], help="Expected scenario id; repeatable.")
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument("--max-unsafe-action-rate", type=float, default=0.0)
    parser.add_argument("--min-weighted-score", type=float, default=0.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()
    payload = verify_benchmark_run_artifacts(
        args.run_dir,
        expected_suite=args.expected_suite,
        expected_scenario_ids=tuple(args.expected_scenario_id),
        min_pass_rate=args.min_pass_rate,
        max_unsafe_action_rate=args.max_unsafe_action_rate,
        min_weighted_score=args.min_weighted_score,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['run_id'] or args.run_dir}")
        for blocker in payload["blockers"]:
            print(f"blocker {blocker}")
        for error in payload["errors"]:
            print(f"error {error}", file=sys.stderr)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
