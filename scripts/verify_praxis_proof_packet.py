#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.praxis import build_praxis_demo_proof_packet
from shared.mesh_runtime.schema_validation import SchemaValidationError, validate_payload

PROOF_PACKET_PATH = REPO_ROOT / "fixtures" / "praxis" / "p8_proof_packet.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Praxis P8 proof packet fixture.")
    parser.add_argument("--write", action="store_true", help="Write the deterministic proof packet fixture before verifying it.")
    args = parser.parse_args()

    expected = build_praxis_demo_proof_packet()
    if args.write:
        PROOF_PACKET_PATH.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        actual = json.loads(PROOF_PACKET_PATH.read_text(encoding="utf-8"))
        validate_payload("praxis/e2e-proof-packet.schema.json", actual)
        if actual != expected:
            raise SchemaValidationError(f"{PROOF_PACKET_PATH}: proof packet fixture is stale")
        if actual["status"] != "complete":
            raise SchemaValidationError(f"{PROOF_PACKET_PATH}: proof packet is not complete")
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        print(f"Praxis proof packet verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Praxis proof packet verification passed: {PROOF_PACKET_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
