#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.recursive_chaos import (  # noqa: E402
    DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY,
    verify_recursive_chaos_arena_profiles,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh recursive chaos arena profile registry.")
    parser.add_argument(
        "--profiles",
        default=str(DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY),
        help="Path to mesh.recursive_chaos.arena_profiles.v1 JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_recursive_chaos_arena_profiles(args.profiles)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['profile_count']} recursive chaos arena profiles checked")
        if payload["blockers"]:
            print("blockers: " + ", ".join(payload["blockers"]))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
