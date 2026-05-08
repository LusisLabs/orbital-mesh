from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.watch_mode_proof import load_watch_mode_proof, verify_watch_mode_proof


class WatchModeProofTests(unittest.TestCase):
    def test_verifier_passes_complete_fixture_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "watch-mode-proof.json", _proof())

            result = verify_watch_mode_proof(proof_path, expected_environment="staging")

            self.assertEqual(result["schema_version"], "mesh.watch_mode_proof_verification.v1")
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["run_ids"], ["run_watch_001", "run_watch_002"])
            self.assertTrue(all(result["checks"].values()))

    def test_require_live_rejects_fixture_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "watch-mode-proof.json", _proof(evidence_level="fixture"))

            result = verify_watch_mode_proof(proof_path, require_live=True)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["live_evidence_required"])

    def test_verifier_fails_missing_duplicate_suppression_and_exports(self) -> None:
        proof = _proof()
        proof["duplicate_suppression"]["duplicate_ticks_suppressed"] = 0
        proof["audit_exports"]["all_runs_exported"] = False
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "watch-mode-proof.json", proof)

            result = verify_watch_mode_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["duplicate_ticks_suppressed"])
            self.assertFalse(result["checks"]["all_runs_exported"])

    def test_load_validates_schema(self) -> None:
        proof = _proof()
        proof.pop("kill_switch")
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "watch-mode-proof.json", proof)

            self.assertIsNone(load_watch_mode_proof(None))
            result = verify_watch_mode_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["schema_valid"])
            self.assertIn("kill_switch", result["error"])

    def test_cli_verifies_watch_mode_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "watch-mode-proof.json", _proof())

            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_watch_mode_proof.py",
                    "--proof",
                    str(proof_path),
                    "--expected-environment",
                    "staging",
                    "--json",
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
            )

            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "pass")


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _proof(*, evidence_level: str = "fixture") -> dict:
    return {
        "schema_version": "mesh.watch_mode_proof.v1",
        "proof_id": "watch-proof-20260508-fixture",
        "generated_at": "2026-05-08T16:45:00Z",
        "environment": "staging",
        "evidence_level": evidence_level,
        "watcher_name": "kubernetes-staging",
        "signal_source": "kubernetes",
        "started_at": "2026-05-08T16:40:00Z",
        "completed_at": "2026-05-08T16:44:00Z",
        "ticks": [
            {
                "tick_id": "tick-001",
                "observed_at": "2026-05-08T16:40:01Z",
                "target_ref": "kubernetes://staging/default/search",
                "outcome": "run_created",
                "run_id": "run_watch_001",
                "error_signature": "CrashLoopBackOff|Error",
                "provider": "kubernetes",
            },
            {
                "tick_id": "tick-002",
                "observed_at": "2026-05-08T16:41:01Z",
                "target_ref": "kubernetes://staging/default/search",
                "outcome": "duplicate_suppressed",
                "run_id": None,
                "error_signature": "CrashLoopBackOff|Error",
                "provider": "kubernetes",
            },
            {
                "tick_id": "tick-003",
                "observed_at": "2026-05-08T16:42:01Z",
                "target_ref": "kubernetes://staging/default/cart",
                "outcome": "healthy_ignored",
                "run_id": None,
                "error_signature": None,
                "provider": "kubernetes",
            },
            {
                "tick_id": "tick-004",
                "observed_at": "2026-05-08T16:43:01Z",
                "target_ref": "kubernetes://staging/default/checkout",
                "outcome": "run_created",
                "run_id": "run_watch_002",
                "error_signature": "ImagePullBackOff",
                "provider": "kubernetes",
            },
            {
                "tick_id": "tick-005",
                "observed_at": "2026-05-08T16:43:30Z",
                "target_ref": "kubernetes://staging/default/payments",
                "outcome": "provider_failure_recovered",
                "run_id": None,
                "error_signature": None,
                "provider": "kubernetes",
            },
            {
                "tick_id": "tick-006",
                "observed_at": "2026-05-08T16:44:00Z",
                "target_ref": "kubernetes://staging/default/search",
                "outcome": "kill_switch_paused",
                "run_id": None,
                "error_signature": None,
                "provider": "kubernetes",
            },
        ],
        "runs": [
            {
                "run_id": "run_watch_001",
                "target_ref": "kubernetes://staging/default/search",
                "error_signature": "CrashLoopBackOff|Error",
                "decision_type": "restart_deployment",
                "evaluation_ref": "evaluation://eval_watch_001",
                "evidence_refs": ["evidence://watch/tick-001", "policy://autonomy/staging"],
                "approval_state": "approved",
                "approval_ref": "approval://watch-operator-001",
                "run_export_ref": "artifact://runs/run_watch_001/run-export-package.json",
                "postmortem_export_ref": "artifact://runs/run_watch_001/postmortem.md",
            },
            {
                "run_id": "run_watch_002",
                "target_ref": "kubernetes://staging/default/checkout",
                "error_signature": "ImagePullBackOff",
                "decision_type": "rollback_deployment",
                "evaluation_ref": "evaluation://eval_watch_002",
                "evidence_refs": ["evidence://watch/tick-004", "policy://autonomy/staging"],
                "approval_state": "blocked",
                "approval_ref": "approval-blocked://eval_watch_002",
                "run_export_ref": "artifact://runs/run_watch_002/run-export-package.json",
                "postmortem_export_ref": "artifact://runs/run_watch_002/postmortem.md",
            },
        ],
        "duplicate_suppression": {
            "duplicate_ticks_suppressed": 1,
            "repeated_run_count": 0,
        },
        "false_positive_controls": {
            "healthy_ticks_ignored": 1,
            "false_positive_run_count": 0,
        },
        "kill_switch": {
            "watchers_paused": True,
            "event_ref": "event://kill-switch/watchers-paused",
            "ticks_suppressed_after_pause": 1,
        },
        "provider_failure": {
            "provider": "kubernetes",
            "recovered": True,
            "operator_visible_ref": "event://watcher/provider-failure-recovered",
            "run_created_during_failure": False,
        },
        "audit_exports": {
            "all_runs_exported": True,
            "secret_redaction_verified": True,
            "third_party_replay_ref": "artifact://watch-mode/replay-report.json",
        },
    }


if __name__ == "__main__":
    unittest.main()
