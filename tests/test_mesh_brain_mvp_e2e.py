from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import run_private_crops_mvp_e2e


class MeshBrainMVPE2ETests(unittest.TestCase):
    def test_private_crops_mvp_satisfies_acceptance_criteria(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_private_crops_mvp_e2e(output_directory=temp_dir, tenant_id="tenant_a")
            acceptance_path = Path(temp_dir) / "mvp_acceptance_report.json"
            workflow_path = Path(temp_dir) / "mvp_workflow.json"
            trace_path = Path(temp_dir) / "trace_dataset_row.json"
            acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))

            self.assertTrue(workflow_path.exists())
            self.assertTrue(trace_path.exists())
            self.assertTrue((Path(temp_dir) / "data" / "eval_cases.jsonl").exists())
            self.assertTrue((Path(temp_dir) / "training" / "deployment_manifest.json").exists())
            self.assertTrue((Path(temp_dir) / "eval" / "eval_job.json").exists())
            self.assertTrue((Path(temp_dir) / "serving" / "serving_plan.json").exists())
            self.assertTrue((Path(temp_dir) / "observability" / "mesh_brain_metrics.prom").exists())
            self.assertTrue((Path(temp_dir) / "catalog" / "model_catalog_snapshot.json").exists())

        self.assertTrue(acceptance["openai_compatible_endpoint_planned"])
        self.assertTrue(acceptance["mesh_os_worker_lane_exercised"])
        self.assertTrue(acceptance["tool_calls_schema_valid_and_policy_gated"])
        self.assertGreaterEqual(acceptance["golden_eval_case_count"], 50)
        self.assertTrue(acceptance["candidate_eval_passed"])
        self.assertTrue(acceptance["runtime_trace_exported_to_dataset_row"])
        self.assertTrue(acceptance["rollback_restored_prior_adapter"])
        self.assertTrue(acceptance["observability_labels_complete"])
        self.assertEqual(acceptance["rollback_alias_state"], "production")
        self.assertEqual(result.training_job.request.method, "qlora")
        self.assertEqual(result.eval_job.release_decision, "promote")
        self.assertEqual(result.canary_alias.state, "canary")
        self.assertEqual(result.serving_plan.backend_name, "sgl-project/sglang")
        self.assertTrue(result.serving_plan.openai_compatible)
        self.assertEqual(result.agent_result.status, "approval_required")
        self.assertEqual(result.trace_dataset_row.row_type, "rl_trajectory")
        self.assertEqual(result.rollback_alias.state, "production")


if __name__ == "__main__":
    unittest.main()
