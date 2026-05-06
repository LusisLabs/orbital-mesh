#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.config import DEFAULT_DATA_CLASSIFICATION_POLICY_PATH
from shared.mesh_runtime.data_classification import verify_data_classification_policy


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh data-classification policy.")
    parser.add_argument(
        "--policy",
        default=str(DEFAULT_DATA_CLASSIFICATION_POLICY_PATH),
        help="Path to mesh.data_classification_policy.v1 JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()
    payload = verify_data_classification_policy(args.policy)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['class_count']} data classes checked")
        if payload["errors"]:
            print("errors: " + ", ".join(payload["errors"]))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
