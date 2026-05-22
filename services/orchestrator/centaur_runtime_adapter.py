from __future__ import annotations

import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4


STATE_SLICE = "mesh.agent_sandbox_runtime.v1"
TERMINAL_STATUSES = {"completed", "failed_permanent", "cancelled"}


class FileBackedCentaurRuntime:
    """Mesh-owned Centaur-compatible proposal runtime.

    This is not a second control plane. It implements the small Centaur-style
    HTTP lifecycle Mesh needs for local compose and sandbox proof while keeping
    every execution proposal-only and replayable from file-backed state.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.executions = self.root / "executions"
        self.threads = self.root / "threads"
        self.executions.mkdir(parents=True, exist_ok=True)
        self.threads.mkdir(parents=True, exist_ok=True)

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        thread_key = str(payload.get("thread_key") or "")
        if not thread_key:
            raise ValueError("thread_key is required")
        execution_id = str(payload.get("execute_id") or f"exec_{uuid4().hex}")
        now = _timestamp()
        record = {
            "schema_version": STATE_SLICE,
            "execution_id": execution_id,
            "thread_key": thread_key,
            "assignment_generation": 1,
            "status": "completed",
            "terminal_reason": "proposal_recorded",
            "created_at": now,
            "updated_at": now,
            "harness": payload.get("harness") or "text",
            "result_text": "Mesh-owned sandbox runtime recorded a proposal-only execution.",
            "error_text": "",
            "agent_thread_id": f"thread_{_safe_id(thread_key)}",
            "events": [
                {
                    "event_id": f"{execution_id}_accepted",
                    "event_type": "centaur_execute_accepted",
                    "recorded_at": now,
                    "status": "accepted",
                    "summary": {"thread_key": thread_key},
                },
                {
                    "event_id": f"{execution_id}_completed",
                    "event_type": "centaur_execution_completed",
                    "recorded_at": now,
                    "status": "completed",
                    "summary": {"terminal_reason": "proposal_recorded"},
                },
            ],
            "release": {"released": False, "released_at": None},
            "authority": {
                "mesh_control_plane_authoritative": True,
                "runtime_adapter_authoritative": False,
                "policy_approval_actuation_allowed": False,
            },
        }
        self._write_execution(execution_id, record)
        return {
            "execution_id": execution_id,
            "thread_key": thread_key,
            "assignment_generation": 1,
            "status": "queued",
            "state_slice": STATE_SLICE,
        }

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        record = self._read_execution(execution_id)
        if record is None:
            raise KeyError(execution_id)
        return record

    def release(self, thread_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = _timestamp()
        released: list[str] = []
        for path in self.executions.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("thread_key") != thread_key:
                continue
            if payload.get("cancel_inflight") is True and record.get("status") not in TERMINAL_STATUSES:
                record["status"] = "cancelled"
                record["terminal_reason"] = "released"
            record["release"] = {"released": True, "released_at": now}
            record["updated_at"] = now
            self._write_execution(str(record["execution_id"]), record)
            released.append(str(record["execution_id"]))
        release_record = {
            "thread_key": thread_key,
            "released": bool(released),
            "released_execution_ids": released,
            "released_at": now,
            "state_slice": STATE_SLICE,
        }
        (self.threads / f"{_safe_id(thread_key)}.json").write_text(
            json.dumps(release_record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return release_record

    def _read_execution(self, execution_id: str) -> dict[str, Any] | None:
        path = self.executions / f"{_safe_id(execution_id)}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_execution(self, execution_id: str, record: dict[str, Any]) -> None:
        (self.executions / f"{_safe_id(execution_id)}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def make_handler(runtime: FileBackedCentaurRuntime, *, api_key: str | None = None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=401)
                return
            if self.path == "/agent/execute":
                try:
                    self._send_json(runtime.execute(self._read_json()))
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                return
            prefix = "/agent/threads/"
            suffix = "/release"
            if self.path.startswith(prefix) and self.path.endswith(suffix):
                encoded = self.path[len(prefix) : -len(suffix)]
                thread_key = urllib.parse.unquote(encoded)
                self._send_json(runtime.release(thread_key, self._read_json()))
                return
            self._send_json({"error": "not found"}, status=404)

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=401)
                return
            prefix = "/agent/executions/"
            if self.path.startswith(prefix):
                execution_id = urllib.parse.unquote(self.path[len(prefix) :])
                try:
                    self._send_json(runtime.get_execution(execution_id))
                except KeyError:
                    self._send_json({"error": "not found"}, status=404)
                return
            if self.path in {"/health", "/health/ready"}:
                self._send_json({"status": "ok", "state_slice": STATE_SLICE})
                return
            self._send_json({"error": "not found"}, status=404)

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _authorized(self) -> bool:
            if not api_key:
                return True
            return self.headers.get("Authorization") == f"Bearer {api_key}"

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    host = os.getenv("MESH_CENTAUR_ADAPTER_HOST", "0.0.0.0")
    port = int(os.getenv("MESH_CENTAUR_ADAPTER_PORT", "8080"))
    state_dir = os.getenv("MESH_CENTAUR_ADAPTER_STATE_DIR", "/app/.mesh-centaur-adapter")
    api_key = os.getenv(os.getenv("MESH_CENTAUR_API_KEY_ENV_NAME", "CENTAUR_API_KEY"), "") or None
    server = ThreadingHTTPServer((host, port), make_handler(FileBackedCentaurRuntime(state_dir), api_key=api_key))
    server.serve_forever()


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    main()
