#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hardened_arena_packet import (  # noqa: E402
    generate_hardened_arena_packet,
    output_path_is_generated,
    write_hardened_arena_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a review-only Hardened Production Arena proof packet.")
    parser.add_argument("--profile", required=True, help="Hardened arena profile id.")
    parser.add_argument("--output", required=True, help="Output packet path under ignored dist/ generated output.")
    parser.add_argument("--profiles", default=None, help="Optional profile registry path.")
    parser.add_argument("--catalog", default=None, help="Optional catalog path.")
    args = parser.parse_args()

    if not output_path_is_generated(args.output):
        print("refusing to write generated packet outside ignored dist/ output", file=sys.stderr)
        return 2
    packet = generate_hardened_arena_packet(args.profile, profile_registry_path=args.profiles, catalog_path=args.catalog)
    write_hardened_arena_packet(packet, args.output)
    print(f"generated hardened arena packet for {args.profile} at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
