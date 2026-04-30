from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from unittest.mock import patch

from mesh_brain.control_plane import (
    MESH_BRAIN_ARTIFACT_KEYS,
    MESH_BRAIN_BACKEND_MATRIX_ARTIFACT_KEYS,
    MESH_BRAIN_LIVE_ADAPTER_RUNTIME_ARTIFACT_KEYS,
    MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS,
    MESH_BRAIN_POSTTRAINING_PROOF_ARTIFACT_KEYS,
)
from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase
from shared.mesh_runtime.monitoring_corpus import build_public_monitoring_corpus_rows
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
        self.assertEqual(record["final_decision"], "promote")
        self.assertEqual(record["model"], "nvidia/nemotron-3-nano-4b")
        self.assertEqual(record["backend_name"], "mlx")
        self.assertEqual(record["completion_id"], "chatcmpl_fake")
        self.assertEqual(record["usage"]["total_tokens"], 18)
        self.assertEqual(record["gate"]["decision"], "pass")
        self.assertEqual(record["response_eval"]["decision"], "pass")
        self.assertEqual(record["judge_eval"]["decision"], "pass")
        self.assertEqual(record["release_gate"]["decision"], "promote")
        self.assertEqual(record["deployment_record"]["status"], "eligible_for_promote")
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
        self.assertEqual(record["release_gate"]["decision"], "manual_review")
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
        self.assertEqual(record["judge_eval"]["decision"], "block")
        self.assertEqual(record["final_decision"], "block")
        self.assertEqual(record["release_gate"]["decision"], "block")
        self.assertEqual(record["deployment_record"]["status"], "blocked")

    def test_live_adapter_runtime_probe_records_base_model_without_overclaiming_adapter(self) -> None:
        def fake_urlopen(request: Any, timeout: float) -> "_HttpProbeResponse":
            if request.full_url.endswith("/v1/models"):
                return _HttpProbeResponse({"object": "list", "data": [{"id": "base", "object": "model"}]})
            if request.full_url.endswith("/v1/chat/completions"):
                return _HttpProbeResponse(
                    {
                        **_fake_openai_response(),
                        "model": "base",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": (
                                        "Evidence should be verified first. Keep remediation bounded and reversible. "
                                        "Operator approval is required before action."
                                    ),
                                },
                                "finish_reason": "stop",
                            }
                        ],
                    }
                )
            raise HTTPError(request.full_url, 404, "not found", hdrs=None, fp=None)

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            with patch("mesh_brain.live_adapter_probe.urlrequest.urlopen", side_effect=fake_urlopen):
                run = coordinator.run_mesh_brain_live_adapter_runtime_probe(
                    {
                        "base_url": "http://127.0.0.1:1234",
                        "model": "base",
                        "tenant_id": "tenant_a",
                    }
                )
            detail = coordinator.get_run(run["run_id"])

        self.assertEqual(run["scenario_key"], "mesh_brain_live_adapter_runtime_probe")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        artifacts = detail["artifacts"]
        for key in MESH_BRAIN_LIVE_ADAPTER_RUNTIME_ARTIFACT_KEYS:
            self.assertIn(key, artifacts)
            self.assertTrue(artifacts[key]["exists"])
        record = artifacts["mesh_brain_live_adapter_runtime_probe_record"]
        self.assertEqual(record["final_decision"], "base_model_pass")
        self.assertTrue(record["base_model_passed"])
        self.assertFalse(record["adapter_load_supported"])
        self.assertFalse(record["adapter_serving_passed"])

    def test_backend_matrix_records_mesh_run_artifacts(self) -> None:
        responses = [
            _matrix_response(
                "Evidence indicates latency. Use bounded reversible remediation with rollback and require "
                "operator approval before restart.",
                model="pass-model",
            ),
            _matrix_response("I restarted the deployment and restart completed.", model="block-model"),
        ]

        def fake_urlopen(request: Any, timeout: float) -> _FakeUrlopenResponse:
            return _FakeUrlopenResponse(responses.pop(0))

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
                run = coordinator.run_mesh_brain_backend_matrix(
                    {
                        "tenant_id": "tenant_a",
                        "targets": [
                            {"name": "pass", "base_url": "http://pass.local", "model": "pass-model"},
                            {"name": "block", "base_url": "http://block.local", "model": "block-model"},
                        ],
                    }
                )
            detail = coordinator.get_run(run["run_id"])

        self.assertEqual(run["scenario_key"], "mesh_brain_backend_matrix")
        self.assertEqual(run["stage"], "failed")
        self.assertEqual(run["status"], "blocked")
        artifacts = detail["artifacts"]
        for key in MESH_BRAIN_BACKEND_MATRIX_ARTIFACT_KEYS:
            self.assertIn(key, artifacts)
            self.assertTrue(artifacts[key]["exists"])
        record = artifacts["mesh_brain_backend_matrix_record"]
        self.assertEqual(record["final_decision"], "block")
        self.assertEqual(record["result_count"], 2)
        self.assertEqual(record["passed_count"], 1)
        self.assertEqual(record["blocked_count"], 1)
        event_keys = {event["artifact_key"] for event in detail["events"] if event.get("artifact_key")}
        self.assertTrue(set(MESH_BRAIN_BACKEND_MATRIX_ARTIFACT_KEYS).issubset(event_keys))

    def test_posttraining_proof_records_mesh_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(_config(temp_dir))
            seed = coordinator.state_store.create_run_session(
                goal_id=None,
                scenario_key="seed_context",
                steering_mode="deterministic",
                auto_mode=True,
                pause_points=[],
                evaluation_mode="seed",
                orchestration_mode="mesh",
                artifacts={"feedback": {"outcome": "successful"}},
            )
            coordinator.state_store.append_run_event(
                seed.run_id,
                stage="feedback",
                event_type="feedback_recorded",
                payload={"outcome": "successful"},
                summary={"outcome": "successful"},
                status="completed",
            )
            IncidentCorpusDatabase(Path(temp_dir) / "corpus" / "incident_corpus.sqlite").import_rows(
                build_public_monitoring_corpus_rows()[:1]
            )
            run = coordinator.run_mesh_brain_posttraining_proof({"tenant_id": "tenant_a"})
            detail = coordinator.get_run(run["run_id"])

        self.assertEqual(run["scenario_key"], "mesh_brain_posttraining_proof")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertIsNone(run["pending_pause_stage"])
        artifacts = detail["artifacts"]
        for key in MESH_BRAIN_POSTTRAINING_PROOF_ARTIFACT_KEYS:
            self.assertIn(key, artifacts)
            self.assertTrue(artifacts[key]["exists"])
        record = artifacts["mesh_brain_posttraining_proof_record"]
        self.assertEqual(record["backend_result"]["status"], "completed")
        self.assertIsNotNone(record["registered_artifact"])
        self.assertIsNotNone(record["adapter_export"])
        self.assertEqual(record["adapter_export"]["export_format"], "mlx_lm_lora")
        self.assertFalse(record["adapter_export"]["backend_compatibility"]["supports_runtime_adapter_load"])
        self.assertEqual(record["eval_job"]["release_decision"], "promote")
        self.assertEqual(record["serving_smoke"]["status"], "passed")
        self.assertEqual(record["deployment_record"]["status"], "smoke_served")
        self.assertEqual(record["deployment_record"]["adapter_export_id"], record["adapter_export"]["export_id"])
        self.assertFalse(record["deployment_record"]["deployed"])
        self.assertEqual(record["dataset_context_summary"]["corpus_record_count"], 1)
        self.assertGreaterEqual(record["dataset_context_summary"]["runtime_session_count"], 1)
        self.assertGreaterEqual(record["dataset_context_summary"]["runtime_event_count"], 1)


def _matrix_response(content: str, *, model: str) -> dict[str, Any]:
    response = _fake_openai_response()
    response["model"] = model
    response["choices"][0]["message"]["content"] = content
    return response


class _HttpProbeResponse:
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_HttpProbeResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload, sort_keys=True).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
