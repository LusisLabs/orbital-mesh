from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.integrations import build_readiness
from shared.mesh_runtime.provider_adapter import provider_adapter_proof_ready, verify_provider_adapter_proof


class ProviderAdapterProofTests(unittest.TestCase):
    def test_feature_flag_provider_proof_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "feature-flag-provider-proof.json"
            proof_path.write_text(json.dumps(_proof("feature_flag_provider"), indent=2, sort_keys=True) + "\n")

            result = verify_provider_adapter_proof(proof_path, adapter_id="feature_flag_provider")
            ready = provider_adapter_proof_ready(proof_path, adapter_id="feature_flag_provider")

        self.assertEqual(result["schema_version"], "mesh.provider_adapter_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(ready)

    def test_incident_provider_proof_requires_incident_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof = _proof("incident_provider")
            proof["supported_actions"] = ["read_incident"]
            proof_path = Path(tmp) / "incident-provider-proof.json"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")

            result = verify_provider_adapter_proof(proof_path, adapter_id="incident_provider")

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["required_actions_present"])

    def test_pilot_readiness_allows_feature_flag_credentials_only_with_matching_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "feature-flag-provider-proof.json"
            proof_path.write_text(json.dumps(_proof("feature_flag_provider"), indent=2, sort_keys=True) + "\n")

            blocked = build_readiness(
                RuntimeConfig(
                    state_directory=tmp,
                    vault_path=str(Path(tmp) / "vault"),
                    readiness_profile="pilot",
                    feature_flag_credentials_available=True,
                    feature_flag_provider_proof_path=str(Path(tmp) / "missing-proof.json"),
                ),
                force=True,
            ).to_dict()
            ready_check = build_readiness(
                RuntimeConfig(
                    state_directory=tmp,
                    vault_path=str(Path(tmp) / "vault"),
                    readiness_profile="pilot",
                    feature_flag_credentials_available=True,
                    feature_flag_provider_proof_path=str(proof_path),
                ),
                force=True,
            ).to_dict()

        self.assertIn("unfinished_feature_flag_adapter_disabled", blocked["blockers"])
        self.assertTrue(ready_check["required_checks"]["unfinished_feature_flag_adapter_disabled"])

    def test_cli_verifies_provider_adapter_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "feature-flag-provider-proof.json"
            proof_path.write_text(json.dumps(_proof("feature_flag_provider"), indent=2, sort_keys=True) + "\n")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_provider_adapter_proof.py",
                    "--proof",
                    str(proof_path),
                    "--adapter-id",
                    "feature_flag_provider",
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass")


def _proof(adapter_id: str) -> dict:
    actions = (
        ["read_flag", "set_rollout", "rollback_flag"]
        if adapter_id == "feature_flag_provider"
        else ["read_incident", "create_incident", "update_incident"]
    )
    return {
        "schema_version": "mesh.provider_adapter_proof.v1",
        "proof_id": f"{adapter_id}_test",
        "adapter_id": adapter_id,
        "provider_name": "test-provider",
        "environment": "staging",
        "operator_id": "platform@example.com",
        "supported_actions": actions,
        "authority_boundary": "Mesh control plane approval gate owns all provider writes.",
        "service_account_ref": "secret-ref://mesh/provider/service-account",
        "credential_rotation_ref": "rotation://mesh/provider/2026-05-06",
        "break_glass_recording_ref": "break-glass://mesh/provider/2026-05-06",
        "audit_sink_ref": "audit://mesh/provider/append-only/receipt",
        "dry_run_ref": "dry-run://mesh/provider/action-preview",
        "rollback_ref": "rollback://mesh/provider/restore",
        "degraded_behavior": "fail closed with operator-visible blocker",
        "production_write_enabled": True,
        "proposal_lane_credentials_absent": True,
        "raw_secret_material_present": False,
    }


if __name__ == "__main__":
    unittest.main()
