from __future__ import annotations

import copy
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from shared.mesh_runtime.hardened_arena_intent import (
    REQUIRED_INTENT_KINDS,
    generate_hardened_arena_intent,
    output_dir_is_generated,
    verify_hardened_arena_intent,
    write_hardened_arena_intent,
)
from shared.mesh_runtime.schema_validation import validate_payload


class HardenedArenaIntentTests(unittest.TestCase):
    def test_generated_intent_contains_review_only_outputs(self) -> None:
        bundle = generate_hardened_arena_intent("solo_project_default", generated_at="2026-05-22T00:00:00Z")

        self.assertEqual(bundle["profile_id"], "solo_project_default")
        self.assertTrue(bundle["review_only"])
        self.assertFalse(bundle["live_deployment_allowed"])
        self.assertFalse(bundle["secret_values_present"])
        self.assertFalse(bundle["kubeconfig_material_present"])
        kinds = {output["kind"] for output in bundle["outputs"]}
        self.assertTrue(REQUIRED_INTENT_KINDS.issubset(kinds))
        self.assertIn("compose_overlay_intent", kinds)
        self.assertGreater(len(bundle["rollback_cleanup_requirements"]), 0)
        for requirement in bundle["rollback_cleanup_requirements"]:
            self.assertGreater(len(requirement["rollback_intent"]), 0)
            self.assertGreater(len(requirement["cleanup_intent"]), 0)
        validate_payload("hardened-arena-intent.schema.json", bundle)

    def test_enterprise_profile_omits_compose_when_not_supported(self) -> None:
        bundle = generate_hardened_arena_intent("enterprise_onprem_rehearsal", generated_at="2026-05-22T00:00:00Z")
        kinds = {output["kind"] for output in bundle["outputs"]}

        self.assertNotIn("compose_overlay_intent", kinds)
        self.assertTrue(REQUIRED_INTENT_KINDS.issubset(kinds))

    def test_written_intent_bundle_verifies(self) -> None:
        bundle = generate_hardened_arena_intent("startup_saas_staging", generated_at="2026-05-22T00:00:00Z")
        directory = Path("dist/hardened-arena/test/intent")
        try:
            bundle_path = write_hardened_arena_intent(bundle, directory)
            result = verify_hardened_arena_intent(bundle_path)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["profile_id"], "startup_saas_staging")
        self.assertEqual(result["output_count"], len(bundle["outputs"]))

    def test_verifier_rejects_live_deployment_intent(self) -> None:
        bundle = generate_hardened_arena_intent("solo_project_default", generated_at="2026-05-22T00:00:00Z")
        broken = copy.deepcopy(bundle)
        broken["live_deployment_allowed"] = True
        directory = Path("dist/hardened-arena/test/live-intent")
        try:
            bundle_path = write_hardened_arena_intent(broken, directory)
            result = verify_hardened_arena_intent(bundle_path)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("intent_allows_live_deployment", result["blockers"])

    def test_verifier_rejects_forbidden_live_command_text(self) -> None:
        bundle = generate_hardened_arena_intent("solo_project_default", generated_at="2026-05-22T00:00:00Z")
        broken = copy.deepcopy(bundle)
        broken["outputs"][0]["content"]["forbidden"] = "kubectl apply -f live.yaml"
        directory = Path("dist/hardened-arena/test/forbidden-intent")
        try:
            bundle_path = write_hardened_arena_intent(broken, directory)
            result = verify_hardened_arena_intent(bundle_path)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("forbidden_live_or_secret_material:kubectl apply", result["blockers"])

    def test_cli_generates_and_verifies_intent_under_dist(self) -> None:
        output_dir = Path("dist/hardened-arena/solo_project_default/intent")
        shutil.rmtree(output_dir, ignore_errors=True)
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/generate_hardened_arena_intent.py",
                "--profile",
                "solo_project_default",
                "--output-dir",
                str(output_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        bundle_path = output_dir / "intent-bundle.json"
        verify_completed = subprocess.run(
            [sys.executable, "scripts/verify_hardened_arena_intent.py", "--intent", str(bundle_path), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        shutil.rmtree(output_dir, ignore_errors=True)

        self.assertEqual(verify_completed.returncode, 0, verify_completed.stdout + verify_completed.stderr)
        self.assertIn('"status": "pass"', verify_completed.stdout)

    def test_cli_rejects_output_outside_generated_dist(self) -> None:
        self.assertTrue(output_dir_is_generated("dist/hardened-arena/example/intent"))
        self.assertFalse(output_dir_is_generated("config/intent"))
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/generate_hardened_arena_intent.py",
                "--profile",
                "solo_project_default",
                "--output-dir",
                "config/intent",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("refusing to write generated intent outside ignored dist/ output", completed.stderr)


if __name__ == "__main__":
    unittest.main()
