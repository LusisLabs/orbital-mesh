from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.run_mvp_e2e import persisted_artifact_paths, run_persisted_mvp_e2e


class MeshBrainRunMVPE2ETests(unittest.TestCase):
    def test_persisted_mvp_e2e_writes_inspectable_artifact_tree(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / ".mesh-runtime-state" / "mesh-brain" / "mvp-e2e"
            result = run_persisted_mvp_e2e(output_directory=output_dir, tenant_id="tenant_a")
            paths = persisted_artifact_paths(output_dir)
            summary = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))

            self.assertTrue((output_dir / "run_summary.json").exists())
            for path in paths.values():
                self.assertTrue(Path(path).exists(), path)

        self.assertEqual(summary["workflow_id"], result.workflow_id)
        self.assertEqual(summary["tenant_id"], "tenant_a")
        self.assertEqual(summary["release_decision"], "promote")
        self.assertEqual(summary["canary_state"], "canary")
        self.assertEqual(summary["rollback_state"], "production")
        self.assertGreaterEqual(summary["golden_eval_case_count"], 50)
        self.assertEqual(summary["serving_backend"], "sgl-project/sglang")
        self.assertEqual(summary["policy_route"], "approval_required")

    def test_module_cli_writes_persisted_artifacts_and_json_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / ".mesh-runtime-state" / "mesh-brain" / "mvp-e2e"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "mesh_brain.run_mvp_e2e",
                    "--output",
                    str(output_dir),
                    "--tenant-id",
                    "tenant_a",
                    "--json",
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
            )
            stdout = json.loads(completed.stdout)

            self.assertTrue((output_dir / "run_summary.json").exists())
            self.assertTrue((output_dir / "mvp_workflow.json").exists())
            self.assertTrue((output_dir / "observability" / "mesh_brain_metrics.prom").exists())

        self.assertEqual(stdout["output_directory"], str(output_dir))
        self.assertEqual(stdout["release_decision"], "promote")
        self.assertTrue(stdout["rollback_restored_prior_adapter"])


if __name__ == "__main__":
    unittest.main()
