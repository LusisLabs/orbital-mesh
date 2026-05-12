from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import load_schema, validate_payload
from shared.mesh_runtime.on_call_drill import verify_on_call_drill


class OnCallDrillTests(unittest.TestCase):
    def test_on_call_drill_schema_is_loadable(self) -> None:
        schema = load_schema("on-call-drill.schema.json")
        self.assertEqual(schema["title"], "OnCallDrill")

    def test_on_call_drill_passes_when_every_required_action_is_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "on-call-drill.json"
            proof = _proof()
            validate_payload("on-call-drill.schema.json", proof)
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_on_call_drill(proof_path)

        self.assertEqual(result["schema_version"], "mesh.on_call_drill_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_missing_on_call_drill_reports_required_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "missing-on-call-drill.json"

            result = verify_on_call_drill(proof_path, expected_environment="pilot")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error"], "proof_missing")
        self.assertIn("proof_present", result["missing"])
        self.assertIn("schema_valid", result["missing"])
        self.assertIn("environment_matches_expected", result["missing"])
        self.assertFalse(result["checks"]["proof_present"])
        self.assertFalse(result["checks"]["schema_valid"])

    def test_on_call_drill_blocks_slow_recovery_missing_rotation_and_unpaused_watchers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "on-call-drill.json"
            proof = _proof()
            proof["measured_recovery_seconds"] = 901
            proof["kill_switch"]["watchers_paused"] = False
            proof["provider_key_rotation"]["status"] = "fail"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_on_call_drill(proof_path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["recovery_within_target"])
        self.assertFalse(result["checks"]["kill_switch_paused_watchers"])
        self.assertFalse(result["checks"]["provider_key_rotation_verified"])

    def test_on_call_drill_blocks_wrong_expected_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "on-call-drill.json"
            proof = _proof()
            proof["environment"] = "staging"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_on_call_drill(proof_path, expected_environment="pilot")

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["environment_matches_expected"])
        self.assertTrue(result["checks"]["environment_present"])

    def test_verify_on_call_drill_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "on-call-drill.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_on_call_drill.py",
                    "--proof",
                    str(proof_path),
                    "--expected-environment",
                    "pilot",
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["schema_version"], "mesh.on_call_drill_verification.v1")


def _proof() -> dict:
    return {
        "schema_version": "mesh.on_call_drill.v1",
        "drill_id": "on_call_drill_20260505",
        "generated_at": "2026-05-05T23:45:00Z",
        "operator_id": "platform@example.com",
        "environment": "pilot",
        "recovery_target_seconds": 900,
        "measured_recovery_seconds": 420,
        "kill_switch": {
            "live_execution_disabled": True,
            "watchers_paused": True,
            "approval_gate_forced": True,
            "event_ref": "event://kill-switch/2026-05-05",
        },
        "bad_target_revocation": {
            "target_ref": "kubernetes://cluster-a/default/bad-target",
            "revoked": True,
            "denied_action_ref": "run://denied-action/2026-05-05",
        },
        "stuck_run_recovery": {
            "run_id": "run_stuck_20260505",
            "recovered": True,
            "event_ref": "event://run-recovered/2026-05-05",
        },
        "failed_dependency": {
            "dependency": "prometheus",
            "degraded_state_visible": True,
            "operator_action_ref": "runbook://failed-dependency/2026-05-05",
        },
        "provider_key_rotation": {
            "verification_ref": "credential-rotation://provider/2026-05-05",
            "status": "pass",
            "break_glass_recorded": True,
        },
        "state_restore": {
            "verification_ref": "backup-restore://pilot/2026-05-05",
            "status": "pass",
            "restore_ref": "restore://pilot/2026-05-05",
        },
    }
