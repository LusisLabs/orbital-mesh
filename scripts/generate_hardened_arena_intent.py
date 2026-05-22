#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hardened_arena_intent import (  # noqa: E402
    generate_hardened_arena_intent,
    output_dir_is_generated,
    write_hardened_arena_intent,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate review-only Hardened Production Arena intent files.")
    parser.add_argument("--profile", required=True, help="Hardened arena profile id.")
    parser.add_argument("--output-dir", required=True, help="Output directory under ignored dist/ generated output.")
    parser.add_argument("--profiles", default=None, help="Optional profile registry path.")
    args = parser.parse_args()

    if not output_dir_is_generated(args.output_dir):
        print("refusing to write generated intent outside ignored dist/ output", file=sys.stderr)
        return 2
    bundle = generate_hardened_arena_intent(args.profile, profile_registry_path=args.profiles)
    bundle_path = write_hardened_arena_intent(bundle, args.output_dir)
    print(f"generated hardened arena intent bundle for {args.profile} at {bundle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
