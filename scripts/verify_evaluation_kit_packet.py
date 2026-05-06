#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.evaluation_kit import EVALUATION_KIT_VERIFICATION_VERSION, verify_evaluation_kit_packet

if EVALUATION_KIT_VERIFICATION_VERSION != "mesh.evaluation_kit_packet_verification.v1":
    raise RuntimeError("unexpected evaluation-kit verification schema version")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an Orbital Mesh evaluation-kit packet.")
    parser.add_argument("--packet", required=True, help="Path to mesh.evaluation_kit_packet.v1 JSON.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()
    payload = verify_evaluation_kit_packet(args.packet)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload.get('sample_run_id') or 'no sample run'}")
        for blocker in payload["blockers"]:
            print(f"blocker {blocker}")
        for error in payload["errors"]:
            print(f"error {error}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
