from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from services.control_plane import RunCoordinator, TERMINAL_STAGES
from services.ingest.webhook_service import (
    SignatureMismatchError,
    UnknownWebhookSourceError,
    WebhookIngestError,
)
from shared.mesh_runtime import RuntimeConfig

_LOG = logging.getLogger("mesh.control_plane")
TIMELINE_PROOF_ROUTE_TEMPLATE = "/api/runs/{run_id}/timeline-proof"


class AuthorizationError(PermissionError):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.FORBIDDEN):
        super().__init__(message)
        self.status = status


def _safe_segment(path: str, index: int) -> str | None:
    """Extract a URL path segment by index, returning None if out of bounds."""
    segments = [s for s in path.split("/") if s]
    return segments[index] if index < len(segments) else None


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _roles_for_steering(command: object) -> set[str]:
    if command in {"approve", "override_decision", "override_execution_parameters"}:
        return {"approver", "admin"}
    if command in {"override_review", "postmortem_review"}:
        return {"viewer", "launcher", "approver", "admin"}
    return {"launcher", "approver", "admin"}


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "auto_mode": run.get("auto_mode"),
        "created_at": run.get("created_at"),
        "error": run.get("error"),
        "evaluation_mode": run.get("evaluation_mode"),
        "goal_id": run.get("goal_id"),
        "latest_event_id": run.get("latest_event_id"),
        "latest_event_sequence": run.get("latest_event_sequence"),
        "latest_merkle_root": run.get("latest_merkle_root"),
        "orchestration_mode": run.get("orchestration_mode"),
        "pending_pause_stage": run.get("pending_pause_stage"),
        "run_id": run.get("run_id"),
        "scenario_key": run.get("scenario_key"),
        "stage": run.get("stage"),
        "status": run.get("status"),
        "steering_mode": run.get("steering_mode"),
        "updated_at": run.get("updated_at"),
    }


def darkharness_packet_response(coordinator: RunCoordinator, run_id: str) -> tuple[dict[str, Any], HTTPStatus]:
    payload = coordinator.build_darkharness_packet(run_id)
    if payload is None:
        return {"error": "run not found"}, HTTPStatus.NOT_FOUND
    status = HTTPStatus.CONFLICT if payload.get("status") == "blocked" else HTTPStatus.OK
    return payload, status


def darkharness_checkpoint_packet_response(coordinator: RunCoordinator) -> tuple[dict[str, Any], HTTPStatus]:
    payload = coordinator.build_darkharness_pilot_checkpoint_packet()
    status = HTTPStatus.CONFLICT if payload.get("status") == "blocked" else HTTPStatus.OK
    return payload, status


class MeshControlPlaneServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], config: RuntimeConfig):
        super().__init__(server_address, MeshControlPlaneRequestHandler)
        self.config = config
        self.coordinator = RunCoordinator(config)

    def server_close(self) -> None:
        if hasattr(self, "coordinator"):
            self.coordinator.stop_background_workers()
        super().server_close()


