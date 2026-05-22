#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hardened_arena_packet import verify_hardened_arena_packet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Hardened Production Arena proof packet.")
    parser.add_argument("--packet", required=True, help="Path to mesh.hardened_arena.packet.v1 JSON.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_hardened_arena_packet(args.packet)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: hardened arena packet checked for {payload['profile_id']}")
        if payload["blockers"]:
            print("blockers: " + ", ".join(payload["blockers"]))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
