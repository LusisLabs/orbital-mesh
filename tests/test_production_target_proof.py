from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import load_schema, validate_payload
from shared.mesh_runtime.production_target import (
    load_production_target_proof,
    verify_production_target_proof,
)


class ProductionTargetProofTests(unittest.TestCase):
    def test_schema_is_loadable(self) -> None:
        schema = load_schema("production-target-proof.schema.json")
        self.assertEqual(schema["title"], "ProductionTargetProof")

    def test_verifier_passes_complete_fixture_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _proof()
            validate_payload("production-target-proof.schema.json", payload)
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", payload)

            result = verify_production_target_proof(proof_path, expected_environment="pilot")

            self.assertEqual(result["schema_version"], "mesh.production_target_verification.v1")
            self.assertEqual(result["status"], "pass")
            self.assertTrue(all(result["checks"].values()))
            self.assertEqual(result["run_id"], "run_prod_target_fixture")

    def test_require_live_rejects_fixture_without_live_artifacts(self) -> None:
        proof = _proof(evidence_level="fixture", live_artifact_refs=[])
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", proof)

            result = verify_production_target_proof(proof_path, require_live=True)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["live_evidence_required"])
            self.assertFalse(result["checks"]["live_artifact_refs_present"])

    def test_missing_ingress_identity_or_tls_fails_closed(self) -> None:
        proof = _proof()
        proof["ingress"]["identity_enforced"] = False
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", proof)

            result = verify_production_target_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["ingress_authenticated"])

    def test_missing_approval_audit_fails_closed(self) -> None:
        proof = _proof()
        proof["approval"]["approval_audit_ref"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", proof)

            result = verify_production_target_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["approval_audited"])

    def test_secret_material_or_missing_rotation_fails_closed(self) -> None:
        proof = _proof()
        proof["secrets"]["raw_secret_material_present"] = True
        proof["secrets"]["credential_rotation_ref"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", proof)

            result = verify_production_target_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["secrets_protected"])
            self.assertFalse(result["checks"]["secret_redaction_verified"])

    def test_wrong_expected_environment_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", _proof())

            result = verify_production_target_proof(proof_path, expected_environment="production")

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["environment_matches_expected"])

    def test_schema_error_is_reported(self) -> None:
        proof = _proof()
        proof.pop("run")
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", proof)

            self.assertIsNone(load_production_target_proof(None))
            result = verify_production_target_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["schema_valid"])
            self.assertIn("run", result["error"])

    def test_cli_verifies_production_target_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "production-target-proof.json", _proof())

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_production_target_proof.py",
                    "--proof",
                    str(proof_path),
                    "--expected-environment",
                    "pilot",
                    "--json",
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "pass")


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _proof(**overrides) -> dict:
    payload = {
        "schema_version": "mesh.production_target_proof.v1",
        "proof_id": "production-target-fixture",
        "generated_at": "2026-05-08T18:10:00Z",
        "environment": "pilot",
        "evidence_level": "fixture",
        "target_ref": "k8s://pilot/search-api",
        "ingress": {
            "proof_ref": "artifact://authenticated-ingress-deployment-proof.json",
            "ingress_url": "https://mesh.pilot.example.com",
            "authenticated": True,
            "tls_terminated": True,
            "identity_enforced": True,
        },
        "identity": {
            "operator_id": "platform@example.com",
            "source_identity_ref": "identity://oidc/platform@example.com",
            "mutation_identity_recorded": True,
            "evidence_ref": "artifact://audit/operator-identity.json",
        },
        "telemetry": {
            "signal_source_ref": "otel://pilot/search-api",
            "metrics_ref": "prometheus://pilot/search-api/readiness",
            "feedback_source_ref": "artifact://runs/run_prod_target_fixture/feedback.json",
            "target_feedback_verified": True,
        },
        "secrets": {
            "runtime_secret_refs": ["secret://mesh/kubernetes-service-account", "secret://mesh/otel-reader"],
            "credential_rotation_ref": "rotation://mesh/pilot-target/2026-05-08",
            "raw_secret_material_present": False,
            "secret_redaction_verified": True,
        },
        "rollback": {
            "rollback_ref": "rollback://kubernetes/search-api/deployment",
            "rollback_rehearsed": True,
            "rollback_artifact_ref": "artifact://runs/run_prod_target_fixture/rollback.json",
        },
        "approval": {
            "approval_required": True,
            "approval_ref": "approval://run_prod_target_fixture/rollback",
            "approver_identity_ref": "identity://oidc/approver@example.com",
            "approval_audit_ref": "artifact://runs/run_prod_target_fixture/approval.json",
        },
        "run": {
            "run_id": "run_prod_target_fixture",
            "decision_ref": "artifact://runs/run_prod_target_fixture/decision.json",
            "evaluation_ref": "artifact://runs/run_prod_target_fixture/evaluation.json",
            "execution_ref": "artifact://runs/run_prod_target_fixture/execution.json",
            "feedback_ref": "artifact://runs/run_prod_target_fixture/feedback.json",
            "run_export_ref": "artifact://runs/run_prod_target_fixture/run-export-package.json",
            "postmortem_export_ref": "artifact://runs/run_prod_target_fixture/postmortem.md",
        },
        "governance": {
            "on_call_ref": "runbook://production-live#on-call",
            "escalation_ref": "runbook://production-live#escalation",
            "break_glass_ref": "break-glass://pilot-target/record",
            "incident_review_ref": "postmortem://run_prod_target_fixture/review",
            "retention_ref": "policy://audit-retention/pilot",
            "deletion_ref": "policy://audit-deletion/pilot",
        },
        "audit": {
            "timeline_ref": "timeline://run_prod_target_fixture",
            "merkle_ref": "merkle://run_prod_target_fixture",
            "policy_refs": ["policy://autonomy/approval-required", "policy://provider-action/kubernetes-rollback"],
            "evidence_refs": ["artifact://runs/run_prod_target_fixture/evidence.json"],
            "decision_reason_ref": "artifact://runs/run_prod_target_fixture/why.json",
            "change_record_ref": "artifact://runs/run_prod_target_fixture/change.json",
            "recovery_result_ref": "artifact://runs/run_prod_target_fixture/recovery.json",
            "secret_redaction_verified": True,
            "third_party_replay_ref": "replay://run_prod_target_fixture",
        },
        "live_artifact_refs": ["live-proof://placeholder-for-real-pilot-target"],
    }
    payload.update(overrides)
    return payload


if __name__ == "__main__":
    unittest.main()
