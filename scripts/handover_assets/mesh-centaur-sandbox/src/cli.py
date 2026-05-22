from __future__ import annotations

import argparse
import json
import sys

from mesh_centaur_sandbox.verify_e2e import verify_package_e2e


def main() -> int:
    parser = argparse.ArgumentParser(prog="mesh-centaur-sandbox")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_e2e = sub.add_parser("verify-e2e", help="Verify Centaur sandbox profile and live proof")
    verify_e2e.add_argument("--json", action="store_true")

    args = parser.parse_args()
    result = verify_package_e2e()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: mesh-centaur-sandbox verify-e2e")
        for blocker in result.get("blockers", []):
            print(f"  blocker: {blocker}", file=sys.stderr)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
