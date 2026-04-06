from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from services.control_plane import RunCoordinator, TERMINAL_STAGES
from shared.mesh_runtime import RuntimeConfig


class MeshControlPlaneServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], config: RuntimeConfig):
        super().__init__(server_address, MeshControlPlaneRequestHandler)
        self.config = config
        self.coordinator = RunCoordinator(config)


class MeshControlPlaneRequestHandler(BaseHTTPRequestHandler):
    server: MeshControlPlaneServer
    protocol_version = "HTTP/1.1"

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return
        self._serve_static(path, head_only=True)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._send_json({"status": "ok", "timestamp": _timestamp()})
            return
        if path == "/api/readiness":
            self._send_json(self.server.coordinator.build_readiness())
            return
        if path == "/api/scenarios":
            self._send_json({"scenarios": self.server.coordinator.list_scenarios()})
            return
        if path == "/api/goals":
            self._send_json({"goals": self.server.coordinator.list_goals()})
            return
        if path == "/api/runs":
            self._send_json({"runs": self.server.coordinator.list_runs()})
            return
        if path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = path.split("/")[3]
            after = int(parse_qs(parsed.query).get("after", ["0"])[0])
            events = self.server.coordinator.state_store.list_run_events(run_id, after_sequence=after)
            self._send_json({"events": [event.to_dict() for event in events]})
            return
        if path.startswith("/api/runs/") and path.endswith("/merkle"):
            run_id = path.split("/")[3]
            snapshot = self.server.coordinator.state_store.get_merkle_snapshot(run_id)
            self._send_json(snapshot.to_dict())
            return
        if "/api/runs/" in path and "/merkle/proof/" in path:
            segments = [segment for segment in path.split("/") if segment]
            run_id = segments[2]
            event_id = segments[-1]
            proof = self.server.coordinator.state_store.get_merkle_proof(run_id, event_id)
            if proof is None:
                self._send_json({"error": "event not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(proof.to_dict())
            return
        if path.startswith("/api/runs/"):
            run_id = path.split("/")[3]
            payload = self.server.coordinator.get_run(run_id)
            if payload is None:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path == "/api/vault/tree":
            self._send_json({"tree": self.server.coordinator.state_store.tree()})
            return
        if path == "/api/vault/document":
            query = parse_qs(parsed.query)
            relative_path = query.get("path", [""])[0]
            if not relative_path:
                self._send_json({"error": "path is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(self.server.coordinator.state_store.read_document(relative_path))
            except FileNotFoundError:
                self._send_json({"error": "document not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/api/stream/runs/"):
            run_id = path.split("/")[4]
            self._stream_run(run_id)
            return
        if path == "/api/stream/system":
            self._stream_system()
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        payload = self._read_json_body()
        if parsed.path == "/api/goals":
            goal = self.server.coordinator.create_goal(payload)
            self._send_json(goal, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/runs":
            run = self.server.coordinator.create_run(payload)
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/steer"):
            run_id = parsed.path.split("/")[3]
            try:
                run = self.server.coordinator.steer_run(run_id, payload)
            except KeyError:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run)
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _serve_static(self, path: str, head_only: bool = False) -> None:
        assets_root = Path(self.server.config.web_asset_path)
        if not assets_root.exists():
            self._send_json(
                {
                    "error": "web assets not built",
                    "detail": "Run `npm install` and `npm run build` in mesh-intelligence/web before opening the browser.",
                },
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        relative_path = "index.html" if path in {"", "/"} else path.lstrip("/")
        candidate = (assets_root / relative_path).resolve()
        if not str(candidate).startswith(str(assets_root.resolve())) or not candidate.exists():
            candidate = assets_root / "index.html"
        content_type, _ = mimetypes.guess_type(str(candidate))
        raw = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if not head_only:
            self.wfile.write(raw)

    def _stream_run(self, run_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_id = int(self.headers.get("Last-Event-ID", "0") or "0")
        try:
            while True:
                events = self.server.coordinator.state_store.list_run_events(run_id, after_sequence=last_id)
                for event in events:
                    self._write_sse(
                        event_id=str(event.sequence),
                        event_type=event.event_type,
                        payload=event.to_dict(),
                    )
                    last_id = event.sequence
                run = self.server.coordinator.state_store.get_run_session(run_id)
                if run and run.stage in TERMINAL_STAGES and last_id >= run.latest_event_sequence:
                    self._write_sse(
                        event_id=str(last_id + 1),
                        event_type="complete",
                        payload={"run_id": run_id, "status": run.status, "stage": run.stage},
                    )
                    return
                self.wfile.write(b":heartbeat\n\n")
                self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _stream_system(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        event_id = 0
        try:
            while True:
                event_id += 1
                runs = self.server.coordinator.list_runs(limit=10)
                readiness = self.server.coordinator.build_readiness()
                payload = {
                    "timestamp": _timestamp(),
                    "runs": runs,
                    "readiness": readiness,
                    "active_runs": [run for run in runs if run["status"] not in {"completed", "failed", "cancelled"}],
                }
                self._write_sse(event_id=str(event_id), event_type="system", payload=payload)
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _write_sse(self, event_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
        self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))


def build_server(config: RuntimeConfig | None = None) -> MeshControlPlaneServer:
    resolved = config or RuntimeConfig.from_env()
    server = MeshControlPlaneServer((resolved.server_host, resolved.server_port), resolved)
    return server


def serve_forever(config: RuntimeConfig | None = None, start_sidecar: bool = True) -> MeshControlPlaneServer:
    server = build_server(config)
    if start_sidecar:
        server.coordinator.ensure_sidecar()
    try:
        server.serve_forever()
    finally:
        server.coordinator.sidecar.stop()
    return server


def start_server_in_thread(
    config: RuntimeConfig | None = None,
    start_sidecar: bool = True,
) -> tuple[MeshControlPlaneServer, threading.Thread]:
    server = build_server(config)
    if start_sidecar:
        server.coordinator.ensure_sidecar()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
