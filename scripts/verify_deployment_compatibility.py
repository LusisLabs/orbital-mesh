#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.config import DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH
from shared.mesh_runtime.deployment_compatibility import verify_deployment_compatibility_registry

VERIFICATION_SCHEMA_VERSION = "mesh.deployment_compatibility_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh deployment compatibility registry.")
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH),
        help="Path to mesh.deployment_compatibility.registry.v1 JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()
    payload = verify_deployment_compatibility_registry(args.registry)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['target_count']} deployment targets checked")
        if payload["blockers"]:
            print("blockers: " + ", ".join(payload["blockers"]))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
