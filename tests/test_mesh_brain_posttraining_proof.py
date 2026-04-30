from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.posttraining_proof import (
    LocalSubprocessTrainingBackend,
    run_posttraining_proof,
)


class MeshBrainPosttrainingProofTests(unittest.TestCase):
    def test_real_local_posttraining_proof_registers_evals_and_smoke_serves_artifact(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_posttraining_proof(output_directory=Path(temp_dir), tenant_id="tenant_a")
            backend = json.loads((Path(temp_dir) / "posttraining_backend_result.json").read_text(encoding="utf-8"))
            deployment = json.loads((Path(temp_dir) / "posttraining_deployment_record.json").read_text(encoding="utf-8"))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.backend_result["status"], "completed")
        self.assertIsNotNone(result.registered_artifact)
        self.assertIsNotNone(result.eval_job)
        self.assertIsNotNone(result.serving_smoke)
        self.assertEqual(result.eval_job["release_decision"], "promote")
        self.assertEqual(result.serving_smoke["status"], "passed")
        self.assertEqual(result.deployment_record["status"], "smoke_served")
        self.assertFalse(result.deployment_record["deployed"])
        self.assertEqual(result.deployment_record["release_decision"], "promote")
        self.assertEqual(backend["backend_name"], "local_subprocess_training_backend")
        self.assertEqual(deployment["status"], "smoke_served")
        self.assertIn("posttraining_backend_result", result.artifact_paths)
        self.assertIn("posttraining_eval_job", result.artifact_paths)
        self.assertIn("posttraining_serving_smoke", result.artifact_paths)

    def test_local_subprocess_posttraining_proof_blocks_failed_command(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_posttraining_proof(
                output_directory=Path(temp_dir),
                tenant_id="tenant_a",
                backend=LocalSubprocessTrainingBackend(),
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.backend_result["status"], "failed")
        self.assertEqual(result.backend_result["return_code"], 7)
        self.assertIsNone(result.registered_artifact)
        self.assertIsNone(result.eval_job)
        self.assertIsNone(result.serving_smoke)
        self.assertEqual(result.deployment_record["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
