#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hardened_arena_proof import (  # noqa: E402
    output_path_is_generated,
    run_hardened_arena_proof,
    write_hardened_arena_proof,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fail-closed proof checks against an already-created hardened arena target.")
    parser.add_argument("--evidence", required=True, help="Target-specific proof evidence input JSON.")
    parser.add_argument("--output", required=True, help="Output proof path under ignored dist/ generated output.")
    parser.add_argument("--timeout-seconds", type=float, default=5.0, help="HTTP check timeout.")
    args = parser.parse_args()

    if not output_path_is_generated(args.output):
        print("refusing to write generated proof outside ignored dist/ output", file=sys.stderr)
        return 2
    proof = run_hardened_arena_proof(args.evidence, timeout_seconds=args.timeout_seconds)
    write_hardened_arena_proof(proof, args.output)
    print(f"generated hardened arena proof at {args.output} with status {proof['readiness_posture']['status']}")
    return 0 if proof["readiness_posture"]["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
