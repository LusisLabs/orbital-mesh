#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.agentic_operator_provenance import verify_agentic_operator_source_provenance
from shared.mesh_runtime.config import DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh agentic-operator source provenance.")
    parser.add_argument(
        "--provenance",
        default=str(DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH),
        help="Path to mesh.agentic_operator_source_provenance.v1 JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()
    payload = verify_agentic_operator_source_provenance(args.provenance)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['source_path_count']} source paths checked")
        if payload["errors"]:
            print("errors: " + ", ".join(payload["errors"]))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
