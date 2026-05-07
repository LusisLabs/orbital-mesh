from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import load_schema, validate_payload
from shared.mesh_runtime.credential_rotation import verify_credential_rotation_proof


def _proof(**overrides):
    payload = {
        "schema_version": "mesh.credential_rotation_proof.v1",
        "generated_at": "2026-05-05T21:00:00Z",
        "connector_id": "audit_sink",
        "service_account_ref": "serviceaccount://mesh/audit-sink-writer",
        "credential_mode": "runtime-secret",
        "rotated_at": "2026-05-05T21:00:01Z",
        "previous_secret_ref": "secret://mesh/audit-sink-writer/2026-04",
        "new_secret_ref": "secret://mesh/audit-sink-writer/2026-05",
        "previous_secret_revoked": True,
        "rotation_ticket_ref": "ticket://platform/rotate-audit-sink-2026-05",
        "operator_id": "platform-security@example.com",
        "evidence_refs": ["audit-rotation://2026-05-05/audit-sink-writer"],
        "secret_material_absent": True,
        "break_glass_used": False,
        "break_glass_recorded": True,
    }
    payload.update(overrides)
    return payload


class CredentialRotationTests(unittest.TestCase):
    def test_credential_rotation_schema_is_loadable(self) -> None:
        schema = load_schema("credential-rotation-proof.schema.json")
        self.assertEqual(schema["title"], "CredentialRotationProof")

    def test_rotation_proof_passes_against_connector_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rotation-proof.json"
            payload = _proof()
            validate_payload("credential-rotation-proof.schema.json", payload)
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_credential_rotation_proof(
                proof_path=path,
                registry_path="config/connector-certification.registry.json",
                connector_id="audit_sink",
            )

        self.assertEqual(result["schema_version"], "mesh.credential_rotation_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_rotation_proof_blocks_secret_material_and_unrevoked_previous_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rotation-proof.json"
            path.write_text(
                json.dumps(
                    _proof(
                        previous_secret_revoked=False,
                        secret_material_absent=False,
                    )
                ),
                encoding="utf-8",
            )

            result = verify_credential_rotation_proof(
                proof_path=path,
                registry_path="config/connector-certification.registry.json",
                connector_id="audit_sink",
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["previous_secret_revoked"])
        self.assertFalse(result["checks"]["secret_material_absent"])

    def test_rotation_proof_blocks_service_account_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rotation-proof.json"
            path.write_text(
                json.dumps(_proof(service_account_ref="serviceaccount://mesh/wrong")),
                encoding="utf-8",
            )

            result = verify_credential_rotation_proof(
                proof_path=path,
                registry_path="config/connector-certification.registry.json",
                connector_id="audit_sink",
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["service_account_ref_matches"])


if __name__ == "__main__":
    unittest.main()
