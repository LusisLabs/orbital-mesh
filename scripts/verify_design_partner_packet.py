#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.design_partner import DESIGN_PARTNER_VERIFICATION_VERSION, verify_design_partner_packet


EXPECTED_DESIGN_PARTNER_VERIFICATION_SCHEMA = "mesh.design_partner_packet_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Mesh design-partner pilot packet.")
    parser.add_argument("--packet", required=True, help="Path to a mesh.design_partner_packet.v1 JSON packet.")
    parser.add_argument("--expected-go-no-go-sha", default="", help="Expected captured pilot go/no-go packet SHA-256.")
    parser.add_argument(
        "--expected-release-provenance-sha",
        default="",
        help="Expected captured release-provenance packet SHA-256.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_design_partner_packet(
        args.packet,
        expected_go_no_go_sha=args.expected_go_no_go_sha,
        expected_release_provenance_sha=args.expected_release_provenance_sha,
    )
    if (
        payload.get("schema_version") != DESIGN_PARTNER_VERIFICATION_VERSION
        or payload.get("schema_version") != EXPECTED_DESIGN_PARTNER_VERIFICATION_SCHEMA
    ):
        payload = {**payload, "status": "fail", "error": "unexpected verification schema version"}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for name, passed in payload["checks"].items():
            state = "pass" if passed else "fail"
            print(f"{state} {name}")
        if payload.get("error"):
            print(payload["error"], file=sys.stderr)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
