from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.verify_e2e_claim import verify_e2e_claim


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/verify_e2e_claim.py"
HEAD = "a" * 40


class VerifyE2EClaimTests(unittest.TestCase):
    def test_fails_closed_without_release_runtime_pilot_and_autonomy_artifacts(self) -> None:
        result = verify_e2e_claim(expected_head=HEAD)

        self.assertEqual(result["schema_version"], "mesh.e2e_claim_verification.v1")
        self.assertEqual(result["status"], "fail")
        self.assertIn("release_artifact_bundle_passed", result["missing"])
        self.assertIn("runtime_binding_passed", result["missing"])
        self.assertIn("pilot_clearance_passed", result["missing"])
        self.assertIn("production_autonomy_clearance_passed", result["missing"])
        self.assertEqual(
            result["artifacts"]["runtime_binding"]["missing"],
            ["release_provenance_path_missing"],
        )
        self.assertEqual(
            result["artifacts"]["pilot_clearance"]["missing"],
            ["pilot_base_url_missing"],
        )
        self.assertEqual(
            result["artifacts"]["production_autonomy_clearance"]["missing"],
            ["live_proof_dir_missing"],
        )

    def test_cli_reports_structured_failure_for_missing_inputs(self) -> None:
        completed = subprocess.run(
            [sys.executable, SCRIPT, "--expected-head", HEAD, "--json"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1, completed.stderr + completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["expected_head"], HEAD)
        self.assertIn("release_artifact_bundle_passed", payload["missing"])

    def test_runtime_binding_requires_health_or_image_evidence_even_with_release_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_path = Path(tmp) / "release-provenance.json"
            release_path.write_text("{}\n", encoding="utf-8")

            result = verify_e2e_claim(expected_head=HEAD, release_provenance=release_path)

            self.assertEqual(result["status"], "fail")
            self.assertIn("runtime_binding_passed", result["missing"])
            self.assertEqual(
                result["artifacts"]["runtime_binding"]["missing"],
                ["runtime_binding_evidence_missing"],
            )

    def test_passes_when_release_runtime_pilot_and_autonomy_checks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_proof = root / "live-proof-current"
            (live_proof / "proofs").mkdir(parents=True)

            with (
                patch("scripts.verify_e2e_claim.verify_release_artifact_bundle", return_value={"status": "pass"}),
                patch("scripts.verify_e2e_claim.verify_release_runtime_binding", return_value={"status": "pass"}),
                patch("scripts.verify_e2e_claim.verify_pilot_clearance", return_value={"status": "pass"}),
                patch("scripts.verify_e2e_claim.verify_production_autonomy_clearance", return_value={"status": "pass"}),
            ):
                result = verify_e2e_claim(
                    expected_head=HEAD,
                    artifact_root=root,
                    image_ref="orbital-mesh:test",
                    pilot_base_url="https://mesh.example",
                    live_proof_dir=live_proof,
                )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["missing"], [])
            self.assertTrue(all(result["checks"].values()))


if __name__ == "__main__":
    unittest.main()
