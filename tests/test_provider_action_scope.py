from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.provider_action_scope import (
    load_provider_action_scope_proof,
    verify_provider_action_scope_proof,
)


class ProviderActionScopeProofTests(unittest.TestCase):
    def test_verifier_passes_registry_allowed_fixture_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", _proof())

            result = verify_provider_action_scope_proof(proof_path)

            self.assertEqual(result["schema_version"], "mesh.provider_action_scope_verification.v1")
            self.assertEqual(result["status"], "pass")
            self.assertTrue(result["checks"]["all_actions_allowed"])
            self.assertEqual(
                {item["action_id"] for item in result["action_results"]},
                {"kubernetes-rollback", "otel-feedback", "audit-local"},
            )

    def test_require_live_rejects_fixture_and_missing_live_refs(self) -> None:
        proof = _proof()
        proof["evidence_level"] = "fixture"
        proof["action_scopes"][0]["live_proof_ref"] = None
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", proof)

            result = verify_provider_action_scope_proof(proof_path, require_live=True)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["live_evidence_required"])
            self.assertIn("live_proof_present", result["action_results"][0]["blockers"])

    def test_feature_flag_write_fails_closed_when_registry_has_no_write_scope(self) -> None:
        proof = _proof(
            action_scopes=[
                _action(
                    action_id="feature-flag-write",
                    connector_id="feature_flag_adapter",
                    requested_scope="write",
                    policy_tier="approval_required",
                    incident_class="feature_flag_regression",
                    approval_required=True,
                    approval_behavior_ref="approval://flag-provider/write",
                    rollback_ref="rollback://flag-provider/restore",
                )
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", proof)

            result = verify_provider_action_scope_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            action = result["action_results"][0]
            self.assertFalse(action["checks"]["scope_allowed_by_registry"])
            self.assertFalse(action["checks"]["connector_state_sufficient"])

    def test_external_audit_write_fails_until_registry_allows_append_scope(self) -> None:
        proof = _proof(
            action_scopes=[
                _action(
                    action_id="external-audit-write",
                    connector_id="audit_sink",
                    requested_scope="append-only-audit-write",
                    policy_tier="approval_required",
                    incident_class="postmortem_export",
                    approval_required=True,
                    approval_behavior_ref="approval://audit-sink/write",
                    rollback_ref="compensating-action://audit-sink/tombstone",
                    credential_rotation_ref="rotation://audit-sink/key",
                    break_glass_ref="break-glass://audit-sink/record",
                )
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", proof)

            result = verify_provider_action_scope_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["action_results"][0]["checks"]["scope_allowed_by_registry"])

    def test_approval_required_scope_requires_approval_behavior(self) -> None:
        proof = _proof(
            action_scopes=[
                _action(
                    action_id="kubernetes-approval-missing",
                    connector_id="kubernetes",
                    requested_scope="rollback",
                    policy_tier="approval_required",
                    incident_class="bad_deploy",
                    approval_required=True,
                    approval_behavior_ref=None,
                    rollback_ref="rollback://kubernetes/search",
                )
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", proof)

            result = verify_provider_action_scope_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["action_results"][0]["checks"]["approval_behavior_valid"])

    def test_secret_exposure_fails_scope(self) -> None:
        proof = _proof()
        proof["action_scopes"][0]["secret_material_exposed"] = True
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", proof)

            result = verify_provider_action_scope_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["action_results"][0]["checks"]["secret_material_absent"])

    def test_schema_error_is_reported(self) -> None:
        proof = _proof()
        proof.pop("action_scopes")
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", proof)

            self.assertIsNone(load_provider_action_scope_proof(None))
            result = verify_provider_action_scope_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["schema_valid"])
            self.assertIn("action_scopes", result["error"])

    def test_cli_verifies_provider_action_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "provider-action-scope-proof.json", _proof())

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_provider_action_scopes.py",
                    "--proof",
                    str(proof_path),
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


def _proof(*, action_scopes: list[dict] | None = None) -> dict:
    return {
        "schema_version": "mesh.provider_action_scope_proof.v1",
        "proof_id": "provider-action-scope-fixture",
        "generated_at": "2026-05-08T17:10:00Z",
        "environment": "pilot",
        "evidence_level": "fixture",
        "connector_registry_ref": "config/connector-certification.registry.json",
        "action_scopes": action_scopes
        if action_scopes is not None
        else [
            _action(
                action_id="kubernetes-rollback",
                connector_id="kubernetes",
                requested_scope="rollback",
                policy_tier="approval_required",
                incident_class="bad_deploy",
                approval_required=True,
                approval_behavior_ref="approval://kubernetes/rollback",
                rollback_ref="rollback://kubernetes/search",
                credential_rotation_ref="rotation://kubernetes/service-account",
                break_glass_ref="break-glass://kubernetes/record",
            ),
            _action(
                action_id="otel-feedback",
                connector_id="otel",
                requested_scope="feedback-proof",
                policy_tier="advisory_only",
                incident_class="telemetry_degradation",
                credential_rotation_ref="rotation://otel/reader-token",
            ),
            _action(
                action_id="audit-local",
                connector_id="audit_sink",
                requested_scope="local-audit",
                policy_tier="advisory_only",
                incident_class="postmortem_export",
                credential_rotation_ref="rotation://audit-sink/key",
                break_glass_ref="break-glass://audit-sink/record",
            ),
        ],
    }


def _action(
    *,
    action_id: str,
    connector_id: str,
    requested_scope: str,
    policy_tier: str,
    incident_class: str,
    approval_required: bool = False,
    approval_behavior_ref: str | None = None,
    rollback_ref: str | None = None,
    credential_rotation_ref: str | None = None,
    break_glass_ref: str | None = None,
) -> dict:
    return {
        "action_id": action_id,
        "incident_class": incident_class,
        "connector_id": connector_id,
        "requested_scope": requested_scope,
        "policy_tier": policy_tier,
        "approval_required": approval_required,
        "approval_behavior_ref": approval_behavior_ref,
        "evidence_refs": [f"evidence://{action_id}", "policy://provider-action-scope"],
        "rollback_ref": rollback_ref,
        "run_export_ref": f"artifact://runs/{action_id}/run-export-package.json",
        "degraded_behavior_ref": f"degraded://{connector_id}/{requested_scope}",
        "credential_rotation_ref": credential_rotation_ref,
        "break_glass_ref": break_glass_ref,
        "secret_material_exposed": False,
        "live_proof_ref": f"live-proof://{action_id}",
    }


if __name__ == "__main__":
    unittest.main()
