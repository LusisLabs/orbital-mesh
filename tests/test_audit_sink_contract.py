from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import RuntimeConfig, load_schema, validate_payload
from shared.mesh_runtime.audit_sink import audit_sink_proof_ready, verify_audit_sink_proof
from shared.mesh_runtime.integrations import build_readiness


def _proof(**overrides):
    payload = {
        "schema_version": "mesh.audit_sink_proof.v1",
        "generated_at": "2026-05-05T20:00:00Z",
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
            "received_at": "2026-05-05T20:00:01Z",
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
        "rotation_evidence_ref": "audit-rotation://2026-05-05/customer-audit-archive",
        "break_glass_recording_required": True,
        "break_glass_drill_recorded": True,
    }
    payload.update(overrides)
    return payload


class AuditSinkContractTests(unittest.TestCase):
    def test_audit_sink_proof_schema_is_loadable(self) -> None:
        schema = load_schema("audit-sink-proof.schema.json")
        self.assertEqual(schema["title"], "AuditSinkProof")

    def test_audit_sink_proof_validates_and_passes_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit-sink-proof.json"
            payload = _proof()
            validate_payload("audit-sink-proof.schema.json", payload)
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_audit_sink_proof(path)

        self.assertEqual(result["schema_version"], "mesh.audit_sink_contract_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_audit_sink_proof_blocks_non_durable_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit-sink-proof.json"
            path.write_text(json.dumps(_proof(destination_uri=f"file://{tmp}/audit.json")), encoding="utf-8")

            result = verify_audit_sink_proof(path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["destination_uri_durable"])
        self.assertFalse(audit_sink_proof_ready(path))

    def test_expansion_readiness_blocks_without_audit_sink_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                RuntimeConfig(
                    state_directory=tmp,
                    vault_path=str(Path(tmp) / "vault"),
                    integrations_config_path=str(Path(tmp) / "integrations.json"),
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
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("external_audit_sink_contract_verified", readiness["blockers"])
        self.assertIn("external_audit_sink_certified", readiness["blockers"])


if __name__ == "__main__":
    unittest.main()
