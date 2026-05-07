from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.audit_sink_certification import (
    audit_sink_certification_ready,
    verify_audit_sink_certification,
)
from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.integrations import build_readiness


class AuditSinkCertificationTests(unittest.TestCase):
    def test_audit_sink_certification_passes_with_proof_and_certified_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proof_path = _write_json(tmp_path / "audit-sink-proof.json", _proof())
            registry_path = _write_json(tmp_path / "connector-certification.registry.json", _registry("production-ready"))
            certification_path = _write_json(
                tmp_path / "audit-sink-certification.json",
                _certification(proof_path),
            )

            result = verify_audit_sink_certification(
                certification_path,
                proof_path=proof_path,
                registry_path=registry_path,
            )
            ready = audit_sink_certification_ready(
                certification_path,
                proof_path=proof_path,
                registry_path=registry_path,
            )

        self.assertEqual(result["schema_version"], "mesh.audit_sink_certification_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(ready)

    def test_audit_sink_certification_fails_when_registry_still_caps_mock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proof_path = _write_json(tmp_path / "audit-sink-proof.json", _proof())
            registry_path = _write_json(tmp_path / "connector-certification.registry.json", _registry("mock"))
            certification_path = _write_json(
                tmp_path / "audit-sink-certification.json",
                _certification(proof_path),
            )

            result = verify_audit_sink_certification(
                certification_path,
                proof_path=proof_path,
                registry_path=registry_path,
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["registry_record_certified"])

    def test_expansion_readiness_requires_audit_sink_certification_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proof_path = _write_json(tmp_path / "audit-sink-proof.json", _proof())
            registry_path = _write_json(tmp_path / "connector-certification.registry.json", _registry("production-ready"))
            certification_path = _write_json(
                tmp_path / "audit-sink-certification.json",
                _certification(proof_path),
            )

            blocked = build_readiness(
                _expansion_config(
                    tmp,
                    registry_path=registry_path,
                    proof_path=proof_path,
                    certification_path=tmp_path / "missing-certification.json",
                ),
                force=True,
            ).to_dict()
            ready_check = build_readiness(
                _expansion_config(
                    tmp,
                    registry_path=registry_path,
                    proof_path=proof_path,
                    certification_path=certification_path,
                ),
                force=True,
            ).to_dict()

        self.assertIn("external_audit_sink_certification_verified", blocked["blockers"])
        self.assertTrue(ready_check["required_checks"]["external_audit_sink_certification_verified"])

    def test_cli_verifies_audit_sink_certification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proof_path = _write_json(tmp_path / "audit-sink-proof.json", _proof())
            registry_path = _write_json(tmp_path / "connector-certification.registry.json", _registry("production-ready"))
            certification_path = _write_json(
                tmp_path / "audit-sink-certification.json",
                _certification(proof_path),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_audit_sink_certification.py",
                    "--certification",
                    str(certification_path),
                    "--proof",
                    str(proof_path),
                    "--registry",
                    str(registry_path),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass")


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _proof() -> dict:
    return {
        "schema_version": "mesh.audit_sink_proof.v1",
        "generated_at": "2026-05-06T10:00:00Z",
        "connector_id": "audit_sink",
        "sink_id": "customer-audit-archive",
        "sink_state": "production-ready",
        "destination_uri": "s3://mesh-audit-archive/prod/run_123.json",
        "append_only": True,
        "run_export_sha256": "a" * 64,
        "merkle_root": "b" * 64,
        "latest_event_id": "evt_0001",
        "event_count": 3,
        "receipt": {
            "receipt_id": "receipt-123",
            "received_at": "2026-05-06T10:00:01Z",
            "sink_sequence": 10,
        },
        "credential_boundary": {
            "service_account_ref": "serviceaccount://mesh/audit-sink-writer",
            "credential_mode": "runtime-secret",
            "runtime_secret_mount_required": True,
            "production_actuator_credentials_allowed": False,
            "repo_write_credentials_allowed": False,
        },
        "retention_days": 365,
        "rotation_evidence_ref": "rotation://audit-sink/2026-05-06",
        "break_glass_recording_required": True,
        "break_glass_drill_recorded": True,
    }


def _certification(proof_path: Path) -> dict:
    return {
        "schema_version": "mesh.audit_sink_certification.v1",
        "generated_at": "2026-05-06T10:01:00Z",
        "certification_id": "audit-sink-cert-prod-001",
        "connector_id": "audit_sink",
        "sink_id": "customer-audit-archive",
        "sink_state": "production-ready",
        "environment": "production",
        "reviewed_by": "security@example.com",
        "approved_at": "2026-05-06T10:02:00Z",
        "registry_ref": "config/connector-certification.registry.json#audit_sink",
        "registry_state": "production-ready",
        "audit_sink_proof_ref": str(proof_path),
        "audit_sink_proof_sha256": _sha256(proof_path),
        "required_artifacts": {
            "append_only_receipt_ref": "receipt://audit-sink/receipt-123",
            "run_export_ref": "run-export://run_123",
            "merkle_proof_ref": "merkle://run_123/evt_0001",
            "rotation_evidence_ref": "rotation://audit-sink/2026-05-06",
            "break_glass_recording_ref": "break-glass://audit-sink/2026-05-06",
            "retention_policy_ref": "policy://retention/audit-sink/365d",
        },
        "authority_boundary": {
            "service_account_ref": "serviceaccount://mesh/audit-sink-writer",
            "credential_mode": "runtime-secret",
            "runtime_secret_mount_required": True,
            "production_actuator_credentials_allowed": False,
            "repo_write_credentials_allowed": False,
        },
        "degraded_behavior": "fail closed to local Merkle and run export audit path",
        "compliance_reliance_allowed": True,
        "raw_secret_material_present": False,
        "blockers": [],
    }


def _registry(state: str) -> dict:
    blockers = [] if state in {"pilot-ready", "production-ready"} else ["external_audit_sink_not_certified"]
    return {
        "schema_version": "connector.certification.registry.v1",
        "connectors": [
            {
                "connector_id": "audit_sink",
                "display_name": "External audit sink",
                "domain": "audit",
                "state": state,
                "required_before": "expansion",
                "authority_posture": "append-only external audit continuity",
                "credential_policy": "runtime secret mounted only into audit sink writer",
                "credential_boundary": {
                    "service_account_ref": "serviceaccount://mesh/audit-sink-writer",
                    "credential_mode": "runtime-secret",
                    "production_actuator_credentials_allowed": False,
                    "repo_write_credentials_allowed": False,
                    "runtime_secret_mount_required": True,
                    "rotation_evidence_ref": "rotation://audit-sink/2026-05-06",
                    "break_glass_recording_required": True,
                },
                "degraded_behavior": "fail closed to local Merkle and run export audit path",
                "allowed_scopes": ["append-only-audit-write"],
                "evidence_refs": ["proof://audit-sink/receipt-123"],
                "blockers": blockers,
            }
        ],
    }


def _expansion_config(
    state_directory: str,
    *,
    registry_path: Path,
    proof_path: Path,
    certification_path: Path,
) -> RuntimeConfig:
    return RuntimeConfig(
        state_directory=state_directory,
        vault_path=str(Path(state_directory) / "vault"),
        integrations_config_path=str(Path(state_directory) / "integrations.json"),
        connector_certification_registry_path=str(registry_path),
        audit_sink_proof_path=str(proof_path),
        audit_sink_certification_path=str(certification_path),
        promptfoo_command="/missing/promptfoo",
        hermes_command="/missing/hermes",
        goose_command="/missing/goose",
        evo_command="/missing/evo",
        readiness_profile="expansion",
        operator_identity_required=True,
        state_backend="postgres",
        database_url="postgresql://mesh:mesh@localhost:5432/mesh",
        force_approval_gate=True,
        live_feedback_required=True,
        feedback_prometheus_enabled=True,
        prometheus_url="http://prometheus.local",
        mesh_brain_artifact_uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
        mesh_brain_serving_base_url="http://mesh-brain-serving.private:8000",
        mesh_brain_serving_model="nvidia/nemotron-3-nano-4b",
        run_export_retention_reviewed=True,
        feature_flag_credentials_available=False,
        incident_credentials_available=False,
        policy_signing_key="test-policy-signing-key",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
