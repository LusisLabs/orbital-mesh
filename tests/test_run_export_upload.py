from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig, load_schema, validate_payload
from shared.mesh_runtime.run_export_upload import verify_run_export_upload_proof


def _config(tmp: str, **overrides) -> RuntimeConfig:
    values = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
        "vault_mirror_mode": "sync",
        "run_export_retention_reviewed": True,
    }
    values.update(overrides)
    return RuntimeConfig(**values)


class RunExportUploadTests(unittest.TestCase):
    def test_run_export_upload_schema_is_loadable(self) -> None:
        schema = load_schema("run-export-upload-proof.schema.json")
        self.assertEqual(schema["title"], "RunExportUploadProof")

    def test_run_export_upload_proof_passes_for_durable_package_and_archive_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package, archive = _export_run(tmp)
            proof_path = Path(tmp) / "run-export-upload-proof.json"
            proof = _proof(package=package, archive=archive)
            validate_payload("run-export-upload-proof.schema.json", proof)
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_run_export_upload_proof(
                package_path=package["path"],
                archive_path=archive["path"],
                proof_path=proof_path,
            )

        self.assertEqual(result["schema_version"], "mesh.run_export_upload_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_run_export_upload_proof_blocks_wrong_archive_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package, archive = _export_run(tmp)
            proof_path = Path(tmp) / "run-export-upload-proof.json"
            proof = _proof(package=package, archive=archive)
            for upload in proof["uploads"]:
                if upload["artifact_type"] == "archive":
                    upload["sha256"] = "0" * 64
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_run_export_upload_proof(
                package_path=package["path"],
                archive_path=archive["path"],
                proof_path=proof_path,
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["archive_sha256_matches"])

    def test_run_export_upload_proof_blocks_local_uri_and_missing_restore_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package, archive = _export_run(tmp)
            proof_path = Path(tmp) / "run-export-upload-proof.json"
            proof = _proof(package=package, archive=archive, restore_tested=False)
            proof["uploads"][0]["blob_uri"] = f"file://{tmp}/run.json"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_run_export_upload_proof(
                package_path=package["path"],
                archive_path=archive["path"],
                proof_path=proof_path,
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["package_uri_durable"])
        self.assertFalse(result["checks"]["restore_tested"])

    def test_run_export_upload_proof_blocks_mismatched_upload_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package, archive = _export_run(tmp)
            proof_path = Path(tmp) / "run-export-upload-proof.json"
            proof = _proof(package=package, archive=archive)
            proof["uploads"][0]["provider"] = "gs"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_run_export_upload_proof(
                package_path=package["path"],
                archive_path=archive["path"],
                proof_path=proof_path,
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["package_provider_matches"])
        self.assertTrue(result["checks"]["archive_provider_matches"])


def _export_run(tmp: str) -> tuple[dict, dict]:
    coordinator = RunCoordinator(_config(tmp))
    try:
        session = coordinator.state_store.create_run_session(
            goal_id=coordinator.state_store.ensure_default_goal().goal_id,
            scenario_key="search_latency_regression",
            steering_mode="approval_gate",
            auto_mode=False,
            pause_points=[],
            evaluation_mode="native",
            orchestration_mode="native",
            artifacts={
                "input_signal": {"service": "search"},
                "decision": {"decision_type": "reduce_rollout"},
                "evaluation": {"passed": True},
                "execution": {"status": "succeeded"},
                "feedback": {"outcome": "recovered"},
            },
        )
        coordinator.state_store.append_run_event(
            session.run_id,
            stage="completed",
            event_type="run_completed",
            payload={"status": "completed"},
            status="completed",
        )
        current = coordinator.state_store.get_run_session(session.run_id)
        assert current is not None
        current.stage = "completed"
        current.status = "completed"
        coordinator.state_store.save_run_session(current)
        package = coordinator.export_run_package(session.run_id)
        archive = coordinator.export_run_archive(session.run_id)
        assert package is not None
        assert archive is not None
        persisted_package = json.loads(Path(package["path"]).read_text(encoding="utf-8"))
        return persisted_package, archive
    finally:
        coordinator.stop_background_workers()


def _proof(*, package: dict, archive: dict, restore_tested: bool = True) -> dict:
    package_path = Path(package["path"])
    archive_path = Path(archive["path"])
    run_id = str(package["run_id"])
    return {
        "schema_version": "mesh.run_export_upload_proof.v1",
        "generated_at": "2026-05-05T22:30:00Z",
        "run_id": run_id,
        "export_id": str(package["export_id"]),
        "provider": "s3",
        "restore_tested": restore_tested,
        "restore_ref": f"restore://run-exports/{run_id}/2026-05-05",
        "uploads": [
            {
                "artifact_type": "package",
                "blob_uri": f"s3://mesh-run-exports/{run_id}.json",
                "sha256": _file_sha256(package_path),
                "byte_count": package_path.stat().st_size,
                "content_type": "application/json",
                "uploaded_at": "2026-05-05T22:30:01Z",
                "provider": "s3",
            },
            {
                "artifact_type": "archive",
                "blob_uri": f"s3://mesh-run-exports/{run_id}.zip",
                "sha256": _file_sha256(archive_path),
                "byte_count": archive_path.stat().st_size,
                "content_type": "application/zip",
                "uploaded_at": "2026-05-05T22:30:02Z",
                "provider": "s3",
            },
        ],
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
