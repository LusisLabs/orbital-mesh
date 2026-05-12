from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import RuntimeConfig, load_schema, validate_payload
from shared.mesh_runtime.authenticated_ingress import (
    authenticated_ingress_deployment_ready,
    verify_authenticated_ingress_deployment_proof,
)
from shared.mesh_runtime.integrations import build_readiness


def _proof(**overrides) -> dict:
    payload = {
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
            "evidence_ref": "ingress-proof://tls/2026-05-06",
        },
        "identity_provider": {
            "type": "oidc",
            "sso_enforced": True,
            "identity_claim": "email",
            "roles_claim": "groups",
            "evidence_ref": "ingress-proof://oidc/2026-05-06",
        },
        "header_sanitization": {
            "client_mesh_operator_header_stripped": True,
            "client_mesh_roles_header_stripped": True,
            "proxy_operator_header_stamped": True,
            "proxy_roles_header_stamped": True,
            "evidence_ref": "ingress-proof://headers/2026-05-06",
        },
        "role_mapping": {
            "viewer": "group://mesh/viewers",
            "launcher": "group://mesh/launchers",
            "approver": "group://mesh/approvers",
            "admin": "group://mesh/admins",
            "evidence_ref": "ingress-proof://role-mapping/2026-05-06",
        },
        "network_boundary": {
            "raw_service_publicly_reachable": False,
            "upstream_private": True,
            "allowed_proxy_ref": "security-group://mesh-ingress-to-control-plane",
            "evidence_ref": "ingress-proof://network/2026-05-06",
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
            "evidence_ref": "ingress-proof://audit/2026-05-06",
        },
        "raw_secret_material_present": False,
    }
    payload.update(overrides)
    return payload


def _runtime_config(tmp: str, proof_path: str | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        state_directory=tmp,
        vault_path=str(Path(tmp) / "vault"),
        integrations_config_path=str(Path(tmp) / "integrations.json"),
        promptfoo_command="/missing/promptfoo",
        hermes_command="/missing/hermes",
        goose_command="/missing/goose",
        evo_command="/missing/evo",
        readiness_profile="staging",
        operator_identity_required=True,
        policy_signing_key="test-policy-signing-key",
        authenticated_ingress_proof_path=proof_path,
    )


class AuthenticatedIngressDeploymentTests(unittest.TestCase):
    def test_authenticated_ingress_deployment_schema_is_loadable(self) -> None:
        schema = load_schema("authenticated-ingress-deployment-proof.schema.json")
        self.assertEqual(schema["title"], "AuthenticatedIngressDeploymentProof")

    def test_authenticated_ingress_deployment_proof_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
            payload = _proof()
            validate_payload("authenticated-ingress-deployment-proof.schema.json", payload)
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_authenticated_ingress_deployment_proof(path, expected_environment="staging")

        self.assertEqual(result["schema_version"], "mesh.authenticated_ingress_deployment_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_missing_authenticated_ingress_deployment_proof_reports_required_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-authenticated-ingress-deployment-proof.json"

            result = verify_authenticated_ingress_deployment_proof(path, expected_environment="staging")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error"], "proof_missing")
        self.assertIn("proof_present", result["missing"])
        self.assertIn("schema_valid", result["missing"])
        self.assertIn("environment_matches_expected", result["missing"])
        self.assertFalse(result["checks"]["proof_present"])
        self.assertFalse(result["checks"]["schema_valid"])

    def test_authenticated_ingress_deployment_blocks_wrong_expected_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
            path.write_text(json.dumps(_proof()), encoding="utf-8")

            result = verify_authenticated_ingress_deployment_proof(path, expected_environment="pilot")

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["environment_matches_expected"])

    def test_public_raw_service_blocks_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
            payload = _proof(
                network_boundary={
                    "raw_service_publicly_reachable": True,
                    "upstream_private": True,
                    "allowed_proxy_ref": "security-group://mesh-ingress-to-control-plane",
                    "evidence_ref": "ingress-proof://network/2026-05-06",
                }
            )
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_authenticated_ingress_deployment_proof(path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["network_boundary_private"])
        self.assertFalse(authenticated_ingress_deployment_ready(path))

    def test_staging_readiness_requires_deployed_ingress_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
            proof_path.write_text(json.dumps(_proof()), encoding="utf-8")

            blocked = build_readiness(
                _runtime_config(tmp, proof_path=str(Path(tmp) / "missing-ingress-proof.json")),
                force=True,
            ).to_dict()
            ready = build_readiness(_runtime_config(tmp, proof_path=str(proof_path)), force=True).to_dict()
            wrong_environment_path = Path(tmp) / "wrong-environment-ingress-proof.json"
            wrong_environment_path.write_text(json.dumps(_proof(environment="pilot")), encoding="utf-8")
            wrong_environment = build_readiness(
                _runtime_config(tmp, proof_path=str(wrong_environment_path)),
                force=True,
            ).to_dict()

        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("authenticated_ingress_deployment_verified", blocked["blockers"])
        self.assertTrue(ready["required_checks"]["authenticated_ingress_deployment_verified"])
        self.assertEqual(wrong_environment["status"], "blocked")
        self.assertIn("authenticated_ingress_deployment_verified", wrong_environment["blockers"])

    def test_cli_verifies_deployment_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
            path.write_text(json.dumps(_proof()), encoding="utf-8")

            process = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_authenticated_ingress_deployment.py",
                    "--proof",
                    str(path),
                    "--expected-environment",
                    "staging",
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(process.stdout)
        self.assertEqual(result["schema_version"], "mesh.authenticated_ingress_deployment_verification.v1")
        self.assertEqual(result["status"], "pass")


if __name__ == "__main__":
    unittest.main()
