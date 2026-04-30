from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mesh_brain.control_plane import MESH_BRAIN_ARTIFACT_KEYS, MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS
from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig
from tests.test_mesh_brain_model_client import _FakeUrlopenResponse, _fake_openai_response


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

    def test_live_serving_smoke_records_mesh_run_artifacts_and_completion(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: float) -> _FakeUrlopenResponse:
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            response = _fake_openai_response()
            response["model"] = "nvidia/nemotron-3-nano-4b"
            response["choices"][0]["message"]["content"] = (
                "Evidence suggests search latency. Use bounded, reversible remediation and require operator "
                "approval before any restart."
            )
            return _FakeUrlopenResponse(response)

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
                run = coordinator.run_mesh_brain_live_serving_smoke(
                    {
                        "base_url": "http://127.0.0.1:1234",
                        "model": "nvidia/nemotron-3-nano-4b",
                        "tenant_id": "tenant_a",
                        "hardware_tier": "apple_silicon",
                        "prompt": "Smoke test.",
                    }
                )
            detail = coordinator.get_run(run["run_id"])

        self.assertEqual(run["scenario_key"], "mesh_brain_live_serving_smoke")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(captured["url"], "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "nvidia/nemotron-3-nano-4b")
        artifacts = detail["artifacts"]
        for key in MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS:
            self.assertIn(key, artifacts)
            self.assertTrue(artifacts[key]["exists"])
        record = artifacts["mesh_brain_live_serving_record"]
        self.assertEqual(record["stage"], "completed")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["model"], "nvidia/nemotron-3-nano-4b")
        self.assertEqual(record["backend_name"], "mlx")
        self.assertEqual(record["completion_id"], "chatcmpl_fake")
        self.assertEqual(record["usage"]["total_tokens"], 18)
        self.assertEqual(record["gate"]["decision"], "pass")
        self.assertEqual(record["response_eval"]["decision"], "pass")
        self.assertEqual(record["final_decision"], "pass")
        self.assertIn("bounded", record["content_preview"])
        event_keys = {event["artifact_key"] for event in detail["events"] if event.get("artifact_key")}
        self.assertTrue(set(MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS).issubset(event_keys))

    def test_live_serving_smoke_gate_manual_review_updates_run_status(self) -> None:
        def fake_urlopen(request: Any, timeout: float) -> _FakeUrlopenResponse:
            return _FakeUrlopenResponse({**_fake_openai_response(), "model": "nvidia/nemotron-3-nano-4b"})

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
                run = coordinator.run_mesh_brain_live_serving_smoke(
                    {
                        "base_url": "http://127.0.0.1:1234",
                        "model": "nvidia/nemotron-3-nano-4b",
                        "tenant_id": "tenant_a",
                        "hardware_tier": "apple_silicon",
                        "max_total_tokens": 1,
                    }
                )
            detail = coordinator.get_run(run["run_id"])

        self.assertEqual(run["stage"], "awaiting_operator")
        self.assertEqual(run["status"], "manual_review")
        self.assertEqual(run["pending_pause_stage"], "evaluation_ready")
        record = detail["artifacts"]["mesh_brain_live_serving_record"]
        self.assertEqual(record["gate"]["decision"], "manual_review")
        self.assertIn("token_usage_ceiling_exceeded", record["gate"]["reasons"])

    def test_live_serving_response_eval_block_updates_run_status(self) -> None:
        def fake_urlopen(request: Any, timeout: float) -> _FakeUrlopenResponse:
            response = _fake_openai_response()
            response["model"] = "nvidia/nemotron-3-nano-4b"
            response["choices"][0]["message"]["content"] = "I restarted the deployment and restart completed."
            return _FakeUrlopenResponse(response)

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
                run = coordinator.run_mesh_brain_live_serving_smoke(
                    {
                        "base_url": "http://127.0.0.1:1234",
                        "model": "nvidia/nemotron-3-nano-4b",
                        "tenant_id": "tenant_a",
                        "hardware_tier": "apple_silicon",
                    }
                )
            detail = coordinator.get_run(run["run_id"])

        self.assertEqual(run["stage"], "failed")
        self.assertEqual(run["status"], "blocked")
        record = detail["artifacts"]["mesh_brain_live_serving_record"]
        self.assertEqual(record["gate"]["decision"], "pass")
        self.assertEqual(record["response_eval"]["decision"], "block")
        self.assertEqual(record["final_decision"], "block")
        self.assertIn("unsupported_tool_execution_claim", record["response_eval"]["reasons"])


if __name__ == "__main__":
    unittest.main()
