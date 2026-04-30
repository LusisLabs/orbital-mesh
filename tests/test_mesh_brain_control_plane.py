from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mesh_brain.control_plane import MESH_BRAIN_ARTIFACT_KEYS
from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig


def _config(state_dir: str) -> RuntimeConfig:
    return RuntimeConfig(
        state_directory=state_dir,
        vault_path=str(Path(state_dir) / "vault"),
        integrations_config_path=str(Path(state_dir) / "integrations.json"),
        promptfoo_command="/missing/promptfoo",
        hermes_command="/missing/hermes",
        goose_command="/missing/goose",
        evo_command="/missing/evo",
        server_host="127.0.0.1",
        server_port=0,
    )


class MeshBrainControlPlaneTests(unittest.TestCase):
    def test_mesh_brain_mvp_records_mesh_run_artifacts_and_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            run = coordinator.run_mesh_brain_mvp({"tenant_id": "tenant_a"})
            detail = coordinator.get_run(run["run_id"])

            self.assertEqual(run["stage"], "completed")
            self.assertEqual(run["status"], "completed")
            self.assertIsNotNone(detail)
            artifacts = detail["artifacts"]
            for key in MESH_BRAIN_ARTIFACT_KEYS:
                self.assertIn(key, artifacts)
                self.assertTrue(artifacts[key]["exists"])
                self.assertEqual(artifacts[key]["artifact_key"], key)
            record = artifacts["mesh_brain_run_record"]
            self.assertEqual(record["tenant_id"], "tenant_a")
            self.assertEqual(record["final_release_decision"], "promote")
            self.assertGreaterEqual(record["summary_metrics"]["golden_eval_case_count"], 50)
            self.assertTrue(record["audit_events"])
            self.assertTrue(record["policy_events"])
            event_keys = {event["artifact_key"] for event in detail["events"] if event.get("artifact_key")}
            self.assertTrue(set(MESH_BRAIN_ARTIFACT_KEYS).issubset(event_keys))

    def test_mesh_brain_metrics_are_exposed_from_control_plane_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            coordinator.run_mesh_brain_mvp({"tenant_id": "tenant_a"})

            metrics = coordinator.agent_slo_prometheus()

        self.assertIn("mesh_brain_requests_total", metrics)
        self.assertIn('tenant="tenant_a"', metrics)
        self.assertIn('policy_route="approval_required"', metrics)

    def test_forced_failed_eval_blocks_deployment_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            run = coordinator.run_mesh_brain_mvp({"tenant_id": "tenant_a", "force_eval_block": True})
            detail = coordinator.get_run(run["run_id"])

        self.assertEqual(run["stage"], "failed")
        self.assertEqual(run["status"], "blocked")
        deployment = detail["artifacts"]["mesh_brain_deployment_record"]
        self.assertEqual(deployment["status"], "blocked")
        self.assertFalse(deployment["deployed"])
        self.assertEqual(deployment["release_decision"], "block")
        self.assertIsNone(deployment["serving_backend"])


if __name__ == "__main__":
    unittest.main()
