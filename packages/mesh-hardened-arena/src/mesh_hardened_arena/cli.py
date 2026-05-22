from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mesh_hardened_arena.verify_e2e import verify_package_e2e


def main() -> int:
    parser = argparse.ArgumentParser(prog="mesh-hardened-arena")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_e2e = sub.add_parser("verify-e2e", help="Verify Hardened Arena pipeline end-to-end")
    verify_e2e.add_argument("--json", action="store_true")
    verify_e2e.add_argument("--output-dir", type=Path, default=None)

    args = parser.parse_args()
    result = verify_package_e2e(output_dir=args.output_dir)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: mesh-hardened-arena verify-e2e")
        for blocker in result.get("blockers", []):
            print(f"  blocker: {blocker}", file=sys.stderr)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