class MeshControlPlaneRequestHandler(BaseHTTPRequestHandler):
    server: MeshControlPlaneServer
    protocol_version = "HTTP/1.1"

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self._add_security_headers()
            self._add_cors_headers()
            self.end_headers()
            return
        self._serve_static(path, head_only=True)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._add_security_headers()
        self._add_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "timestamp": _timestamp(),
                    "environment": self.server.config.environment,
                    "version": self.server.config.build_version,
                    "commit": self.server.config.build_commit,
                }
            )
            return
        if path == "/api/readiness":
            self._send_json(self.server.coordinator.build_readiness())
            return
        if path == "/api/policy/lifecycle":
            self._send_json(self.server.coordinator.build_policy_lifecycle())
            return
        if path == "/api/connectors/certification":
            self._send_json(self.server.coordinator.build_connector_certification())
            return
        if path == "/api/deployment/compatibility":
            self._send_json(self.server.coordinator.build_deployment_compatibility())
            return
        if path == "/api/failure-modes":
            self._send_json(self.server.coordinator.build_failure_mode_library())
            return
        if path == "/api/approvals":
            try:
                self._authorize({"viewer", "launcher", "approver", "admin"})
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            self._send_json(self.server.coordinator.build_approval_queue())
            return
        if path == "/api/kill-switch":
            self._send_json(self.server.coordinator.kill_switch_status())
            return
        if path == "/api/pilot/go-no-go":
            self._send_json(self.server.coordinator.generate_pilot_go_no_go())
            return
        if path == "/api/darkharness/pilot-packet":
            payload, status = darkharness_checkpoint_packet_response(self.server.coordinator)
            self._send_json(payload, status=status)
            return
        if path == "/api/rules/suggestions":
            # Layer 4 admin surface. Returns [] when rule_learning_enabled is
            # off or too few overrides have accumulated. Suggestions never
            # auto-apply — operators paste approved rules into the policy file.
            self._send_json({"suggestions": self.server.coordinator.list_rule_suggestions()})
            return
        if path == "/api/scenarios":
            self._send_json({"scenarios": self.server.coordinator.list_scenarios()})
            return
        if path == "/api/simulations":
            self._send_json({"simulations": self.server.coordinator.list_simulations()})
            return
        if path == "/api/benchmarks":
            limit = _safe_int(parse_qs(parsed.query).get("limit", ["100"])[0], default=100)
            self._send_json({"benchmarks": self.server.coordinator.list_benchmarks(limit=limit)})
            return
        if path.startswith("/api/benchmarks/"):
            benchmark_id = _safe_segment(path, 2)
            if benchmark_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            benchmark = self.server.coordinator.get_benchmark(benchmark_id)
            if benchmark is None:
                self._send_json({"error": "benchmark not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(benchmark)
            return
        if path == "/api/service-agents":
            self._send_json({"service_agents": self.server.coordinator.list_service_agents()})
            return
        if path.startswith("/api/reconciliation/"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            reconciliation = self.server.coordinator.get_reconciliation(run_id)
            if reconciliation is None:
                self._send_json({"error": "reconciliation not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(reconciliation)
            return
        if path == "/api/goals":
            self._send_json({"goals": self.server.coordinator.list_goals()})
            return
        if path == "/api/runs":
            if parse_qs(parsed.query).get("summary", ["0"])[0] in {"1", "true"}:
                runs = self.server.coordinator.list_run_summaries()
            else:
                runs = self.server.coordinator.list_runs()
            self._send_json({"runs": runs})
            return
        if path == "/api/memory/active":
            service = parse_qs(parsed.query).get("service", [None])[0]
            self._send_json(self.server.coordinator.get_active_memory(service))
            return
        if path == "/api/memory/query":
            query = parse_qs(parsed.query).get("q", [""])[0]
            service = parse_qs(parsed.query).get("service", [None])[0]
            limit = _safe_int(parse_qs(parsed.query).get("limit", ["10"])[0], default=10)
            self._send_json(self.server.coordinator.query_memory(query, {"service": service} if service else {}, limit=limit))
            return
        if path.startswith("/api/memory/claims/"):
            claim_id = _safe_segment(path, 3)
            if claim_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            claim = self.server.coordinator.get_memory_claim(claim_id)
            if claim is None:
                self._send_json({"error": "claim not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(claim)
            return
        if path == "/api/memory/graph":
            service = parse_qs(parsed.query).get("service", [None])[0]
            self._send_json(self.server.coordinator.get_memory_graph(service))
            return
        if path == "/api/research-sessions":
            self._send_json({"sessions": self.server.coordinator.list_research_sessions()})
            return
        if path == "/api/research-corpus":
            self._send_json(self.server.coordinator.get_research_corpus())
            return
        if path.startswith("/api/research-sessions/"):
            raw = path[len("/api/research-sessions/") :].strip("/")
            session_id = unquote(raw)
            detail = self.server.coordinator.get_research_session(session_id)
            if detail is None:
                self._send_json({"error": "research session not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(detail)
            return
        if path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            after = _safe_int(parse_qs(parsed.query).get("after", ["0"])[0])
            events = self.server.coordinator.state_store.list_run_events(run_id, after_sequence=after)
            self._send_json({"events": [event.to_dict() for event in events]})
            return
        if path.startswith("/api/runs/") and path.endswith("/scenario-analysis"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.server.coordinator.get_scenario_analysis(run_id)
            if payload is None:
                self._send_json({"error": "scenario analysis not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path.startswith("/api/runs/") and path.endswith("/evidence-graph"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.server.coordinator.get_evidence_graph(run_id)
            if payload is None:
                self._send_json({"error": "evidence graph not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path.startswith("/api/runs/") and path.endswith("/merkle"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            snapshot = self.server.coordinator.state_store.get_merkle_snapshot(run_id)
            self._send_json(snapshot.to_dict())
            return
        if path.startswith("/api/runs/") and path.endswith("/timeline-proof"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.server.coordinator.build_timeline_proof(run_id)
            if payload is None:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path.startswith("/api/runs/") and path.endswith("/agent-tasks"):
            run_id = path.split("/")[3]
            try:
                self._send_json({"tasks": self.server.coordinator.list_agent_tasks(run_id)})
            except KeyError:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/api/runs/") and path.endswith("/memory-crystallization"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.server.coordinator.get_memory_crystallization(run_id)
            if payload is None:
                self._send_json({"error": "memory crystallization not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path.startswith("/api/runs/") and path.endswith("/reasoning-bank"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.server.coordinator.get_reasoning_bank(run_id)
            if payload is None:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path.startswith("/api/runs/") and path.endswith("/darkharness-packet"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload, status = darkharness_packet_response(self.server.coordinator, run_id)
            self._send_json(payload, status=status)
            return
        if "/api/runs/" in path and "/merkle/proof/" in path:
            segments = [segment for segment in path.split("/") if segment]
            run_id = segments[2] if len(segments) > 2 else None
            event_id = segments[-1] if len(segments) > 5 else None
            if run_id is None or event_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            proof = self.server.coordinator.state_store.get_merkle_proof(run_id, event_id)
            if proof is None:
                self._send_json({"error": "event not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(proof.to_dict())
            return
        if path.startswith("/api/runs/"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.server.coordinator.get_run(run_id)
            if payload is None:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path == "/api/webhook-sources":
            self._send_json({"sources": self.server.coordinator.list_webhook_sources()})
            return
        if path.startswith("/api/webhook-sources/"):
            source_id = path.split("/")[-1]
            try:
                self._send_json(self.server.coordinator.get_webhook_source(source_id))
            except UnknownWebhookSourceError:
                self._send_json({"error": "source not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if path == "/api/alerts":
            query = parse_qs(parsed.query)
            source_id = query.get("source_id", [None])[0]
            limit = _safe_int(query.get("limit", ["100"])[0], default=100)
            alerts = self.server.coordinator.list_alert_events(source_id, limit=limit)
            self._send_json({"alerts": alerts})
            return
        if path == "/api/watch/status":
            self._send_json(self.server.coordinator.watch_status())
            return
        if path == "/api/watchers":
            self._send_json(self.server.coordinator.watchers_status())
            return
        if path == "/api/watchers/ownership":
            self._send_json(self.server.coordinator.build_watcher_ownership())
            return
        if path.startswith("/api/watchers/") and path.count("/") == 3:
            # GET /api/watchers/{name}
            name = path.split("/", 3)[3]
            detail = self.server.coordinator._watcher_detail(name)
            if not detail.get("registered", False):
                self._send_json(
                    {"error": f"watcher {name!r} not registered"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_json(detail)
            return
        if path == "/api/graph/status":
            self._send_json(self.server.coordinator.graph_status())
            return
        if path == "/api/graph/snapshot":
            snap = self.server.coordinator.graph_snapshot()
            if snap is None:
                self._send_json({"error": "graph not populated"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(snap)
            return
        if path.startswith("/api/graph/neighbors/"):
            parts = path[len("/api/graph/neighbors/"):].split("/")
            if len(parts) < 3:
                self._send_json({"error": "usage: /api/graph/neighbors/{kind}/{namespace}/{name}"}, status=HTTPStatus.BAD_REQUEST)
                return
            kind, namespace, name = parts[0], parts[1], "/".join(parts[2:])
            namespace_arg = None if namespace in ("_cluster", "-") else namespace
            query = parse_qs(parsed.query)
            depth = _safe_int(query.get("depth", ["1"])[0], default=1)
            direction = query.get("direction", ["both"])[0]
            edge_kinds_raw = query.get("edge_kinds", [""])[0]
            edge_kinds = [k for k in edge_kinds_raw.split(",") if k] or None
            neighbors = self.server.coordinator.graph_neighbors(
                kind, name, namespace_arg,
                depth=depth, edge_kinds=edge_kinds, direction=direction,
            )
            self._send_json({"neighbors": neighbors})
            return
        if path.startswith("/api/graph/node/"):
            parts = path[len("/api/graph/node/"):].split("/")
            if len(parts) < 3:
                self._send_json({"error": "usage: /api/graph/node/{kind}/{namespace}/{name}"}, status=HTTPStatus.BAD_REQUEST)
                return
            kind, namespace, name = parts[0], parts[1], "/".join(parts[2:])
            namespace_arg = None if namespace in ("_cluster", "-") else namespace
            node = self.server.coordinator.graph_node(kind, name, namespace_arg)
            if node is None:
                self._send_json({"error": "node not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(node)
            return
        if path.startswith("/api/graph/affected/"):
            parts = path[len("/api/graph/affected/"):].split("/")
            if len(parts) != 2:
                self._send_json({"error": "usage: /api/graph/affected/{namespace}/{deployment}"}, status=HTTPStatus.BAD_REQUEST)
                return
            namespace, deployment = parts
            services = self.server.coordinator.graph_affected_services(deployment, namespace)
            self._send_json({"affected_services": services})
            return
        if path == "/api/trust-ladder":
            self._send_json({"entries": self.server.coordinator.trust_ladder_list()})
            return
        if path == "/api/agent/slo":
            self._send_json(self.server.coordinator.agent_slo_report())
            return
        if path == "/metrics":
            body = self.server.coordinator.agent_slo_prometheus().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/trust-ladder/"):
            parts = path[len("/api/trust-ladder/"):].split("/", 1)
            if len(parts) != 2:
                self._send_json({"error": "usage: /api/trust-ladder/{action_class}/{service}"}, status=HTTPStatus.BAD_REQUEST)
                return
            action_class, service = parts
            entry = self.server.coordinator.trust_ladder_entry(action_class, service)
            self._send_json(entry)
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
            if ".." in relative_path or relative_path.startswith("/"):
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            vault_root = Path(self.server.config.vault_path).resolve()
            resolved = (vault_root / relative_path).resolve()
            if not str(resolved).startswith(str(vault_root)):
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(self.server.coordinator.state_store.read_document(relative_path))
            except FileNotFoundError:
                self._send_json({"error": "document not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/api/stream/runs/"):
            run_id = _safe_segment(path, 3)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._stream_run(run_id)
            return
        if path == "/api/stream/system":
            self._stream_system()
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._request_body_within_limit():
            self._send_json(
                {"error": "payload too large"},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        raw_body = self._read_request_body()
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except (json.JSONDecodeError, ValueError):
            self._send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(payload, dict):
            # Webhook vendors occasionally ship JSON arrays at the root;
            # wrap them so path expressions like "$.alerts[0]" still work.
            payload = {"root": payload}
        if parsed.path == "/v1/metrics":
            # OTLP/HTTP metrics receiver — opt-in. When enabled, an OTel
            # Collector (or any OTLP producer) posts here and the payload
            # becomes a Mesh run via the OtlpPushIngester.
            if not self.server.config.otel_receiver_enabled:
                self._send_json(
                    {"error": "otlp receiver disabled"},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            self._handle_otlp_metrics(payload)
            return
        if parsed.path == "/api/watch/start":
            try:
                self._authorize({"admin"})
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            self._send_json(self.server.coordinator.watch_start())
            return
        if parsed.path == "/api/watch/stop":
            try:
                self._authorize({"admin"})
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            self._send_json(self.server.coordinator.watch_stop())
            return
        if parsed.path.startswith("/api/watchers/") and parsed.path.endswith("/start"):
            try:
                self._authorize({"admin"})
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            name = parsed.path[len("/api/watchers/"):-len("/start")]
            if not name:
                self._send_json({"error": "watcher name required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(self.server.coordinator.watcher_start(name))
            except KeyError:
                self._send_json(
                    {"error": f"watcher {name!r} not registered"},
                    status=HTTPStatus.NOT_FOUND,
                )
            return
        if parsed.path.startswith("/api/watchers/") and parsed.path.endswith("/stop"):
            try:
                self._authorize({"admin"})
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            name = parsed.path[len("/api/watchers/"):-len("/stop")]
            if not name:
                self._send_json({"error": "watcher name required"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(self.server.coordinator.watcher_stop(name))
            return
        if parsed.path == "/api/trust-ladder/override":
            try:
                payload["_operator"] = self._authorize({"admin", "approver"})
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            action_class = str(payload.get("action_class", "")).strip()
            service = str(payload.get("service", "")).strip()
            level = str(payload.get("level", "")).strip()
            reason = str(payload.get("reason", "operator_override"))
            if not action_class or not service or not level:
                self._send_json(
                    {"error": "action_class, service, and level are required"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                entry = self.server.coordinator.trust_ladder_override(
                    action_class, service, level, reason=reason,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(entry)
            return
        if parsed.path == "/api/graph/refresh":
            namespaces_raw = payload.get("namespaces") if isinstance(payload, dict) else None
            namespaces = None
            if isinstance(namespaces_raw, list):
                namespaces = [str(n) for n in namespaces_raw if n]
            result = self.server.coordinator.graph_refresh(namespaces=namespaces)
            status = HTTPStatus.OK if result.get("status") == "succeeded" else HTTPStatus.SERVICE_UNAVAILABLE
            self._send_json(result, status=status)
            return
        if parsed.path == "/api/policy/simulate":
            try:
                payload["_operator"] = self._authorize({"viewer", "launcher", "approver", "admin"})
                result = self.server.coordinator.simulate_policy(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except KeyError:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/kill-switch":
            try:
                payload["_operator"] = self._authorize({"admin"})
                result = self.server.coordinator.apply_kill_switch(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/export/archive"):
            try:
                self._authorize({"viewer", "launcher", "approver", "admin"})
                run_id = _safe_segment(parsed.path, 2)
                if run_id is None:
                    self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                    return
                archive = self.server.coordinator.export_run_archive(run_id)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if archive is None:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_file_response(
                Path(archive["path"]),
                content_type=str(archive["content_type"]),
                download_name=str(archive["filename"]),
            )
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/export"):
            try:
                self._authorize({"viewer", "launcher", "approver", "admin"})
                run_id = _safe_segment(parsed.path, 2)
                if run_id is None:
                    self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                    return
                package = self.server.coordinator.export_run_package(run_id)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if package is None:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(package)
            return
        if parsed.path == "/api/goals":
            goal = self.server.coordinator.create_goal(payload)
            self._send_json(goal, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/runs":
            try:
                payload["_operator"] = self._authorize({"launcher", "admin"})
                run = self.server.coordinator.create_run(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:  # pragma: no cover - defensive; avoid empty TCP replies to clients
                _LOG.exception("POST /api/runs failed: %s", exc)
                self._send_json(
                    {"error": "run creation failed", "detail": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/mesh-brain/model-kernel-probe":
            try:
                payload["_operator"] = self._authorize({"launcher", "admin"})
                run = self.server.coordinator.run_mesh_brain_model_kernel_probe(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/mesh-brain/meshmodel-probe":
            try:
                payload["_operator"] = self._authorize({"launcher", "admin"})
                run = self.server.coordinator.run_mesh_brain_meshmodel_probe(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/mesh-brain/live-serving-smoke":
            try:
                payload["_operator"] = self._authorize({"launcher", "admin"})
                run = self.server.coordinator.run_mesh_brain_live_serving_smoke(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/mesh-brain/rollback-drill":
            try:
                payload["_operator"] = self._authorize({"launcher", "admin"})
                run = self.server.coordinator.run_mesh_brain_rollback_drill(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/mesh-brain/backend-matrix":
            try:
                payload["_operator"] = self._authorize({"launcher", "admin"})
                run = self.server.coordinator.run_mesh_brain_backend_matrix(payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path.startswith("/api/simulations/") and parsed.path.endswith("/run"):
            scenario_id = _safe_segment(parsed.path, 2)
            if scenario_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                run = self.server.coordinator.run_simulation(scenario_id, payload)
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            except KeyError:
                self._send_json({"error": "simulation not found"}, status=HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/memory/maintenance/run":
            self._send_json(self.server.coordinator.run_memory_maintenance(), status=HTTPStatus.CREATED)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/steer"):
            run_id = _safe_segment(parsed.path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                payload["_operator"] = self._authorize(_roles_for_steering(payload.get("command")))
                run = self.server.coordinator.steer_run(run_id, payload)
            except AuthorizationError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
                return
            except KeyError:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run)
            return
        if parsed.path == "/api/webhook-sources":
            try:
                record = self.server.coordinator.register_webhook_source(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(record, status=HTTPStatus.CREATED)
            return
        if parsed.path.startswith("/api/webhooks/"):
            source_id = parsed.path.split("/", 3)[-1]
            signature = self.headers.get("X-Mesh-Signature") or self.headers.get(
                "X-Hub-Signature-256"
            )
            try:
                outcome = self.server.coordinator.ingest_webhook(
                    source_id,
                    payload,
                    raw_body=raw_body,
                    signature=signature,
                )
            except UnknownWebhookSourceError:
                self._send_json({"error": "source not found"}, status=HTTPStatus.NOT_FOUND)
                return
            except SignatureMismatchError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
                return
            except WebhookIngestError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(outcome, status=HTTPStatus.ACCEPTED)
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/webhook-sources/"):
            source_id = parsed.path.split("/")[-1]
            try:
                self.server.coordinator.delete_webhook_source(source_id)
            except UnknownWebhookSourceError:
                self._send_json({"error": "source not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"deleted": source_id})
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_otlp_metrics(self, otlp_payload: dict[str, Any]) -> None:
        """Accept an OTLP/HTTP JSON metrics payload and spawn a Mesh run.

        Optional bearer-token auth via ``MESH_OTEL_RECEIVER_TOKEN``. The
        sender can attach ``x-mesh-alert-context`` as a JSON header naming the
        metric that tripped and supplying a baseline value; without it the
        ingester falls back to heuristics (latency/error name matching).
        """
        expected_token = self.server.config.otel_receiver_token
        if expected_token:
            provided = self.headers.get("Authorization", "")
            if provided != f"Bearer {expected_token}":
                self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                return

        alert_context: dict[str, Any] = {}
        raw_alert_header = self.headers.get("x-mesh-alert-context") or self.headers.get("X-Mesh-Alert-Context")
        if raw_alert_header:
            try:
                parsed_alert = json.loads(raw_alert_header)
                if isinstance(parsed_alert, dict):
                    alert_context = parsed_alert
            except json.JSONDecodeError:
                self._send_json(
                    {"error": "invalid x-mesh-alert-context header"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

        create_payload: dict[str, Any] = {
            "otlp_payload": otlp_payload,
            "alert_context": alert_context,
            "evaluation_mode": self.server.config.evaluation_mode,
            "orchestration_mode": self.server.config.orchestration_mode,
            "steering_mode": self.server.config.default_steering_mode,
        }
        try:
            run = self.server.coordinator.create_run(create_payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.exception("OTLP metric ingestion failed: %s", exc)
            self._send_json(
                {"error": "otlp ingestion failed", "detail": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._send_json(
            {"status": "accepted", "run_id": run.get("run_id"), "scenario_key": run.get("scenario_key")},
            status=HTTPStatus.ACCEPTED,
        )

    def _operator_context(self) -> dict[str, Any]:
        identity = (
            self.headers.get(self.server.config.operator_header_name)
            or self.headers.get("X-Forwarded-User")
            or self.headers.get("X-Auth-Request-Email")
            or ""
        ).strip()
        raw_roles = (
            self.headers.get(self.server.config.operator_roles_header_name)
            or self.headers.get("X-Mesh-Role")
            or ""
        )
        roles = sorted({role.strip().lower() for role in raw_roles.replace(";", ",").split(",") if role.strip()})
        if not identity:
            identity = "anonymous"
        return {
            "operator_id": identity,
            "roles": roles,
            "source": "proxy_header" if identity != "anonymous" else "local_anonymous",
            "source_ip": self.client_address[0] if self.client_address else None,
        }

    def _authorize(self, allowed_roles: set[str]) -> dict[str, Any]:
        operator = self._operator_context()
        identity_required = self.server.config.operator_identity_required
        if not identity_required:
            return operator
        if operator["operator_id"] == "anonymous":
            raise AuthorizationError("operator identity is required", HTTPStatus.UNAUTHORIZED)
        roles = set(operator.get("roles") or [])
        if not roles & allowed_roles:
            allowed = ", ".join(sorted(allowed_roles))
            raise AuthorizationError(f"operator role required: {allowed}", HTTPStatus.FORBIDDEN)
        return operator

    def log_message(self, format: str, *args: Any) -> None:
        if not self.server.config.access_log_enabled:
            return
        try:
            client_host = self.client_address[0] if self.client_address else "-"
        except Exception:  # pragma: no cover - defensive for malformed handler state
            client_host = "-"
        _LOG.info("%s - %s", client_host, format % args)

    def _serve_static(self, path: str, head_only: bool = False) -> None:
        assets_root = Path(self.server.config.web_asset_path)
        if not assets_root.exists():
            self._send_json(
                {
                    "error": "web assets not built",
                    "detail": "Run `npm --prefix web install` and `npm --prefix web run build` in orbital-mesh before opening the browser.",
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
        self._add_security_headers()
        self.send_header("Content-Type", content_type or "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if not head_only:
            self.wfile.write(raw)

    def _stream_run(self, run_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self._add_security_headers()
        self._add_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_id = _safe_int(self.headers.get("Last-Event-ID", "0") or "0")
        deadline = time.monotonic() + self.server.config.sse_max_connection_seconds
        try:
            while time.monotonic() < deadline:
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
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        except Exception:
            _LOG.exception("SSE stream error for run %s", run_id)
            return

    def _stream_system(self) -> None:
        self.send_response(HTTPStatus.OK)
        self._add_security_headers()
        self._add_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        event_id = 0
        deadline = time.monotonic() + self.server.config.sse_max_connection_seconds
        try:
            while time.monotonic() < deadline:
                event_id += 1
                runs = self.server.coordinator.list_runs(limit=10)
                summaries = [_run_summary(run) for run in runs]
                readiness = self.server.coordinator.build_readiness()
                payload = {
                    "timestamp": _timestamp(),
                    "runs": summaries,
                    "readiness": readiness,
                    "active_runs": [
                        run for run in summaries if run["status"] not in {"completed", "failed", "cancelled"}
                    ],
                }
                self._write_sse(event_id=str(event_id), event_type="system", payload=payload)
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        except Exception:
            _LOG.exception("SSE system stream error")
            return

    def _write_sse(self, event_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
        self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._add_security_headers()
            self._add_cors_headers()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _send_file_response(self, path: Path, *, content_type: str, download_name: str) -> None:
        try:
            raw = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self._add_security_headers()
            self._add_cors_headers()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except FileNotFoundError:
            self._send_json({"error": "file not found"}, status=HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _request_body_within_limit(self) -> bool:
        limit = self.server.config.max_json_body_bytes
        if limit <= 0:
            return True
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return False
        try:
            length = int(raw_length)
        except ValueError:
            return False
        return length <= limit

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("invalid Content-Length header")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _add_security_headers(self) -> None:
        if not self.server.config.security_headers_enabled:
            return
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

    def _add_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Last-Event-ID, Authorization, X-Mesh-Operator, X-Mesh-Roles, X-Mesh-Role, X-Forwarded-User, X-Auth-Request-Email",
            )
            self.send_header("Access-Control-Max-Age", "86400")

    def _read_request_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return b""
        return self.rfile.read(length)


def build_server(config: RuntimeConfig | None = None) -> MeshControlPlaneServer:
    resolved = config or RuntimeConfig.from_env()
    server = MeshControlPlaneServer((resolved.server_host, resolved.server_port), resolved)
    return server


def serve_forever(config: RuntimeConfig | None = None, start_sidecar: bool = True) -> MeshControlPlaneServer:
    server = build_server(config)
    if start_sidecar:
        server.coordinator.ensure_sidecar()
    server.coordinator.start_watch_daemon()
    try:
        server.serve_forever()
    finally:
        server.coordinator.stop_watch_daemon()
        server.coordinator.sidecar.stop()
        server.server_close()
    return server


def start_server_in_thread(
    config: RuntimeConfig | None = None,
    start_sidecar: bool = True,
) -> tuple[MeshControlPlaneServer, threading.Thread]:
    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
