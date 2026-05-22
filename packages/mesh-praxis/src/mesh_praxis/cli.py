from __future__ import annotations

import argparse
import json
import sys

from mesh_praxis.verify_e2e import build_proof_packet, verify_package_e2e


def main() -> int:
    parser = argparse.ArgumentParser(prog="mesh-praxis")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_e2e = sub.add_parser("verify-e2e", help="Verify Praxis pipeline end-to-end")
    verify_e2e.add_argument("--json", action="store_true")

    build_packet = sub.add_parser("build-proof-packet", help="Build the deterministic P8 proof packet")
    build_packet.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "verify-e2e":
        result = verify_package_e2e()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"{result['status']}: mesh-praxis verify-e2e")
            for blocker in result.get("blockers", []):
                print(f"  blocker: {blocker}", file=sys.stderr)
        return 0 if result["status"] == "pass" else 1

    packet = build_proof_packet()
    if args.json:
        print(json.dumps(packet, indent=2, sort_keys=True))
    else:
        print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
