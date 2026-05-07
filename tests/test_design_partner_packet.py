from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from shared.mesh_runtime import RuntimeConfig, load_schema, validate_payload
from shared.mesh_runtime.design_partner import design_partner_packet_ready, verify_design_partner_packet
from shared.mesh_runtime.integrations import build_readiness


def _packet(**overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": "mesh.design_partner_packet.v1",
        "packet_id": "design_partner_test",
        "generated_at": "2026-05-06T04:40:00Z",
        "partner": {
            "partner_id": "partner-a",
            "technical_owner": "platform@example.com",
            "escalation_channel": "pager://partner-a/platform",
            "pilot_window_days": 30,
        },
        "pilot_scope": {
            "environment": "pilot",
            "kubernetes_contexts": ["prod-us-east-1"],
            "namespaces": ["mesh-targets"],
            "service_classes": ["search-api"],
            "approval_gate_forced": True,
            "live_execution_limited": True,
            "feature_flag_adapter_disabled": True,
            "incident_adapter_disabled": True,
            "proposal_lanes_advisory_only": True,
            "evidence_ref": "design-partner://scope/partner-a",
        },
        "success_metrics": {
            "allowed_action_with_feedback": True,
            "denied_action_with_blocker": True,
            "no_proposal_lane_credentials": True,
            "operator_identity_on_mutations": True,
            "kill_switch_rehearsed": True,
            "merkle_proofs_available": True,
            "postgres_restart_proof_passed": True,
            "evidence_ref": "design-partner://success-metrics/partner-a",
        },
        "data_handling": {
            "retention_days": 30,
            "training_use_opt_in": False,
            "audit_records_excluded_from_training_by_default": True,
            "raw_secrets_disallowed": True,
            "kubeconfig_contents_disallowed": True,
            "private_keys_disallowed": True,
            "customer_payloads_excluded": True,
            "evidence_ref": "design-partner://data-handling/partner-a",
        },
        "support_model": {
            "mesh_support_hours": "business-hours",
            "partner_owner_ref": "user://platform@example.com",
            "emergency_owner": "operator",
            "postmortem_packet_required": True,
            "evidence_ref": "design-partner://support/partner-a",
        },
        "rollback_plan": {
            "plan_ref": "rollback://partner-a/pilot",
            "kill_switch_ref": "runbook://kill-switch",
            "rollback_metadata_required": True,
            "human_review_on_ambiguous_execution": True,
        },
        "consent": {
            "partner_approved": True,
            "mesh_approved": True,
            "real_user_experiment_consent_required": True,
            "real_user_experiment_consent_ref": "consent://partner-a/real-user-experiment",
            "data_handling_terms_ref": "terms://partner-a/data-handling",
            "signed_at": "2026-05-06T04:40:00Z",
        },
        "evidence_summary": {
            "go_no_go_status": "go",
            "go_no_go_packet_sha256": "a" * 64,
            "release_provenance_sha256": "b" * 64,
            "run_export_ref": "run-export://partner-a/run_1",
            "readiness_ref": "readiness://partner-a/pilot",
        },
        "raw_secret_material_present": False,
    }
    payload.update(overrides)
    return payload


def _runtime_config(tmp: str, packet_path: str | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        state_directory=tmp,
        vault_path=str(Path(tmp) / "vault"),
        integrations_config_path=str(Path(tmp) / "integrations.json"),
        promptfoo_command="/missing/promptfoo",
        hermes_command="/missing/hermes",
        goose_command="/missing/goose",
        evo_command="/missing/evo",
        readiness_profile="pilot",
        operator_identity_required=True,
        authenticated_ingress_proof_path=str(Path(tmp) / "authenticated-ingress-deployment-proof.json"),
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
        design_partner_packet_path=packet_path,
    )


class DesignPartnerPacketTests(unittest.TestCase):
    def test_design_partner_packet_schema_is_loadable(self) -> None:
        schema = load_schema("design-partner-packet.schema.json")
        self.assertEqual(schema["title"], "DesignPartnerPacket")

    def test_design_partner_packet_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design-partner-packet.json"
            packet = _packet()
            validate_payload("design-partner-packet.schema.json", packet)
            path.write_text(json.dumps(packet), encoding="utf-8")

            result = verify_design_partner_packet(path)

        self.assertEqual(result["schema_version"], "mesh.design_partner_packet_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_design_partner_packet_blocks_missing_real_user_consent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design-partner-packet.json"
            packet = _packet(
                consent={
                    "partner_approved": True,
                    "mesh_approved": True,
                    "real_user_experiment_consent_required": True,
                    "real_user_experiment_consent_ref": None,
                    "data_handling_terms_ref": "terms://partner-a/data-handling",
                    "signed_at": "2026-05-06T04:40:00Z",
                }
            )
            path.write_text(json.dumps(packet), encoding="utf-8")

            result = verify_design_partner_packet(path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["consent_documented"])
        self.assertFalse(design_partner_packet_ready(path))

    def test_readiness_accepts_design_partner_scope_before_final_go_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ingress_path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
            ingress_path.write_text(json.dumps(_authenticated_ingress_proof()), encoding="utf-8")
            packet_path = Path(tmp) / "design-partner-packet.json"
            packet_path.write_text(
                json.dumps(
                    _packet(
                        evidence_summary={
                            "go_no_go_status": "blocked",
                            "go_no_go_packet_sha256": "pending",
                            "release_provenance_sha256": "pending",
                            "run_export_ref": "run-export://partner-a/run_1",
                            "readiness_ref": "readiness://partner-a/pilot",
                        }
                    )
                ),
                encoding="utf-8",
            )

            full_packet = verify_design_partner_packet(packet_path)
            readiness_packet = verify_design_partner_packet(packet_path, require_go_evidence=False)
            readiness = build_readiness(_runtime_config(tmp, packet_path=str(packet_path)), force=True).to_dict()

        self.assertEqual(full_packet["status"], "fail")
        self.assertFalse(full_packet["checks"]["evidence_summary_go"])
        self.assertEqual(readiness_packet["status"], "pass")
        self.assertIn("evidence_summary_go", readiness_packet["advisory_checks"])
        self.assertTrue(readiness["required_checks"]["design_partner_packet_verified"])

    def test_pilot_readiness_requires_design_partner_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ingress_path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
            ingress_path.write_text(json.dumps(_authenticated_ingress_proof()), encoding="utf-8")
            packet_path = Path(tmp) / "design-partner-packet.json"
            packet_path.write_text(json.dumps(_packet()), encoding="utf-8")

            blocked = build_readiness(
                _runtime_config(tmp, packet_path=str(Path(tmp) / "missing-design-partner-packet.json")),
                force=True,
            ).to_dict()
            ready = build_readiness(_runtime_config(tmp, packet_path=str(packet_path)), force=True).to_dict()

        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("design_partner_packet_verified", blocked["blockers"])
        self.assertTrue(ready["required_checks"]["design_partner_packet_verified"])

    def test_cli_verifies_design_partner_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design-partner-packet.json"
            path.write_text(json.dumps(_packet()), encoding="utf-8")

            process = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_design_partner_packet.py",
                    "--packet",
                    str(path),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(process.stdout)
        self.assertEqual(result["schema_version"], "mesh.design_partner_packet_verification.v1")
        self.assertEqual(result["status"], "pass")


def _authenticated_ingress_proof() -> dict[str, Any]:
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


if __name__ == "__main__":
    unittest.main()
