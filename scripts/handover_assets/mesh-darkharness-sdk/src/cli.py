from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mesh_darkharness.verify_e2e import verify_package_e2e, verify_packet_file


def main() -> int:
    parser = argparse.ArgumentParser(prog="mesh-darkharness")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_e2e = sub.add_parser("verify-e2e", help="Verify Darkharness SDK end-to-end")
    verify_e2e.add_argument("--json", action="store_true")
    verify_e2e.add_argument("--with-mesh-live", action="store_true")

    verify_packet = sub.add_parser("verify-packet", help="Validate a Darkharness pilot packet fixture")
    verify_packet.add_argument("packet_path", type=Path)
    verify_packet.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "verify-e2e":
        result = verify_package_e2e(with_mesh_live=args.with_mesh_live)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"{result['status']}: mesh-darkharness verify-e2e")
            for blocker in result.get("blockers", []):
                print(f"  blocker: {blocker}", file=sys.stderr)
        return 0 if result["status"] == "pass" else 1

    result = verify_packet_file(args.packet_path)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: verify-packet {args.packet_path}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
