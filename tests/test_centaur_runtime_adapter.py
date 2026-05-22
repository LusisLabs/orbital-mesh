from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from services.orchestrator.centaur_runtime_adapter import FileBackedCentaurRuntime, make_handler


class CentaurRuntimeAdapterTests(unittest.TestCase):
    def test_runtime_adapter_serves_execute_replay_and_release_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = FileBackedCentaurRuntime(Path(tmp))
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime, api_key="test-key"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                execute = _request_json(
                    f"{base_url}/agent/execute",
                    method="POST",
                    api_key="test-key",
                    payload={"thread_key": "mesh:run:task:codex", "execute_id": "exec_test", "harness": "codex"},
                )
                replay = _request_json(
                    f"{base_url}/agent/executions/{execute['execution_id']}",
                    method="GET",
                    api_key="test-key",
                )
                release = _request_json(
                    f"{base_url}/agent/threads/{urllib.parse.quote('mesh:run:task:codex', safe='')}/release",
                    method="POST",
                    api_key="test-key",
                    payload={"cancel_inflight": False},
                )
                released_replay = _request_json(
                    f"{base_url}/agent/executions/{execute['execution_id']}",
                    method="GET",
                    api_key="test-key",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

            self.assertEqual(execute["status"], "queued")
            self.assertEqual(replay["status"], "completed")
            self.assertEqual(replay["authority"]["runtime_adapter_authoritative"], False)
            self.assertEqual(replay["events"][0]["event_type"], "centaur_execute_accepted")
            self.assertEqual(release["released"], True)
            self.assertEqual(released_replay["release"]["released"], True)

    def test_runtime_adapter_rejects_missing_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_handler(FileBackedCentaurRuntime(Path(tmp)), api_key="test-key"),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/agent/execute",
                    data=json.dumps({"thread_key": "mesh:run:task:codex"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(raised.exception.code, 401)
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


def _request_json(
    url: str,
    *,
    method: str,
    api_key: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert isinstance(result, dict)
    return result


if __name__ == "__main__":
    unittest.main()
