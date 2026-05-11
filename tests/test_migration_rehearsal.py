from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import load_schema, validate_payload
from shared.mesh_runtime.migration_rehearsal import (
    build_migration_rehearsal_packet,
    migration_rehearsal_inventory,
    verify_migration_rehearsal,
)


class MigrationRehearsalTests(unittest.TestCase):
    def test_migration_rehearsal_schema_is_loadable(self) -> None:
        schema = load_schema("migration-rehearsal.schema.json")
        self.assertEqual(schema["title"], "MigrationRehearsal")

    def test_migration_rehearsal_passes_when_bound_to_expected_migration_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "migration-rehearsal.json"
            proof = _proof()
            validate_payload("migration-rehearsal.schema.json", proof)
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_migration_rehearsal(
                proof_path,
                expected_migration_version="004_incident_corpus",
                expected_migration_combined_sha256="a" * 64,
            )

        self.assertEqual(result["schema_version"], "mesh.migration_rehearsal_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_migration_rehearsal_blocks_missing_rollback_and_wrong_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "migration-rehearsal.json"
            proof = _proof()
            proof["rolled_back"] = False
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_migration_rehearsal(
                proof_path,
                expected_migration_version="004_incident_corpus",
                expected_migration_combined_sha256="b" * 64,
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["rolled_back"])
        self.assertFalse(result["checks"]["migration_combined_sha256_matches"])

    def test_build_migration_rehearsal_packet_binds_to_migration_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migration_dir = root / "migrations" / "postgres"
            migration_dir.mkdir(parents=True)
            (migration_dir / "001_init.sql").write_text("select 1;\n", encoding="utf-8")
            (migration_dir / "002_next.sql").write_text("select 2;\n", encoding="utf-8")

            inventory = migration_rehearsal_inventory("migrations/postgres", repo_root=root)
            packet = build_migration_rehearsal_packet(
                operator_id="platform@example.com",
                environment="staging",
                migration_directory="migrations/postgres",
                repo_root=root,
                applied_migration_count=2,
                rolled_back=True,
                rollback_ref="restore://postgres/migration-rehearsal/test",
                pre_migration_snapshot_ref="snapshot://postgres/pre-migration/test",
                post_migration_validation_ref="validation://postgres/post-migration/test",
                destructive_changes_reviewed=True,
                measured_apply_seconds=3.5,
                measured_rollback_seconds=4.5,
                rehearsal_id="migration_rehearsal_test",
                generated_at="2026-05-06T01:20:00Z",
            )

        self.assertEqual(packet["schema_version"], "mesh.migration_rehearsal.v1")
        self.assertEqual(packet["migration_directory"], "migrations/postgres")
        self.assertEqual(packet["migration_version"], "002_next")
        self.assertEqual(packet["migration_combined_sha256"], inventory["combined_sha256"])
        validate_payload("migration-rehearsal.schema.json", packet)

    def test_verify_migration_rehearsal_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "migration-rehearsal.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_migration_rehearsal.py",
                    "--proof",
                    str(proof_path),
                    "--expected-version",
                    "004_incident_corpus",
                    "--expected-combined-sha256",
                    "a" * 64,
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["schema_version"], "mesh.migration_rehearsal_verification.v1")

    def test_generate_migration_rehearsal_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "migration-rehearsal.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_migration_rehearsal.py",
                    "--output",
                    str(output_path),
                    "--operator-id",
                    "platform@example.com",
                    "--environment",
                    "staging",
                    "--applied-migration-count",
                    "6",
                    "--rolled-back",
                    "--rollback-ref",
                    "restore://postgres/migration-rehearsal/test",
                    "--pre-migration-snapshot-ref",
                    "snapshot://postgres/pre-migration/test",
                    "--post-migration-validation-ref",
                    "validation://postgres/post-migration/test",
                    "--destructive-changes-reviewed",
                    "--measured-apply-seconds",
                    "12.5",
                    "--measured-rollback-seconds",
                    "18.25",
                    "--rehearsal-id",
                    "migration_rehearsal_cli_test",
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            packet = json.loads(completed.stdout)
            verification = verify_migration_rehearsal(
                output_path,
                expected_migration_version=packet["migration_version"],
                expected_migration_combined_sha256=packet["migration_combined_sha256"],
            )

        self.assertEqual(packet["schema_version"], "mesh.migration_rehearsal.v1")
        self.assertEqual(packet["migration_version"], "005_helix_projection_outbox")
        self.assertEqual(verification["status"], "pass")


def _proof() -> dict:
    return {
        "schema_version": "mesh.migration_rehearsal.v1",
        "rehearsal_id": "migration_rehearsal_20260505",
        "generated_at": "2026-05-05T23:30:00Z",
        "operator_id": "platform@example.com",
        "environment": "staging",
        "database_engine": "postgres",
        "migration_directory": "migrations/postgres",
        "migration_version": "004_incident_corpus",
        "migration_combined_sha256": "a" * 64,
        "applied_migration_count": 5,
        "rolled_back": True,
        "rollback_ref": "restore://postgres/migration-rehearsal/2026-05-05",
        "pre_migration_snapshot_ref": "snapshot://postgres/pre-migration/2026-05-05",
        "post_migration_validation_ref": "validation://postgres/post-migration/2026-05-05",
        "destructive_changes_reviewed": True,
        "measured_apply_seconds": 12.5,
        "measured_rollback_seconds": 18.25,
    }
