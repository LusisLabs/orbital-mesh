from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    MeshBrainProductionArtifactRef,
    build_production_artifact_ref,
    production_blob_uri,
    validate_durable_artifact_uri,
    verify_production_artifact_record,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_mesh_brain_artifact_registry.py"


class MeshBrainArtifactRegistryTests(unittest.TestCase):
    def test_builds_immutable_production_artifact_ref_with_durable_uri(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "kernel_summary.json"
            path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            ref = build_production_artifact_ref(
                {
                    "artifact_key": "mesh_brain_model_kernel_probe_summary",
                    "path": str(path),
                    "sha256": "a" * 64,
                    "content_type": "application/json",
                },
                uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
                run_id="run_1",
            )

        self.assertIsInstance(ref, MeshBrainProductionArtifactRef)
        self.assertEqual(ref.artifact_key, "mesh_brain_model_kernel_probe_summary")
        self.assertTrue(ref.immutable)
        self.assertEqual(ref.sha256, "a" * 64)
        self.assertEqual(ref.byte_count, 18)
        self.assertEqual(ref.provenance["run_id"], "run_1")
        self.assertTrue(ref.blob_uri.startswith("s3://mesh-prod-artifacts/mesh-brain/mesh_brain_model_kernel_probe_summary/"))

    def test_rejects_local_or_missing_artifact_storage_contracts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "durable object storage"):
                build_production_artifact_ref(
                    {
                        "artifact_key": "mesh_brain_model_kernel_probe_summary",
                        "path": str(path),
                        "sha256": "b" * 64,
                    },
                    uri_prefix=str(Path(temp_dir)),
                    run_id="run_1",
                )
            with self.assertRaisesRegex(ValueError, "requires sha256"):
                build_production_artifact_ref(
                    {
                        "artifact_key": "mesh_brain_model_kernel_probe_summary",
                        "path": str(path),
                    },
                    uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
                    run_id="run_1",
                )

    def test_verifier_requires_durable_uri_hash_and_immutable_metadata(self) -> None:
        production_record = {
            "artifact_key": "mesh_brain_model_kernel_probe_summary",
            "uri": "s3://mesh-prod-artifacts/mesh-brain/key/hash/artifact.json",
            "content_hash": "c" * 64,
            "metadata": {
                "production_artifact": {
                    "blob_uri": "s3://mesh-prod-artifacts/mesh-brain/key/hash/artifact.json",
                    "sha256": "c" * 64,
                    "immutable": True,
                }
            },
        }
        local_record = {
            "artifact_key": "mesh_brain_model_kernel_probe_summary",
            "uri": "/tmp/artifact.json",
            "content_hash": "c" * 64,
            "metadata": {},
        }

        self.assertEqual(verify_production_artifact_record(production_record)["status"], "pass")
        self.assertEqual(verify_production_artifact_record(local_record)["status"], "fail")

    def test_uri_helper_validates_supported_object_storage_schemes(self) -> None:
        uri = production_blob_uri(
            uri_prefix="r2://mesh-prod-artifacts/runtime",
            artifact_key="mesh_brain_eval_report",
            sha256="d" * 64,
            source_path=Path("eval_report.json"),
        )

        validate_durable_artifact_uri(uri)
        self.assertIn("/mesh_brain_eval_report/", uri)
        with self.assertRaisesRegex(ValueError, "durable object storage"):
            validate_durable_artifact_uri("file:///tmp/eval_report.json")

    def test_cli_requires_upload_proof_when_gate_is_enabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = Path(temp_dir) / "artifacts.json"
            proof = Path(temp_dir) / "upload-proof.json"
            uri = "s3://mesh-prod-artifacts/mesh-brain/key/hash/artifact.json"
            artifacts.write_text(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "run_id": "run_1",
                                "artifact_key": "mesh_brain_model_kernel_probe_summary",
                                "uri": uri,
                                "path": "/tmp/artifact.json",
                                "content_hash": "e" * 64,
                                "metadata": {
                                    "production_artifact": {
                                        "blob_uri": uri,
                                        "sha256": "e" * 64,
                                        "byte_count": 42,
                                        "immutable": True,
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            missing = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_SCRIPT),
                    "--artifacts-json",
                    str(artifacts),
                    "--require-upload-proof",
                    "--json",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(missing.returncode, 0)
            missing_payload = json.loads(missing.stdout)
            self.assertEqual(missing_payload["status"], "fail")
            self.assertFalse(missing_payload["checks"]["upload_proofs_present"])

            proof.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.artifact_upload_proof.v1",
                        "uploads": [
                            {
                                "blob_uri": uri,
                                "sha256": "e" * 64,
                                "byte_count": 42,
                                "provider": "s3",
                                "uploaded_at": "2026-05-05T00:00:00+00:00",
                                "etag": "etag-test",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            passed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_SCRIPT),
                    "--artifacts-json",
                    str(artifacts),
                    "--proof-manifest",
                    str(proof),
                    "--require-upload-proof",
                    "--json",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(passed.returncode, 0, passed.stderr + passed.stdout)
            passed_payload = json.loads(passed.stdout)
            self.assertEqual(passed_payload["status"], "pass")
            self.assertTrue(passed_payload["checks"]["upload_proofs_present"])


if __name__ == "__main__":
    unittest.main()
