#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.migration_rehearsal import (
    build_migration_rehearsal_packet,
    verify_migration_rehearsal,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a mesh.migration_rehearsal.v1 proof from operator-supplied Postgres rehearsal evidence."
    )
    parser.add_argument("--output", required=True, help="Write the migration rehearsal proof JSON to this path.")
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--environment", default="staging")
    parser.add_argument("--migration-directory", default="migrations/postgres")
    parser.add_argument("--applied-migration-count", type=int, required=True)
    parser.add_argument("--rollback-ref", required=True)
    parser.add_argument("--pre-migration-snapshot-ref", required=True)
    parser.add_argument("--post-migration-validation-ref", required=True)
    parser.add_argument("--measured-apply-seconds", type=float, required=True)
    parser.add_argument("--measured-rollback-seconds", type=float, required=True)
    parser.add_argument("--rolled-back", action="store_true", help="Required when rollback was actually rehearsed.")
    parser.add_argument(
        "--destructive-changes-reviewed",
        action="store_true",
        help="Required after reviewing destructive migration statements for the target release.",
    )
    parser.add_argument("--rehearsal-id", default="")
    parser.add_argument("--json", action="store_true", help="Print the generated proof packet.")
    args = parser.parse_args()

    if not args.rolled_back:
        parser.error("--rolled-back is required; release packets cannot use unrehearsed migration rollback evidence")
    if not args.destructive_changes_reviewed:
        parser.error("--destructive-changes-reviewed is required before producing migration rehearsal proof")

    packet = build_migration_rehearsal_packet(
        operator_id=args.operator_id,
        environment=args.environment,
        migration_directory=args.migration_directory,
        applied_migration_count=args.applied_migration_count,
        rolled_back=args.rolled_back,
        rollback_ref=args.rollback_ref,
        pre_migration_snapshot_ref=args.pre_migration_snapshot_ref,
        post_migration_validation_ref=args.post_migration_validation_ref,
        destructive_changes_reviewed=args.destructive_changes_reviewed,
        measured_apply_seconds=args.measured_apply_seconds,
        measured_rollback_seconds=args.measured_rollback_seconds,
        rehearsal_id=args.rehearsal_id or None,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verify_migration_rehearsal(
        output_path,
        expected_migration_version=packet["migration_version"],
        expected_migration_combined_sha256=packet["migration_combined_sha256"],
    )
    if verification["status"] != "pass":
        print(json.dumps(verification, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(packet, indent=2, sort_keys=True))
    else:
        print(f"pass: {output_path} {packet['migration_version']} {packet['migration_combined_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
