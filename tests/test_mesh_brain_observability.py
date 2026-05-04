from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    REQUIRED_OBSERVABILITY_LABELS,
    mesh_brain_observation_to_prometheus,
    run_private_crops_mvp_e2e,
)


class MeshBrainObservabilityTests(unittest.TestCase):
    def test_mvp_emits_mesh_brain_metrics_with_required_labels(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_private_crops_mvp_e2e(output_directory=temp_dir, tenant_id="tenant_a")
            observation_path = Path(temp_dir) / "observability" / "mesh_brain_observation.json"
            prometheus_path = Path(temp_dir) / "observability" / "mesh_brain_metrics.prom"
            observation = json.loads(observation_path.read_text(encoding="utf-8"))
            prometheus = prometheus_path.read_text(encoding="utf-8")

        self.assertTrue(set(REQUIRED_OBSERVABILITY_LABELS).issubset(observation["labels"]))
        self.assertEqual(observation["labels"]["engine"], "sgl-project/sglang")
        self.assertEqual(observation["labels"]["tenant"], "tenant_a")
        self.assertEqual(observation["labels"]["task_type"], "crops")
        self.assertEqual(observation["eval_outcome"], "promote")
        self.assertEqual(observation["policy_route"], "approval_required")
        self.assertGreater(observation["token_count"], 0)
        self.assertEqual(observation["cache_hit_rate"], 0.72)
        self.assertTrue(result.acceptance_report["observability_labels_complete"])
        self.assertIn("mesh_brain_requests_total", prometheus)
        self.assertIn('tenant="tenant_a"', prometheus)
        self.assertIn('policy_route="approval_required"', prometheus)
        self.assertIn("mesh_brain_cache_hit_rate", prometheus)

    def test_prometheus_export_includes_declared_metric_types_once(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_private_crops_mvp_e2e(output_directory=temp_dir)
            prometheus = mesh_brain_observation_to_prometheus(result.observability)

        self.assertEqual(prometheus.count("# TYPE mesh_brain_requests_total counter"), 1)
        self.assertEqual(prometheus.count("# TYPE mesh_brain_token_count gauge"), 1)
        self.assertEqual(prometheus.count("# TYPE mesh_brain_cache_hit_rate gauge"), 1)
        self.assertIn("mesh_brain_eval_outcome", prometheus)
        self.assertIn("mesh_brain_policy_route", prometheus)


if __name__ == "__main__":
    unittest.main()
