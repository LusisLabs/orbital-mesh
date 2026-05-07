from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import RuntimeConfig, load_schema, validate_payload
from shared.mesh_runtime.backup_restore import verify_backup_restore_rehearsal
from shared.mesh_runtime.integrations import build_readiness


class BackupRestoreRehearsalTests(unittest.TestCase):
    def test_backup_restore_rehearsal_schema_is_loadable(self) -> None:
        schema = load_schema("backup-restore-rehearsal.schema.json")
        self.assertEqual(schema["title"], "BackupRestoreRehearsal")

    def test_backup_restore_rehearsal_passes_when_required_components_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "backup-restore-rehearsal.json"
            proof = _proof()
            validate_payload("backup-restore-rehearsal.schema.json", proof)
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_backup_restore_rehearsal(proof_path)

        self.assertEqual(result["schema_version"], "mesh.backup_restore_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_backup_restore_rehearsal_blocks_missing_component_and_slow_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "backup-restore-rehearsal.json"
            proof = _proof()
            proof["measured_restore_seconds"] = 901
            proof["components"] = [
                component for component in proof["components"] if component["component"] != "research_artifacts"
            ]
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_backup_restore_rehearsal(proof_path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["restore_within_rto"])
        self.assertFalse(result["checks"]["required_components_present"])

    def test_staging_readiness_requires_backup_restore_rehearsal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocked = build_readiness(
                _config(tmp, backup_restore_rehearsal_path=str(Path(tmp) / "missing.json")),
                force=True,
            ).to_dict()
            proof_path = Path(tmp) / "backup-restore-rehearsal.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            ready = build_readiness(
                _config(tmp, backup_restore_rehearsal_path=str(proof_path)),
                force=True,
            ).to_dict()

        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("backup_restore_rehearsal_verified", blocked["blockers"])
        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["required_checks"]["backup_restore_rehearsal_verified"])

    def test_verify_backup_restore_rehearsal_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "backup-restore-rehearsal.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_backup_restore_rehearsal.py",
                    "--proof",
                    str(proof_path),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["schema_version"], "mesh.backup_restore_verification.v1")


def _config(tmp: str, **overrides) -> RuntimeConfig:
    authenticated_ingress_proof_path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
    if not authenticated_ingress_proof_path.exists():
        authenticated_ingress_proof_path.write_text(
            json.dumps(_authenticated_ingress_deployment_proof(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    values = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "readiness_profile": "staging",
        "operator_identity_required": True,
        "policy_signing_key": "test-policy-signing-key",
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
        "authenticated_ingress_proof_path": str(authenticated_ingress_proof_path),
    }
    values.update(overrides)
    return RuntimeConfig(**values)


def _proof() -> dict:
    digest = "a" * 64
    return {
        "schema_version": "mesh.backup_restore_rehearsal.v1",
        "rehearsal_id": "restore_rehearsal_20260505",
        "generated_at": "2026-05-05T23:00:00Z",
        "environment": "staging",
        "operator_id": "platform@example.com",
        "state_backend": "postgres",
        "backup_ref": "backup://orbital-mesh/staging/2026-05-05",
        "restore_ref": "restore://orbital-mesh/staging/2026-05-05",
        "rpo_seconds": 300,
        "rto_seconds": 900,
        "measured_restore_seconds": 420.5,
        "components": [
            {
                "component": component,
                "backup_uri": f"s3://mesh-backups/staging/{component}.json",
                "restored": True,
                "sha256_before": digest,
                "sha256_after": digest,
                "record_count": 1,
            }
            for component in (
                "state_store",
                "vault",
                "merkle_proofs",
                "integrations_config",
                "research_artifacts",
            )
        ],
    }


def _authenticated_ingress_deployment_proof() -> dict:
    return {
        "schema_version": "mesh.authenticated_ingress_deployment_proof.v1",
        "proof_id": "authenticated_ingress_deployment_test",
        "generated_at": "2026-05-06T04:10:00Z",
        "environment": "staging",
        "operator_id": "platform@example.com",
        "ingress_url": "https://mesh.staging.example.com",
        "tls": {
            "terminated": True,
            "public_listener": True,
            "minimum_version": "TLSv1.3",
            "certificate_ref": "acm://mesh-staging-cert",
            "evidence_ref": "ingress-proof://tls/test",
        },
        "identity_provider": {
            "type": "oidc",
            "sso_enforced": True,
            "identity_claim": "email",
            "roles_claim": "groups",
            "evidence_ref": "ingress-proof://oidc/test",
        },
        "header_sanitization": {
            "client_mesh_operator_header_stripped": True,
            "client_mesh_roles_header_stripped": True,
            "proxy_operator_header_stamped": True,
            "proxy_roles_header_stamped": True,
            "evidence_ref": "ingress-proof://headers/test",
        },
        "role_mapping": {
            "viewer": "group://mesh/viewers",
            "launcher": "group://mesh/launchers",
            "approver": "group://mesh/approvers",
            "admin": "group://mesh/admins",
            "evidence_ref": "ingress-proof://role-mapping/test",
        },
        "network_boundary": {
            "raw_service_publicly_reachable": False,
            "upstream_private": True,
            "allowed_proxy_ref": "security-group://mesh-ingress-to-control-plane",
            "evidence_ref": "ingress-proof://network/test",
        },
        "app_rehearsal": {
            "schema_version": "mesh.authenticated_ingress_rehearsal.v1",
            "status": "passed",
            "run_id": "run_ingress_rehearsal",
            "evidence_ref": "run-artifact://authenticated-ingress-rehearsal.json",
        },
        "audit": {
            "source_ip_or_proxy_identity_recorded": True,
            "operator_identity_recorded": True,
            "evidence_ref": "ingress-proof://audit/test",
        },
        "raw_secret_material_present": False,
    }
