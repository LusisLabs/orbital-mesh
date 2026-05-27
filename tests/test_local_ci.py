from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.local_ci import run_local_ci


HEAD = "a" * 40


def args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "mode": "full",
        "output_root": "dist/local-ci-test",
        "image_tag": "",
        "json": True,
        "dry_run": True,
        "skip_scanners": False,
        "skip_migration": False,
        "skip_runtime_smoke": False,
        "syft_bin": "syft",
        "grype_bin": "grype",
        "policy_signing_key": "local-ci-policy-key",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class LocalCiTests(unittest.TestCase):
    def test_full_mode_manifest_is_local_only_and_plans_heavy_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("scripts.local_ci._git_head", return_value=HEAD),
                patch("scripts.local_ci._git_branch", return_value="feature/local-ci"),
            ):
                manifest = run_local_ci(args(output_root=tmp))

        self.assertEqual(manifest["schema_version"], "mesh.local_ci_manifest.v1")
        self.assertEqual(manifest["status"], "pass")
        self.assertTrue(manifest["local_only"])
        self.assertFalse(manifest["checks"]["github_actions_attestation"])
        self.assertFalse(manifest["checks"]["production_release_authority"])
        self.assertEqual([step["name"] for step in manifest["steps"]], ["heavy-root-gate", "git-diff-check"])
        self.assertEqual(manifest["steps"][0]["command"], ["corepack", "pnpm", "run", "lint"])

    def test_release_mode_records_local_release_steps_without_github_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("scripts.local_ci._git_head", return_value=HEAD),
                patch("scripts.local_ci._git_branch", return_value="feature/local-ci"),
                patch("scripts.local_ci.shutil.which", return_value="/usr/bin/tool"),
            ):
                manifest = run_local_ci(
                    args(
                        mode="release",
                        output_root=tmp,
                        skip_scanners=True,
                        skip_migration=True,
                        skip_runtime_smoke=True,
                    )
                )

        step_names = [step["name"] for step in manifest["steps"]]
        self.assertIn("docker-build", step_names)
        self.assertIn("release-image-metadata", step_names)
        self.assertIn("local-ci-attestation", step_names)
        self.assertIn("release-provenance-local-rehearsal", step_names)
        self.assertFalse(manifest["checks"]["github_actions_attestation"])
        self.assertIn("Local CI evidence", manifest["authority_boundary"])

    def test_manifest_written_path_is_under_head_scoped_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("scripts.local_ci._git_head", return_value=HEAD),
                patch("scripts.local_ci._git_branch", return_value="feature/local-ci"),
            ):
                manifest = run_local_ci(args(mode="fast", output_root=tmp))

            manifest_path = Path(manifest["manifest_path"])
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self.assertEqual(manifest_path.name, "manifest.json")
        self.assertEqual(manifest_path.parent.name, HEAD[:7])


if __name__ == "__main__":
    unittest.main()
