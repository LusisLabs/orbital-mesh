#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hardened_arena_catalog import (  # noqa: E402
    DEFAULT_HARDENED_ARENA_CATALOG,
    verify_hardened_arena_catalog,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh hardened arena DHI catalog.")
    parser.add_argument(
        "--catalog",
        default=str(DEFAULT_HARDENED_ARENA_CATALOG),
        help="Path to mesh.hardened_arena.catalog.v1 JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_hardened_arena_catalog(args.catalog)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['status']}: {payload['entry_count']} hardened arena catalog entries checked "
            f"({payload['image_count']} images, {payload['chart_count']} charts)"
        )
        if payload["blockers"]:
            print("blockers: " + ", ".join(payload["blockers"]))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
