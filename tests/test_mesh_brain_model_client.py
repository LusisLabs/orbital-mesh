from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from unittest.mock import patch

from mesh_brain import (
    DeterministicMeshBrainModelClient,
    MeshBrainServingFabric,
    ModelArtifact,
    OpenAIChatRequest,
    OpenAICompatibleMeshBrainModelClient,
    ServingPool,
    TenantQuota,
    new_model_artifact,
)


class MeshBrainModelClientTests(unittest.TestCase):
    def test_deterministic_client_executes_serving_plan_through_client_boundary(self) -> None:
        fabric = _fabric()
        request = _request()
        execution = fabric.execute_chat_completion(
            request,
            client=DeterministicMeshBrainModelClient(content="CROPS response"),
        )

        self.assertEqual(execution.plan.backend_name, "sgl-project/sglang")
        self.assertEqual(execution.completion["backend_name"], "sgl-project/sglang")
        self.assertEqual(execution.completion["request_id"], execution.plan.request_id)
        self.assertIn("CROPS response", execution.completion["content"])
        self.assertEqual(execution.trace["client_boundary"], "DeterministicMeshBrainModelClient")
        self.assertGreater(execution.completion["usage"]["total_tokens"], 0)

    def test_openai_compatible_client_posts_chat_completion_payload(self) -> None:
        server = None
        try:
            server = _FakeOpenAIServer()
            client = OpenAICompatibleMeshBrainModelClient(base_url=server.base_url, api_key="test-token")
            fabric = _fabric()
            request = _request(stream=False)
            execution = fabric.execute_chat_completion(request, client=client)
        finally:
            if server is not None:
                server.close()

        self.assertEqual(execution.completion["completion_id"], "chatcmpl_fake")
        self.assertEqual(execution.completion["content"], "fake OpenAI-compatible response")
        self.assertEqual(execution.completion["finish_reason"], "stop")
        self.assertEqual(server.last_path, "/v1/chat/completions")
        self.assertEqual(server.last_headers["Authorization"], "Bearer test-token")
        self.assertEqual(server.last_payload["model"], "base")
        self.assertEqual(server.last_payload["messages"][0]["role"], "user")
        self.assertEqual(server.last_payload["metadata"]["mesh_brain_request_id"], execution.plan.request_id)
        self.assertEqual(server.last_payload["response_format"], {"type": "json_object"})

    def test_openai_compatible_client_normalizes_response_with_mocked_transport(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: float) -> _FakeUrlopenResponse:
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeUrlopenResponse(_fake_openai_response())

        fabric = _fabric()
        request = _request(stream=False)
        client = OpenAICompatibleMeshBrainModelClient(
            base_url="http://openai-compatible.local",
            api_key="test-token",
            timeout_seconds=7.0,
        )
        with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
            execution = fabric.execute_chat_completion(request, client=client)

        self.assertEqual(captured["url"], "http://openai-compatible.local/v1/chat/completions")
        self.assertEqual(captured["timeout"], 7.0)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(captured["payload"]["model"], "base")
        self.assertEqual(execution.completion["completion_id"], "chatcmpl_fake")
        self.assertEqual(execution.completion["usage"]["total_tokens"], 18)

    def test_openai_compatible_client_rejects_malformed_response(self) -> None:
        server = None
        try:
            server = _FakeOpenAIServer(response={"id": "bad", "choices": []})
            client = OpenAICompatibleMeshBrainModelClient(base_url=server.base_url)
            fabric = _fabric()
            with self.assertRaisesRegex(RuntimeError, "missing choices"):
                fabric.execute_chat_completion(_request(stream=False), client=client)
        finally:
            if server is not None:
                server.close()


def _fabric() -> MeshBrainServingFabric:
    base = _artifact("base_model", "base", state="production")
    adapter = _artifact("tenant_adapter", "adapter", state="production", tenant_id="tenant_a", task_type="crops")
    return MeshBrainServingFabric(
        pools=[ServingPool(pool_id="nvidia", hardware_tier="nvidia_datacenter", backend_name="sgl-project/sglang")],
        artifacts=[base, adapter],
        quotas={"tenant_a": TenantQuota(tenant_id="tenant_a", max_requests_per_minute=10, max_tokens_per_minute=10000)},
    )


def _request(*, stream: bool = True) -> OpenAIChatRequest:
    return OpenAIChatRequest(
        tenant_id="tenant_a",
        messages=[{"role": "user", "content": "Investigate search latency."}],
        task_type="crops",
        hardware_tier="nvidia_datacenter",
        risk_level="high",
        stream=stream,
        tools=[{"type": "function", "function": {"name": "kubernetes.get_deployment"}}],
        response_format={"type": "json_object"},
        metadata={"sla": "interactive"},
    )


def _artifact(
    artifact_type: str,
    artifact_id: str,
    *,
    state: str,
    tenant_id: str | None = None,
    task_type: str | None = None,
) -> ModelArtifact:
    artifact = new_model_artifact(
        artifact_type=artifact_type,
        version="2026.04.30",
        signed_manifest_ref=f"sha256:{artifact_id}",
        tenant_id=tenant_id,
        task_type=task_type,
    )
    artifact.artifact_id = artifact_id
    artifact.state = state
    return artifact


class _FakeOpenAIServer:
    def __init__(self, *, response: dict[str, Any] | None = None) -> None:
        handler = _handler(response or _fake_openai_response())
        try:
            self._server = HTTPServer(("127.0.0.1", 0), handler)
        except PermissionError as exc:
            raise unittest.SkipTest(f"local HTTP server binding unavailable: {exc}") from exc
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def last_payload(self) -> dict[str, Any]:
        return self._server.RequestHandlerClass.last_payload

    @property
    def last_headers(self) -> dict[str, str]:
        return self._server.RequestHandlerClass.last_headers

    @property
    def last_path(self) -> str:
        return self._server.RequestHandlerClass.last_path

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _handler(response_payload: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        last_payload: dict[str, Any] = {}
        last_headers: dict[str, str] = {}
        last_path: str = ""

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length)
            type(self).last_payload = json.loads(body.decode("utf-8"))
            type(self).last_headers = {key: value for key, value in self.headers.items()}
            type(self).last_path = self.path
            response = json.dumps(response_payload, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args: Any) -> None:
            return

    return Handler


def _fake_openai_response() -> dict[str, Any]:
    return {
        "id": "chatcmpl_fake",
        "object": "chat.completion",
        "created": 1777507200,
        "model": "base",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "fake OpenAI-compatible response"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


class _FakeUrlopenResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeUrlopenResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload, sort_keys=True).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
