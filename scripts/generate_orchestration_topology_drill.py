#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.orchestration_drill import (
    build_orchestration_topology_drill_packet,
    verify_orchestration_topology_drill,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a mesh.orchestration_topology_drill.v1 proof from a Mesh run export package."
    )
    parser.add_argument("--run-export", required=True, help="Path to a mesh.run_export.v1 package JSON.")
    parser.add_argument("--output", required=True, help="Write the topology drill proof JSON to this path.")
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--environment", default="staging")
    parser.add_argument("--state-backend", default="postgres", choices=["postgres", "file"])
    parser.add_argument("--profile-ref", default="config/orchestration-topology.profile.json")
    parser.add_argument("--run-export-ref", default="")
    parser.add_argument("--readiness-ref", default="artifact://integration_readiness")
    parser.add_argument("--operator-approval-recorded", action="store_true")
    parser.add_argument("--bounded-action-execution-ref", default="")
    parser.add_argument("--evidence-ref", action="append", default=[])
    parser.add_argument("--drill-id", default="")
    parser.add_argument("--json", action="store_true", help="Print the generated proof packet.")
    args = parser.parse_args()

    run_export = json.loads(Path(args.run_export).read_text(encoding="utf-8"))
    packet = build_orchestration_topology_drill_packet(
        run_export=run_export,
        operator_id=args.operator_id,
        environment=args.environment,
        state_backend=args.state_backend,
        profile_ref=args.profile_ref,
        run_export_ref=args.run_export_ref or None,
        readiness_ref=args.readiness_ref,
        operator_approval_recorded=args.operator_approval_recorded,
        bounded_action_execution_ref=args.bounded_action_execution_ref or None,
        evidence_refs=args.evidence_ref,
        drill_id=args.drill_id or None,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verify_orchestration_topology_drill(output_path)
    if verification["status"] != "pass":
        print(json.dumps(verification, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(packet, indent=2, sort_keys=True))
    else:
        print(f"pass: {output_path} {packet['drill_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
