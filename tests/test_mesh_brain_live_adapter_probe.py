from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mesh_brain.live_adapter_probe import run_live_adapter_runtime_probe


class MeshBrainLiveAdapterProbeTests(unittest.TestCase):
    def test_live_probe_records_base_model_pass_when_adapter_load_is_unsupported(self) -> None:
        server = None
        try:
            server = _FakeLiveAdapterProbeServer(adapter_supported=False)
            with TemporaryDirectory() as temp_dir:
                summary = run_live_adapter_runtime_probe(
                    base_url=server.base_url,
                    model="nvidia/nemotron-3-nano-4b",
                    output_directory=Path(temp_dir),
                )
                artifact = json.loads((Path(temp_dir) / "live_adapter_runtime_probe.json").read_text(encoding="utf-8"))
        finally:
            if server is not None:
                server.close()

        self.assertEqual(summary["status"], "base_model_pass")
        self.assertTrue(summary["decision"]["base_model_passed"])
        self.assertFalse(summary["decision"]["adapter_load_supported"])
        self.assertFalse(summary["decision"]["adapter_serving_passed"])
        self.assertEqual(summary["adapter_load"]["status_code"], 404)
        self.assertEqual(artifact["status"], "base_model_pass")

    def test_live_probe_passes_adapter_serving_when_load_is_supported_and_model_appears(self) -> None:
        server = None
        try:
            server = _FakeLiveAdapterProbeServer(adapter_supported=True)
            with TemporaryDirectory() as temp_dir:
                summary = run_live_adapter_runtime_probe(
                    base_url=server.base_url,
                    model="nvidia/nemotron-3-nano-4b",
                    adapter_id="adapter-live",
                    output_directory=Path(temp_dir),
                    require_adapter_load=True,
                )
        finally:
            if server is not None:
                server.close()

        self.assertEqual(summary["status"], "adapter_pass")
        self.assertTrue(summary["decision"]["adapter_load_supported"])
        self.assertTrue(summary["decision"]["adapter_serving_passed"])
        self.assertEqual(server.loaded_adapter_id, "adapter-live")
        self.assertEqual(server.last_chat_payload["model"], "nvidia/nemotron-3-nano-4b")

    def test_live_probe_blocks_when_adapter_load_is_required_but_unsupported(self) -> None:
        server = None
        try:
            server = _FakeLiveAdapterProbeServer(adapter_supported=False)
            with TemporaryDirectory() as temp_dir:
                summary = run_live_adapter_runtime_probe(
                    base_url=server.base_url,
                    model="nvidia/nemotron-3-nano-4b",
                    output_directory=Path(temp_dir),
                    require_adapter_load=True,
                )
        finally:
            if server is not None:
                server.close()

        self.assertEqual(summary["status"], "block")
        self.assertIn("adapter_load_required_but_unsupported", summary["decision"]["reasons"])


class _FakeLiveAdapterProbeServer:
    def __init__(self, *, adapter_supported: bool) -> None:
        handler = _handler(adapter_supported=adapter_supported)
        try:
            self._server = HTTPServer(("127.0.0.1", 0), handler)
        except PermissionError as exc:
            raise unittest.SkipTest(f"local HTTP server binding unavailable: {exc}") from exc
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._server.loaded_adapter_id = None
        self._server.last_chat_payload = {}
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def loaded_adapter_id(self) -> str | None:
        return self._server.loaded_adapter_id

    @property
    def last_chat_payload(self) -> dict[str, Any]:
        return self._server.last_chat_payload

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _handler(*, adapter_supported: bool) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server: Any

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/models":
                data = [{"id": "nvidia/nemotron-3-nano-4b", "object": "model"}]
                if self.server.loaded_adapter_id:
                    data.append({"id": self.server.loaded_adapter_id, "object": "model"})
                self._send({"object": "list", "data": data})
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            payload = self._read_json()
            if self.path == "/v1/chat/completions":
                self.server.last_chat_payload = payload
                self._send(
                    {
                        "id": "chatcmpl_live_probe",
                        "object": "chat.completion",
                        "model": payload["model"],
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
                        "usage": {"prompt_tokens": 12, "completion_tokens": 20, "total_tokens": 32},
                    }
                )
                return
            if self.path == "/v1/adapters/load":
                if not adapter_supported:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.server.loaded_adapter_id = payload["adapter_id"]
                self._send({"status": "loaded", "adapter_id": self.server.loaded_adapter_id})
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

    return Handler


if __name__ == "__main__":
    unittest.main()
