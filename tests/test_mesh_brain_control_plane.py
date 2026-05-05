from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from urllib.request import Request, urlopen

from mesh_brain import (
    MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS,
    MESH_BRAIN_MODEL_KERNEL_ARTIFACT_KEYS,
    build_live_serving_artifact_bundle,
    build_model_kernel_artifact_bundle,
    live_serving_smoke_to_run_record,
    model_kernel_probe_to_run_record,
    run_model_kernel_probe,
)
from control_plane_server import start_server_in_thread
from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig


class MeshBrainControlPlaneTests(unittest.TestCase):
    def test_model_kernel_probe_converts_to_artifact_bundle_and_run_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_model_kernel_probe(output_directory=Path(temp_dir), benchmark_iterations=20)
            bundle = build_model_kernel_artifact_bundle(result=result)
            run_record = model_kernel_probe_to_run_record(
                result=result,
                bundle=bundle,
                run_id="run_model_kernel_1",
            )

        self.assertEqual(set(bundle.artifacts), set(MESH_BRAIN_MODEL_KERNEL_ARTIFACT_KEYS))
        self.assertEqual(bundle.workflow_id, result.result_id)
        self.assertEqual(bundle.tenant_id, "mesh_system")
        self.assertEqual(bundle.release_decision, "pass")
        self.assertFalse(bundle.deployment_record["deployed"])
        self.assertEqual(bundle.deployment_record["deterministic_digest"], result.correctness.deterministic_digest)
        self.assertTrue(all(ref.exists for ref in bundle.artifacts.values()))
        self.assertTrue(all(ref.sha256 for ref in bundle.artifacts.values()))
        self.assertEqual(run_record["run_id"], "run_model_kernel_1")
        self.assertEqual(run_record["stage"], "completed")
        self.assertEqual(run_record["final_release_decision"], "pass")
        self.assertIn("max_gradient_relative_error", run_record["summary_metrics"])

    def test_coordinator_records_model_kernel_probe_as_completed_mesh_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                run = coordinator.run_mesh_brain_model_kernel_probe({"benchmark_iterations": 20})
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()

        self.assertEqual(run["scenario_key"], "mesh_brain_model_kernel_probe")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["evaluation_mode"], "mesh_brain_model_kernel")
        self.assertIn("mesh_brain_model_kernel_run_record", run["artifacts"])
        self.assertIn("mesh_brain_model_kernel_probe_summary", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_model_kernel_run_record"]["final_release_decision"], "pass")
        self.assertEqual([event.event_type for event in events], ["run_queued", "integration_artifact_recorded", "run_completed"])

    def test_http_route_records_model_kernel_probe_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/mesh-brain/model-kernel-probe",
                    data=json.dumps({"benchmark_iterations": 20}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["scenario_key"], "mesh_brain_model_kernel_probe")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifacts"]["mesh_brain_model_kernel_run_record"]["final_release_decision"], "pass")

    def test_live_serving_smoke_converts_to_artifact_bundle_and_run_record(self) -> None:
        from mesh_brain.run_live_serving_smoke import run_live_serving_smoke

        with TemporaryDirectory() as temp_dir:
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                summary = run_live_serving_smoke(
                    base_url="http://127.0.0.1:1234",
                    model="nvidia/nemotron-3-nano-4b",
                    output_directory=Path(temp_dir),
                    deterministic_release_decision="canary",
                )
            bundle = build_live_serving_artifact_bundle(summary=summary)
            run_record = live_serving_smoke_to_run_record(
                summary=summary,
                bundle=bundle,
                run_id="run_live_smoke_1",
            )

        self.assertEqual(set(bundle.artifacts), set(MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS))
        self.assertEqual(bundle.release_decision, "canary")
        self.assertEqual(bundle.deployment_record["status"], "eligible_for_canary")
        self.assertTrue(all(ref.exists for ref in bundle.artifacts.values()))
        self.assertTrue(all(ref.sha256 for ref in bundle.artifacts.values()))
        self.assertEqual(run_record["run_id"], "run_live_smoke_1")
        self.assertEqual(run_record["stage"], "completed")
        self.assertEqual(run_record["final_release_decision"], "canary")
        self.assertEqual(run_record["summary_metrics"]["live_smoke_gate"], "pass")
        self.assertEqual(run_record["summary_metrics"]["live_response_eval"], "pass")
        self.assertEqual(run_record["summary_metrics"]["live_judge_eval"], "pass")

    def test_coordinator_records_live_serving_smoke_as_completed_mesh_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                    run = coordinator.run_mesh_brain_live_serving_smoke(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    )
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()

        self.assertEqual(run["scenario_key"], "mesh_brain_live_serving_smoke")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["evaluation_mode"], "mesh_brain_live_serving_smoke")
        self.assertIn("mesh_brain_live_serving_run_record", run["artifacts"])
        self.assertIn("mesh_brain_live_serving_summary", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_live_serving_run_record"]["final_release_decision"], "canary")
        self.assertEqual([event.event_type for event in events], ["run_queued", "integration_artifact_recorded", "run_completed"])

    def test_coordinator_blocks_live_serving_smoke_on_infrastructure_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=RuntimeError("backend down")):
                    run = coordinator.run_mesh_brain_live_serving_smoke(
                        {"base_url": "http://127.0.0.1:1234", "model": "nvidia/nemotron-3-nano-4b"}
                    )
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()

        self.assertEqual(run["stage"], "failed")
        self.assertEqual(run["status"], "failed")
        self.assertIn("mesh_brain_live_serving_failure", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_live_serving_failure"]["release_decision"], "block")
        self.assertEqual([event.event_type for event in events], ["run_queued", "run_failed"])

    def test_http_route_records_live_serving_smoke_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/mesh-brain/live-serving-smoke",
                    data=json.dumps(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                    with urlopen(request, timeout=10) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["scenario_key"], "mesh_brain_live_serving_smoke")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifacts"]["mesh_brain_live_serving_run_record"]["final_release_decision"], "canary")


class _FakeOpenAIResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeOpenAIResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _fake_live_urlopen(request: Any, timeout: float) -> _FakeOpenAIResponse:
    return _FakeOpenAIResponse(
        {
            "id": "chatcmpl_live_control_plane_test",
            "model": "nvidia/nemotron-3-nano-4b",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Evidence indicates CROPS search latency. Use bounded reversible remediation, "
                            "keep rollback ready, and require operator approval before restart."
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 24, "total_tokens": 34},
        }
    )


if __name__ == "__main__":
    unittest.main()
