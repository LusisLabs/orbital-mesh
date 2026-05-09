from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.incident_coverage import (
    REQUIRED_INCIDENT_CLASSES,
    load_incident_coverage_proof,
    verify_incident_coverage_proof,
)


class IncidentCoverageProofTests(unittest.TestCase):
    def test_fixture_coverage_passes_all_required_classes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "incident-coverage-proof.json", _proof())

            result = verify_incident_coverage_proof(proof_path)

            self.assertEqual(result["schema_version"], "mesh.incident_coverage_verification.v1")
            self.assertEqual(result["status"], "pass")
            self.assertEqual(set(result["covered_incident_classes"]), set(REQUIRED_INCIDENT_CLASSES))
            self.assertTrue(result["checks"]["fixture_and_live_separated"])

    def test_missing_required_class_fails(self) -> None:
        proof = _proof()
        proof["coverage"] = [
            entry for entry in proof["coverage"] if entry["incident_class"] != "config_drift"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "incident-coverage-proof.json", proof)

            result = verify_incident_coverage_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["all_required_classes_present"])

    def test_require_live_rejects_fixture_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "incident-coverage-proof.json", _proof())

            result = verify_incident_coverage_proof(proof_path, require_live=True)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["live_evidence_required"])

    def test_require_live_passes_live_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "incident-coverage-proof.json", _proof(evidence_level="live"))

            result = verify_incident_coverage_proof(proof_path, require_live=True)

            self.assertEqual(result["status"], "pass")
            self.assertTrue(result["checks"]["live_evidence_required"])

    def test_false_positive_controls_must_prove_no_action(self) -> None:
        proof = _proof()
        for entry in proof["coverage"]:
            if entry["incident_class"] == "false_positive_controls":
                entry["false_positive_run_count"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "incident-coverage-proof.json", proof)

            result = verify_incident_coverage_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["false_positive_controls_pass"])

    def test_schema_error_is_reported(self) -> None:
        proof = _proof()
        proof.pop("coverage")
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "incident-coverage-proof.json", proof)

            self.assertIsNone(load_incident_coverage_proof(None))
            result = verify_incident_coverage_proof(proof_path)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["schema_valid"])
            self.assertIn("coverage", result["error"])

    def test_cli_verifies_incident_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "incident-coverage-proof.json", _proof())

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_incident_coverage_proof.py",
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


def _proof(*, evidence_level: str = "fixture") -> dict:
    return {
        "schema_version": "mesh.incident_coverage_proof.v1",
        "proof_id": f"incident-coverage-{evidence_level}",
        "generated_at": "2026-05-08T17:30:00Z",
        "environment": "pilot",
        "coverage": [
            _entry("crash_loop", "approval_required", evidence_level=evidence_level),
            _entry("bad_deploy_image", "approval_required", evidence_level=evidence_level),
            _entry("readiness_degradation", "approval_required", evidence_level=evidence_level),
            _entry("config_drift", "no_action", evidence_level=evidence_level),
            _entry("feature_flag_regression", "approval_required", evidence_level=evidence_level),
            _entry("telemetry_degradation", "human_review", evidence_level=evidence_level),
            _entry("queue_resource_pressure", "blocked", evidence_level=evidence_level),
            _entry("external_provider_failure", "human_review", evidence_level=evidence_level),
            _entry("partial_outage", "approval_required", evidence_level=evidence_level),
            _entry(
                "false_positive_controls",
                "no_action",
                evidence_level=evidence_level,
                false_positive_control=True,
                false_positive_run_count=0,
            ),
        ],
    }


def _entry(
    incident_class: str,
    expected_behavior: str,
    *,
    evidence_level: str,
    false_positive_control: bool = False,
    false_positive_run_count: int = 0,
) -> dict:
    run_ids = [f"run_{incident_class}_001"] if evidence_level == "live" else []
    live_proof_ref = f"live-proof://incident-coverage/{incident_class}" if evidence_level == "live" else None
    return {
        "incident_class": incident_class,
        "evidence_level": evidence_level,
        "signal_refs": [f"fixture://signals/{incident_class}.json"],
        "decision_refs": [f"decision://{incident_class}"],
        "policy_refs": ["policy://autonomy", "config://failure-mode-library"],
        "test_refs": [f"tests://incident/{incident_class}"],
        "artifact_refs": [f"artifact://incident-coverage/{incident_class}.json"],
        "expected_behavior": expected_behavior,
        "false_positive_control": false_positive_control,
        "false_positive_run_count": false_positive_run_count,
        "run_ids": run_ids,
        "live_proof_ref": live_proof_ref,
    }


if __name__ == "__main__":
    unittest.main()
