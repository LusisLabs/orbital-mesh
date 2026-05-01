from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mesh_brain import (
    AdapterRuntimeRequest,
    DeterministicAdapterRuntime,
    ModelArtifact,
    OpenAIChatRequest,
    OpenAICompatibleAdapterRuntime,
    ServingPlan,
    new_model_artifact,
)
from mesh_brain.runtime import ServingRoute, stable_digest


class MeshBrainAdapterRuntimeTests(unittest.TestCase):
    def test_filesystem_adapter_runtime_verifies_hashes_loads_and_infers(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifact = _artifact_with_outputs(Path(temp_dir))
            runtime = DeterministicAdapterRuntime()
            request = AdapterRuntimeRequest(
                adapter_artifact=artifact,
                base_model_id="qwen-27b-base",
                serving_backend="llama.cpp",
            )
            verified = runtime.verify(request)
            loaded = runtime.load(request)
            readiness = runtime.readiness(request)
            completion = runtime.infer(request=request, plan=_plan(artifact.artifact_id), chat_request=_chat_request(artifact.artifact_id))

        self.assertEqual(verified.status, "passed")
        self.assertEqual(loaded.status, "loaded")
        self.assertEqual(readiness.status, "ready")
        self.assertEqual(completion.model, artifact.artifact_id)
        self.assertIn(artifact.artifact_id, completion.content)
        self.assertEqual(completion.raw_response["adapter_runtime"]["status"], "ready")

    def test_filesystem_adapter_runtime_blocks_hash_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifact = _artifact_with_outputs(Path(temp_dir))
            output = Path(artifact.metadata["posttraining_proof_outputs"][0]["path"])
            output.write_text("tampered\n", encoding="utf-8")

            result = DeterministicAdapterRuntime().verify(
                AdapterRuntimeRequest(
                    adapter_artifact=artifact,
                    base_model_id="qwen-27b-base",
                    serving_backend="llama.cpp",
                )
            )

        self.assertEqual(result.status, "failed")
        self.assertTrue(result.details["hash_mismatches"])

    def test_openai_compatible_adapter_runtime_loads_and_infers_against_fake_server(self) -> None:
        server = None
        try:
            with TemporaryDirectory() as temp_dir:
                artifact = _artifact_with_outputs(Path(temp_dir))
                server = _FakeAdapterServer()
                runtime = OpenAICompatibleAdapterRuntime(base_url=server.base_url)
                request = AdapterRuntimeRequest(
                    adapter_artifact=artifact,
                    base_model_id="qwen-27b-base",
                    serving_backend="mlx",
                )

                loaded = runtime.load(request)
                readiness = runtime.readiness(request)
                completion = runtime.infer(request=request, plan=_plan(artifact.artifact_id), chat_request=_chat_request(artifact.artifact_id))
        finally:
            if server is not None:
                server.close()

        self.assertEqual(loaded.status, "loaded")
        self.assertEqual(readiness.status, "ready")
        self.assertEqual(completion.model, artifact.artifact_id)
        self.assertEqual(server.loaded_adapter_id, artifact.artifact_id)
        self.assertEqual(server.last_completion_payload["model"], artifact.artifact_id)
        self.assertEqual(server.last_completion_payload["metadata"]["mesh_brain_adapter_artifact_id"], artifact.artifact_id)


def _artifact_with_outputs(output_path: Path) -> ModelArtifact:
    adapter_path = output_path / "adapter_model.safetensors"
    config_path = output_path / "adapter_config.json"
    adapter_payload = {"adapter": "tiny", "rank": 2}
    config_payload = {"base_model_name_or_path": "qwen-27b-base", "peft_type": "LORA"}
    adapter_path.write_text(json.dumps(adapter_payload, sort_keys=True) + "\n", encoding="utf-8")
    config_path.write_text(json.dumps(config_payload, sort_keys=True) + "\n", encoding="utf-8")
    artifact = new_model_artifact(
        artifact_type="tenant_adapter",
        version="2026.04.30",
        signed_manifest_ref="sha256:test",
        tenant_id="tenant_a",
        task_type="crops",
        base_artifact_id="qwen-27b-base",
    )
    artifact.artifact_id = "adapter-test"
    artifact.metadata["posttraining_proof_outputs"] = [
        {"name": "adapter_model.safetensors", "path": str(adapter_path), "sha256": stable_digest(adapter_path.read_text(encoding="utf-8"))},
        {"name": "adapter_config.json", "path": str(config_path), "sha256": stable_digest(config_path.read_text(encoding="utf-8"))},
    ]
    return artifact


def _plan(model_artifact_id: str) -> ServingPlan:
    return ServingPlan(
        request_id="mb_req_test",
        route=ServingRoute(
            tenant_id="tenant_a",
            task_type="crops",
            hardware_tier="cpu_edge",
            engine="llama.cpp",
            secondary_engine=None,
            route_mode="single_request",
            verification_required=True,
            constrained_decoding=False,
            prefix_cache=False,
            continuous_batching=False,
            chunked_prefill=False,
            speculative_decoding=False,
            kv_aware_routing=False,
            adapter_artifact_ids=[model_artifact_id],
            model_artifact_id=model_artifact_id,
        ),
        backend_name="llama.cpp",
        pool_id="local",
        model_artifact_id=model_artifact_id,
        adapter_artifact_ids=[model_artifact_id],
        openai_compatible=True,
        streaming=False,
        structured_output=False,
        trace={"estimated_tokens": 8},
    )


def _chat_request(model: str) -> OpenAIChatRequest:
    return OpenAIChatRequest(
        tenant_id="tenant_a",
        messages=[{"role": "user", "content": "Check adapter identity."}],
        task_type="crops",
        hardware_tier="cpu_edge",
        risk_level="high",
        model=model,
    )


class _FakeAdapterServer:
    def __init__(self) -> None:
        try:
            self._server = HTTPServer(("127.0.0.1", 0), _FakeAdapterHandler)
        except PermissionError as exc:
            raise unittest.SkipTest(f"local HTTP server binding unavailable: {exc}") from exc
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._server.loaded_adapter_id = None
        self._server.last_completion_payload = {}
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def loaded_adapter_id(self) -> str | None:
        return self._server.loaded_adapter_id

    @property
    def last_completion_payload(self) -> dict[str, Any]:
        return self._server.last_completion_payload

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _FakeAdapterHandler(BaseHTTPRequestHandler):
    server: Any

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send({"status": "ok"})
            return
        if self.path == "/v1/models":
            data = []
            if self.server.loaded_adapter_id:
                data.append({"id": self.server.loaded_adapter_id, "object": "model", "owned_by": "mesh-brain"})
            self._send({"object": "list", "data": data})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        payload = self._read_json()
        if self.path == "/v1/adapters/load":
            self.server.loaded_adapter_id = payload["adapter_id"]
            self._send({"status": "loaded", "adapter_id": self.server.loaded_adapter_id})
            return
        if self.path == "/v1/chat/completions":
            self.server.last_completion_payload = payload
            self._send(
                {
                    "id": "chatcmpl_adapter_fake",
                    "object": "chat.completion",
                    "model": payload["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": f"adapter response for {payload['model']}"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
                }
            )
            return
        self.send_response(404)
        self.end_headers()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


if __name__ == "__main__":
    unittest.main()
