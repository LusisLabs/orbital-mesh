#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.production_autonomy_clearance import (
    PRODUCTION_AUTONOMY_CLEARANCE_VERSION,
    verify_production_autonomy_clearance,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify aggregate production-autonomy clearance proof packets.")
    parser.add_argument("--repeatability-proof", required=True, help="Path to a mesh.repeatability_proof.v1 packet.")
    parser.add_argument("--production-target-proof", required=True, help="Path to a mesh.production_target_proof.v1 packet.")
    parser.add_argument("--provider-action-scope-proof", required=True, help="Path to a mesh.provider_action_scope_proof.v1 packet.")
    parser.add_argument("--watch-mode-proof", required=True, help="Path to a mesh.watch_mode_proof.v1 packet.")
    parser.add_argument("--incident-coverage-proof", required=True, help="Path to a mesh.incident_coverage_proof.v1 packet.")
    parser.add_argument("--on-call-drill-proof", required=True, help="Path to a mesh.on_call_drill.v1 packet.")
    parser.add_argument("--expected-head", default="", help="Require repeatability proof to match this git commit.")
    parser.add_argument("--expected-environment", default="", help="Require environment-bound proofs to match this environment.")
    parser.add_argument(
        "--registry",
        default="config/connector-certification.registry.json",
        help="Connector certification registry path.",
    )
    parser.add_argument(
        "--allow-fixture",
        action="store_true",
        help="Allow fixture-level proof packets. Do not use for production-autonomy claims.",
    )
    parser.add_argument(
        "--allow-dirty-env",
        action="store_true",
        help="Relax strict repeatability clean-env checks. Do not use for release claims.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_production_autonomy_clearance(
        repeatability_proof=args.repeatability_proof,
        production_target_proof=args.production_target_proof,
        provider_action_scope_proof=args.provider_action_scope_proof,
        watch_mode_proof=args.watch_mode_proof,
        incident_coverage_proof=args.incident_coverage_proof,
        on_call_drill_proof=args.on_call_drill_proof,
        expected_head=args.expected_head or None,
        expected_environment=args.expected_environment or None,
        registry_path=args.registry,
        require_live=not args.allow_fixture,
        require_clean_env=not args.allow_dirty_env,
    )
    if payload.get("schema_version") != PRODUCTION_AUTONOMY_CLEARANCE_VERSION:
        payload = {**payload, "status": "fail", "error": "unexpected_schema_version"}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for name, passed in payload["checks"].items():
            state = "pass" if passed else "fail"
            print(f"{state} {name}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
