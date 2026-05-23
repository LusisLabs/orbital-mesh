from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.integrations import build_readiness
from shared.mesh_runtime.load_concurrency import (
    load_concurrency_rehearsal_ready,
    verify_load_concurrency_rehearsal,
)
from scripts.run_load_concurrency_rehearsal import RehearsalMeasurements, build_proof


class LoadConcurrencyRehearsalTests(unittest.TestCase):
    def test_load_concurrency_rehearsal_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "load-concurrency-rehearsal.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_load_concurrency_rehearsal(proof_path)

        self.assertEqual(result["schema_version"], "mesh.load_concurrency_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checks"]["tenant_quota_enforced"])
        self.assertTrue(result["checks"]["target_lock_conflicts_observed"])

    def test_load_concurrency_rehearsal_blocks_local_file_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof = _proof()
            proof["environment"] = "local"
            proof["state_backend"] = "file"
            proof_path = Path(tmp) / "load-concurrency-rehearsal.json"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_load_concurrency_rehearsal(proof_path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["production_like_environment"])
        self.assertFalse(result["checks"]["postgres_state_backend"])
        self.assertFalse(load_concurrency_rehearsal_ready(proof_path))

    def test_expansion_readiness_requires_load_concurrency_rehearsal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                RuntimeConfig(
                    state_directory=tmp,
                    vault_path=str(Path(tmp) / "vault"),
                    readiness_profile="expansion",
                    load_concurrency_rehearsal_path=str(Path(tmp) / "missing-load-concurrency.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("load_concurrency_rehearsal_verified", readiness["blockers"])

    def test_cli_verifies_load_concurrency_rehearsal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "load-concurrency-rehearsal.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_load_concurrency_rehearsal.py",
                    "--proof",
                    str(proof_path),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass")

    def test_rehearsal_runner_builds_verifiable_packet(self) -> None:
        proof = build_proof(
            RehearsalMeasurements(
                rehearsal_id="load_concurrency_runner_test",
                generated_at="2026-05-23T12:00:00Z",
                environment="pilot",
                operator_id="platform@example.com",
                run_count=24,
                concurrent_operators=3,
                worker_count=4,
                queue_size=8,
                max_queue_depth=8,
                rejected_runs=17,
                tenant_quota_enforced=True,
                target_lock_conflicts_observed=True,
                cancellation_exercised=True,
                stuck_run_recovery_exercised=True,
                backpressure_observed=True,
                p95_admission_latency_ms=95.2,
                p95_event_persistence_latency_ms=140.1,
                evidence_refs=[
                    "postgres://load-concurrency/load_concurrency_runner_test/runs",
                    "postgres://load-concurrency/load_concurrency_runner_test/events",
                ],
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "load-concurrency-rehearsal.json"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = verify_load_concurrency_rehearsal(proof_path)

        self.assertEqual(result["status"], "pass")

    def test_runner_cli_can_skip_without_database_url(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_load_concurrency_rehearsal.py",
                "--database-url",
                "",
                "--skip-if-missing",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "skipped")


def _proof() -> dict:
    return {
        "schema_version": "mesh.load_concurrency_rehearsal.v1",
        "rehearsal_id": "load_concurrency_test",
        "generated_at": "2026-05-06T12:00:00Z",
        "environment": "staging",
        "operator_id": "platform@example.com",
        "state_backend": "postgres",
        "run_count": 24,
        "concurrent_operators": 3,
        "worker_count": 4,
        "queue_size": 100,
        "max_queue_depth": 12,
        "rejected_runs": 2,
        "tenant_quota_enforced": True,
        "target_lock_conflicts_observed": True,
        "cancellation_exercised": True,
        "stuck_run_recovery_exercised": True,
        "backpressure_observed": True,
        "p95_admission_latency_ms": 120.5,
        "p95_event_persistence_latency_ms": 210.0,
        "evidence_refs": [
            "run-export://load-concurrency/staging/2026-05-06",
            "metrics://mesh/run-admission/p95",
        ],
        "raw_secret_material_present": False,
    }


if __name__ == "__main__":
    unittest.main()
