#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.config import DEFAULT_THREAT_MODEL_REGISTER_PATH
from shared.mesh_runtime.threat_model import verify_threat_model_register


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh threat-model finding register.")
    parser.add_argument("--register", default=str(DEFAULT_THREAT_MODEL_REGISTER_PATH), help="Path to mesh.threat_model_register.v1 JSON.")
    parser.add_argument("--today", help="Override today's date as YYYY-MM-DD for deterministic tests.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else None
    payload = verify_threat_model_register(args.register, today=today)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['finding_count']} findings checked")
        if payload["errors"]:
            print("errors: " + ", ".join(payload["errors"]))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
