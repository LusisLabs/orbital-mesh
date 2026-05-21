from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, unquote, urlparse

from services.control_plane import RunCoordinator, TERMINAL_STAGES
from services.ingest.webhook_service import (
    SignatureMismatchError,
    UnknownWebhookSourceError,
    WebhookIngestError,
)
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.operator_identity import (
    CaptchaConfig,
    OAuthProviderConfig,
    OperatorIdentityStore,
    exchange_oauth_profile,
    oauth_authorize_url,
    write_operator_preferences_audit,
    write_settings_audit,
)
from shared.mesh_runtime.praxis import PraxisManagedRuntimeStore, build_praxis_product_dashboard
from shared.mesh_runtime.schema_validation import SchemaValidationError

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


def _safe_dashboard_call(fn, default: Any | None = None) -> Any:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - dashboard must degrade instead of masking auth.
        return default if default is not None else {"status": "unavailable", "error": str(exc)}


def _json_web_token_segment(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _livekit_access_token(
    *,
    api_key: str,
    api_secret: str,
    room: str,
    identity: str,
    name: str,
    ttl_seconds: int,
    can_publish: bool = True,
    can_publish_data: bool = True,
) -> str:
    now = int(time.time())
    header = _json_web_token_segment({"alg": "HS256", "typ": "JWT"})
    body = _json_web_token_segment(
        {
            "exp": now + ttl_seconds,
            "iss": api_key,
            "nbf": now - 5,
            "name": name,
            "sub": identity,
            "video": {
                "canPublish": can_publish,
                "canPublishData": can_publish_data,
                "canPublishSources": ["microphone"] if can_publish else [],
                "canSubscribe": True,
                "room": room,
                "roomJoin": True,
            },
        }
    )
    signing_input = f"{header}.{body}".encode("ascii")
    signature = hmac.new(api_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def _identifier_segment(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in cleaned.split("-") if part)[:80] or "operator"


def _agent_flow_bound_preview_payload(*, preview: dict[str, Any], context: dict[str, Any]) -> bytes:
    operator = context.get("operator") if isinstance(context.get("operator"), dict) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), dict) else {}
    payload = {
        "action": preview.get("action"),
        "confirmation_required": preview.get("confirmation_required"),
        "endpoint": preview.get("endpoint"),
        "issued_at": preview.get("issued_at"),
        "issued_operator_id": preview.get("issued_operator_id"),
        "issued_scope": preview.get("issued_scope"),
        "operator_id": operator.get("operator_id") or "unknown",
        "preview_id": preview.get("preview_id"),
        "proposed_resource": preview.get("proposed_resource"),
        "scope_id": scope.get("scope_id") or scope.get("id") or "solo",
        "side_effects_executed": preview.get("side_effects_executed"),
        "state_slice": preview.get("state_slice"),
        "target": preview.get("target"),
        "would_touch_state_slice": preview.get("would_touch_state_slice"),
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _agent_flow_preview_signature(*, preview: dict[str, Any], context: dict[str, Any]) -> str:
    session_token = str(context.get("session_token") or "")
    if not session_token:
        return ""
    digest = hmac.new(
        session_token.encode("utf-8"),
        _agent_flow_bound_preview_payload(preview=preview, context=context),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


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
        self.operator_identity = OperatorIdentityStore(config.operator_identity_path)
        self.praxis_store = PraxisManagedRuntimeStore(Path(config.state_directory) / "praxis" / "managed-dry-run-runtime.json")

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
        if path.startswith("/api/auth/") or path.startswith("/api/operator/"):
            self._handle_operator_get(parsed)
            return
        if path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "timestamp": _timestamp(),
                    "environment": self.server.config.environment,
                    "version": self.server.config.build_version,
                    "commit": self.server.config.build_commit,
                    "image_digest": self.server.config.build_image_digest or None,
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
        if path.startswith("/api/runs/") and path.endswith("/delivery-context"):
            run_id = _safe_segment(path, 2)
            if run_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self.server.coordinator.get_delivery_context(run_id)
            if payload is None:
                self._send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)
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
        if parsed.path.startswith("/api/auth/") or parsed.path.startswith("/api/operator/"):
            self._handle_operator_post(parsed.path, payload)
            return
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
                if self._send_session_value_error(exc):
                    return
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

    def _handle_operator_get(self, parsed) -> None:
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/auth/config":
            self._send_json(
                {
                    "auth_mode": self.server.config.auth_mode,
                    "signup_enabled": self.server.config.signup_enabled,
                    "password_auth_enabled": self.server.config.password_auth_enabled,
                    **self.server.operator_identity.public_auth_config(
                        captcha=self._captcha_config(),
                        google=self._oauth_config("google"),
                        github=self._oauth_config("github"),
                        invite_allowlist=self.server.config.auth_invite_allowlist,
                        invite_codes=self.server.config.auth_invite_codes,
                    ),
                }
            )
            return
        if path == "/api/auth/me":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            try:
                self._send_json(self.server.operator_identity.session_payload(token))
            except ValueError as exc:
                self._send_json(
                    {"error": str(exc)},
                    status=HTTPStatus.UNAUTHORIZED,
                    headers=[self._clear_session_cookie_header()],
                )
            return
        if path in {"/api/auth/oauth/google/start", "/api/auth/oauth/github/start"}:
            provider = "google" if "google" in path else "github"
            config = self._oauth_config(provider)
            if not config.configured:
                self._send_json({"error": f"{provider} oauth is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                return
            state = self.server.operator_identity.create_oauth_state(provider)["state"]
            self._send_json({"authorize_url": oauth_authorize_url(config, state)})
            return
        if path in {"/api/auth/oauth/google/callback", "/api/auth/oauth/github/callback"}:
            provider = "google" if "google" in path else "github"
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            if not code or not state:
                self._redirect(self._auth_callback_redirect({"auth_error": "missing_oauth_code"}))
                return
            try:
                self.server.operator_identity.consume_oauth_state(provider, state)
                profile = exchange_oauth_profile(self._oauth_config(provider), code)
                session = self.server.operator_identity.upsert_oauth_user(
                    provider=provider,
                    invite_allowlist=self.server.config.auth_invite_allowlist,
                    **profile,
                )
            except Exception as exc:
                _LOG.warning("%s oauth callback failed: %s", provider, exc)
                self._redirect(self._auth_callback_redirect({"auth_error": f"{provider}_oauth_failed"}))
                return
            self._redirect(self._auth_callback_redirect({"auth": "ok"}), headers=[self._session_cookie_header(session["token"])])
            return
        if path == "/api/operator/dashboard":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            team_id = (query.get("team_id") or [None])[0] or None
            try:
                dashboard = self.server.operator_identity.dashboard(
                    token,
                    team_id=team_id,
                    mesh={},
                )
                dashboard["mesh"] = self._mesh_dashboard_snapshot(
                    praxis_scope=self._praxis_scope_from_dashboard(dashboard),
                )
                self._send_json(
                    dashboard
                )
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/operator/praxis/runs":
            context = self._operator_product_context({"team_id": query.get("team_id", [None])[0]} if query.get("team_id") else None)
            if context is None:
                return
            self._send_json(self.server.praxis_store.list_records(scope=context["scope"]))
            return
        if path.startswith("/api/operator/praxis/runs/"):
            context = self._operator_product_context({"team_id": query.get("team_id", [None])[0]} if query.get("team_id") else None)
            if context is None:
                return
            request_id = _safe_segment(path, 4)
            if request_id is None:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            if path.endswith("/p10-proof"):
                try:
                    self._send_json(self.server.praxis_store.export_p10_proof_packet(request_id, scope=context["scope"]))
                except KeyError:
                    self._send_json({"error": "Praxis generation request not found"}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            record = self.server.praxis_store.get_record(request_id, scope=context["scope"])
            if record is None:
                self._send_json({"error": "Praxis generation request not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(record)
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_operator_post(self, path: str, payload: dict[str, Any]) -> None:
        if path.startswith("/api/operator/agent-flow/"):
            self._handle_operator_agent_flow_post(path, payload)
            return
        if path.startswith("/api/operator/praxis/"):
            self._handle_operator_praxis_post(path, payload)
            return
        if path == "/api/auth/signup":
            if not self.server.config.signup_enabled or not self.server.config.password_auth_enabled:
                self._send_json({"error": "password signup is disabled"}, status=HTTPStatus.FORBIDDEN)
                return
            try:
                session = self.server.operator_identity.create_user(
                    email=str(payload.get("email") or ""),
                    password=str(payload.get("password") or ""),
                    display_name=str(payload.get("display_name") or ""),
                    captcha_token=str(payload.get("captcha_token") or ""),
                    captcha=self._captcha_config(),
                    invite_code=str(payload.get("invite_code") or ""),
                    invite_allowlist=self.server.config.auth_invite_allowlist,
                    invite_codes=self.server.config.auth_invite_codes,
                    accepted_terms=payload.get("accepted_terms") is True,
                )
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(session["session"], status=HTTPStatus.CREATED, headers=[self._session_cookie_header(session["token"])])
            return
        if path == "/api/auth/login":
            if not self.server.config.password_auth_enabled:
                self._send_json({"error": "password login is disabled"}, status=HTTPStatus.FORBIDDEN)
                return
            try:
                session = self.server.operator_identity.login_user(
                    email=str(payload.get("email") or ""),
                    password=str(payload.get("password") or ""),
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
                return
            self._send_json(session["session"], headers=[self._session_cookie_header(session["token"])])
            return
        if path == "/api/auth/logout":
            token = self._session_token()
            if token:
                self.server.operator_identity.delete_session(token)
            self._send_json({"status": "logged_out"}, headers=[self._clear_session_cookie_header()])
            return
        if path == "/api/auth/team":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            try:
                response = self.server.operator_identity.create_team(
                    token,
                    name=str(payload.get("name") or ""),
                    display_name=str(payload.get("display_name") or ""),
                    members=payload.get("members") if isinstance(payload.get("members"), list) else [],
                )
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(response, status=HTTPStatus.CREATED)
            return
        if path == "/api/auth/team/update":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            try:
                response = self.server.operator_identity.update_team(
                    token,
                    team_id=str(payload.get("team_id")) if payload.get("team_id") else None,
                    name=str(payload.get("name") or ""),
                    display_name=(
                        "" if payload.get("display_name") is None else str(payload.get("display_name"))
                    ) if "display_name" in payload else None,
                )
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(response)
            return
        if path == "/api/auth/team/members":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            try:
                response = self.server.operator_identity.upsert_team_members(
                    token,
                    team_id=str(payload.get("team_id")) if payload.get("team_id") else None,
                    members=payload.get("members") if isinstance(payload.get("members"), list) else [],
                )
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(response)
            return
        if path == "/api/auth/switch-team":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            raw_team_id = payload.get("team_id")
            team_id = str(raw_team_id) if raw_team_id else None
            try:
                self._send_json(self.server.operator_identity.set_active_team(token, team_id))
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/operator/settings":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            team_id = str(payload.get("team_id")) if payload.get("team_id") else None
            updates = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
            reason = str(payload.get("reason") or "").strip()
            if not reason:
                self._send_json({"error": "settings update reason is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                response = self.server.operator_identity.update_settings(token, team_id=team_id, updates=updates)
                operator = self.server.operator_identity.operator_context_from_session(token) or {}
                scope = f"team:{team_id}" if team_id else f"user:{operator.get('user_id') or 'unknown'}"
                audit = write_settings_audit(
                    self.server.config.operator_identity_path,
                    operator_id=str(operator.get("operator_id") or "unknown"),
                    reason=reason,
                    scope=scope,
                    updates=updates,
                    git_commit=self.server.config.build_commit or "unknown",
                )
                response["audit"] = {
                    "recorded": True,
                    "state_slice": audit["record"]["state_slice"],
                    "scope": audit["record"]["scope"],
                    "fields": audit["record"]["fields"],
                }
                self._send_json(response)
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/operator/preferences":
            token = self._session_token()
            if not token:
                self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            team_id = str(payload.get("team_id")) if payload.get("team_id") else None
            updates = payload.get("operator_preferences") if isinstance(payload.get("operator_preferences"), dict) else {}
            reason = str(payload.get("reason") or "").strip()
            if not reason:
                self._send_json({"error": "operator preferences update reason is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                response = self.server.operator_identity.update_operator_preferences(token, team_id=team_id, updates=updates)
                operator = self.server.operator_identity.operator_context_from_session(token) or {}
                scope = f"team:{team_id}" if team_id else f"user:{operator.get('user_id') or 'unknown'}"
                audit = write_operator_preferences_audit(
                    self.server.config.operator_identity_path,
                    operator_id=str(operator.get("operator_id") or "unknown"),
                    reason=reason,
                    scope=scope,
                    updates=updates,
                    git_commit=self.server.config.build_commit or "unknown",
                )
                response["audit"] = {
                    "recorded": True,
                    "state_slice": audit["record"]["state_slice"],
                    "scope": audit["record"]["scope"],
                    "fields": audit["record"]["fields"],
                }
                self._send_json(response)
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
            except ValueError as exc:
                if self._send_session_value_error(exc):
                    return
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_operator_agent_flow_post(self, path: str, payload: dict[str, Any]) -> None:
        context = self._operator_product_context(payload)
        if context is None:
            return
        dashboard = context["dashboard"]
        if path == "/api/operator/agent-flow/chat":
            dashboard["mesh"] = self._mesh_dashboard_snapshot(praxis_scope=context["scope"])
            message = str(payload.get("message") or "").strip()
            if not message and not payload.get("attachments"):
                self._send_json({"error": "message is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(self._agent_flow_chat_response(message=message, context=context, dashboard=dashboard))
            return
        if path == "/api/operator/agent-flow/livekit-session":
            self._send_json(self._agent_flow_livekit_session(context=context, payload=payload))
            return
        if path == "/api/operator/agent-flow/confirm-preview":
            preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else {}
            preview_id = str(payload.get("preview_id") or preview.get("preview_id") or "").strip()
            reason = str(payload.get("reason") or "").strip()
            if not preview_id:
                self._send_json({"error": "preview_id is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not reason:
                self._send_json({"error": "confirmation reason is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                validated_preview = self._validated_agent_flow_preview(preview=preview, preview_id=preview_id, context=context)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(self._agent_flow_confirmation(preview=validated_preview, preview_id=preview_id, reason=reason, context=context))
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _agent_flow_chat_response(self, *, message: str, context: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
        mesh = dashboard.get("mesh") if isinstance(dashboard.get("mesh"), dict) else {}
        runs = mesh.get("runs", {}).get("runs") if isinstance(mesh.get("runs"), dict) else []
        approvals = mesh.get("approvals", {}).get("items") if isinstance(mesh.get("approvals"), dict) else []
        runs_list = runs if isinstance(runs, list) else []
        approvals_list = approvals if isinstance(approvals, list) else []
        readiness = mesh.get("readiness") if isinstance(mesh.get("readiness"), dict) else {}
        readiness_status = str(readiness.get("status") or "unknown")
        evidence = self._agent_flow_evidence(mesh)
        preview = self._signed_agent_flow_preview(
            self._agent_flow_mutation_preview(message=message, context=context, dashboard=dashboard),
            context=context,
        )
        state_slices = [
            "mesh.agent_flow.chat_response.v1",
            "mesh.operator-dashboard.read-model.v1",
            "mesh.runs.runs",
            "mesh.approvals.approval_queue",
            "mesh.agent_flow.mutation_preview.v1",
        ]
        answer = (
            f"State slices: {', '.join(state_slices)}. "
            f"Readiness is {readiness_status}; Mesh reports {len(runs_list)} run(s), "
            f"{len(approvals_list)} approval item(s), and {len(evidence)} evidence signal(s). "
            "I prepared a draft preview only. side_effects_executed=false until a Mesh-owned route receives explicit operator confirmation."
        )
        return {
            "schema_version": "mesh.agent_flow.chat_response.v1",
            "state_slice": "mesh.agent_flow.chat_response.v1",
            "agent": {
                "id": "harper-696",
                "name": self.server.config.livekit_agent_name or "Harper-696",
                "source": "Harper-696/src/agent.py",
                "authority": "operator_assistant",
            },
            "answer": answer,
            "state_slices": state_slices,
            "evidence": evidence,
            "lifecycle": {
                "state_slice": "mesh.agent_flow.lifecycle.v1",
                "tasks": self._agent_flow_lifecycle_tasks(mesh=mesh, preview=preview),
            },
            "mutation_preview": preview,
            "authority_boundary": dashboard.get("authority_boundary"),
            "created_at": _timestamp(),
        }

    def _agent_flow_livekit_session(self, *, context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        config = self.server.config
        dashboard = context.get("dashboard") if isinstance(context.get("dashboard"), dict) else {}
        dashboard_scope = dashboard.get("scope") if isinstance(dashboard.get("scope"), dict) else {}
        dashboard_team = dashboard_scope.get("team") if isinstance(dashboard_scope.get("team"), dict) else None
        operator = context.get("operator") if isinstance(context.get("operator"), dict) else {}
        scope = context.get("scope") if isinstance(context.get("scope"), dict) else {}
        scope_id = str(scope.get("scope_id") or scope.get("id") or "solo")
        if scope.get("kind") == "team" and dashboard_team:
            roles = set(dashboard_team.get("roles") if isinstance(dashboard_team.get("roles"), list) else [])
        else:
            roles = set(operator.get("roles") if isinstance(operator.get("roles"), list) else [])
        can_publish = bool(roles & {"launcher", "approver", "admin"})
        room_prefix = f"harper-696-{_identifier_segment(scope_id)}"
        room_suffix = _identifier_segment(str(payload.get("room") or ""))
        room = f"{room_prefix}-{room_suffix}" if room_suffix and room_suffix != "operator" else room_prefix
        identity_root = _identifier_segment(str(operator.get("operator_id") or operator.get("user_id") or scope_id))
        identity_nonce = hashlib.sha256(f"{time.time_ns()}:{identity_root}:{scope_id}".encode("utf-8")).hexdigest()[:10]
        identity = f"operator-{identity_root}-{identity_nonce}"
        configured = bool(config.livekit_url and config.livekit_api_key and config.livekit_api_secret)
        response: dict[str, Any] = {
            "schema_version": "mesh.agent_flow.livekit_session.v1",
            "state_slice": "mesh.agent_flow.livekit_session.v1",
            "agent": {
                "id": "harper-696",
                "name": config.livekit_agent_name or "Harper-696",
                "source": "Harper-696/src/agent.py",
            },
            "status": "ready" if configured and can_publish else "permission_required" if configured else "unconfigured",
            "livekit_url": config.livekit_url if configured else "",
            "room": room,
            "participant_identity": identity,
            "token": "",
            "token_expires_at": None,
            "required_env": ["MESH_LIVEKIT_URL", "MESH_LIVEKIT_API_KEY", "MESH_LIVEKIT_API_SECRET"],
            "side_effects_executed": False,
        }
        if configured and can_publish:
            ttl = int(config.livekit_token_ttl_seconds)
            response["token"] = _livekit_access_token(
                api_key=config.livekit_api_key,
                api_secret=config.livekit_api_secret,
                room=room,
                identity=identity,
                name=str(operator.get("operator_id") or identity),
                ttl_seconds=ttl,
                can_publish=True,
                can_publish_data=False,
            )
            response["token_expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl))
        return response

    def _agent_flow_confirmation(
        self,
        *,
        preview: dict[str, Any],
        preview_id: str,
        reason: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        operator = context.get("operator") if isinstance(context.get("operator"), dict) else {}
        return {
            "schema_version": "mesh.agent_flow.confirmation.v1",
            "state_slice": "mesh.agent_flow.mutation_preview.v1",
            "preview_id": preview_id,
            "status": "confirmation_recorded",
            "confirmed_by": operator.get("operator_id") or "unknown",
            "reason": reason,
            "proposed_resource": preview.get("proposed_resource") or "RunSession",
            "would_touch_state_slice": preview.get("would_touch_state_slice") or "mesh.run_admission.v1",
            "routed_to": preview.get("endpoint") or "/api/runs",
            "side_effects_executed": False,
            "next_step": "Use the named Mesh-owned endpoint to execute after final operator review.",
            "created_at": _timestamp(),
        }

    def _validated_agent_flow_preview(self, *, preview: dict[str, Any], preview_id: str, context: dict[str, Any]) -> dict[str, Any]:
        if preview.get("schema_version") != "mesh.agent_flow.mutation_preview.v1":
            raise ValueError("unsupported preview schema_version")
        if preview.get("state_slice") != "mesh.agent_flow.mutation_preview.v1":
            raise ValueError("unsupported preview state_slice")
        if preview.get("preview_id") != preview_id:
            raise ValueError("preview_id mismatch")
        if preview.get("confirmation_required") is not True:
            raise ValueError("preview must require confirmation")
        if preview.get("side_effects_executed") is not False:
            raise ValueError("preview must not have executed side effects")
        if preview.get("status") != "draft_requires_confirmation":
            raise ValueError("preview must be a draft requiring confirmation")
        operator = context.get("operator") if isinstance(context.get("operator"), dict) else {}
        scope = context.get("scope") if isinstance(context.get("scope"), dict) else {}
        expected_scope = str(scope.get("scope_id") or scope.get("id") or "solo")
        expected_operator = str(operator.get("operator_id") or "unknown")
        if preview.get("issued_scope") != expected_scope:
            raise ValueError("preview scope mismatch")
        if preview.get("issued_operator_id") != expected_operator:
            raise ValueError("preview operator mismatch")
        proof = preview.get("proof") if isinstance(preview.get("proof"), dict) else {}
        if proof.get("algorithm") != "HMAC-SHA256":
            raise ValueError("unsupported preview proof")
        if proof.get("bound_state_slice") != "mesh.agent_flow.mutation_preview.v1":
            raise ValueError("preview proof state slice mismatch")
        expected_signature = _agent_flow_preview_signature(preview=preview, context=context)
        if not expected_signature or not hmac.compare_digest(str(proof.get("signature") or ""), expected_signature):
            raise ValueError("preview signature mismatch")
        resource = str(preview.get("proposed_resource") or "")
        endpoint = str(preview.get("endpoint") or "")
        state_slice = str(preview.get("would_touch_state_slice") or "")
        if resource == "RunSession" and endpoint == "/api/runs" and state_slice == "mesh.run_admission.v1":
            return preview
        if (
            resource == "SteeringCommand"
            and endpoint.startswith("/api/runs/")
            and endpoint.endswith("/steer")
            and state_slice == "mesh.run_steering.v1"
        ):
            return preview
        raise ValueError("preview route is not an allowed Agent Flow draft")

    def _signed_agent_flow_preview(self, preview: dict[str, Any], *, context: dict[str, Any]) -> dict[str, Any]:
        operator = context.get("operator") if isinstance(context.get("operator"), dict) else {}
        scope = context.get("scope") if isinstance(context.get("scope"), dict) else {}
        signed_preview = {
            **preview,
            "issued_scope": str(scope.get("scope_id") or scope.get("id") or "solo"),
            "issued_operator_id": str(operator.get("operator_id") or "unknown"),
            "issued_at": _timestamp(),
        }
        signed_preview["proof"] = {
            "algorithm": "HMAC-SHA256",
            "bound_state_slice": "mesh.agent_flow.mutation_preview.v1",
            "signature": _agent_flow_preview_signature(preview=signed_preview, context=context),
        }
        return signed_preview

    def _agent_flow_mutation_preview(self, *, message: str, context: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
        mesh = dashboard.get("mesh") if isinstance(dashboard.get("mesh"), dict) else {}
        runs = mesh.get("runs", {}).get("runs") if isinstance(mesh.get("runs"), dict) else []
        runs_list = runs if isinstance(runs, list) else []
        lower = message.lower()
        wants_steering = any(keyword in lower for keyword in ("approve", "resume", "cancel", "override", "steer"))
        active_run = next((run for run in runs_list if isinstance(run, dict) and run.get("run_id")), None)
        scope = context.get("scope") if isinstance(context.get("scope"), dict) else {}
        scope_id = str(scope.get("scope_id") or scope.get("id") or "solo")
        preview_basis = f"{scope_id}:{message[:80]}:{active_run.get('run_id') if isinstance(active_run, dict) else 'new-run'}"
        preview_id = hashlib.sha256(preview_basis.encode("utf-8")).hexdigest()[:16]
        if wants_steering and active_run:
            command = "approve" if "approve" in lower else "resume" if "resume" in lower else "cancel" if "cancel" in lower else "explain_blockers"
            return {
                "schema_version": "mesh.agent_flow.mutation_preview.v1",
                "state_slice": "mesh.agent_flow.mutation_preview.v1",
                "preview_id": f"agent-flow-{preview_id}",
                "status": "draft_requires_confirmation",
                "proposed_resource": "SteeringCommand",
                "action": command,
                "target": {"run_id": active_run.get("run_id")},
                "endpoint": f"/api/runs/{active_run.get('run_id')}/steer",
                "would_touch_state_slice": "mesh.run_steering.v1",
                "confirmation_required": True,
                "side_effects_executed": False,
            }
        scenario = str(dashboard.get("settings", {}).get("default_run_scenario") or "reth_peer_starvation")
        return {
            "schema_version": "mesh.agent_flow.mutation_preview.v1",
            "state_slice": "mesh.agent_flow.mutation_preview.v1",
            "preview_id": f"agent-flow-{preview_id}",
            "status": "draft_requires_confirmation",
            "proposed_resource": "RunSession",
            "action": "launch_draft",
            "target": {"scenario_key": scenario},
            "endpoint": "/api/runs",
            "would_touch_state_slice": "mesh.run_admission.v1",
            "confirmation_required": True,
            "side_effects_executed": False,
        }

    def _agent_flow_evidence(self, mesh: dict[str, Any]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        pilot = mesh.get("pilot_go_no_go") if isinstance(mesh.get("pilot_go_no_go"), dict) else {}
        missing = pilot.get("missing_evidence") if isinstance(pilot.get("missing_evidence"), list) else []
        for index, item in enumerate(missing[:4]):
            label = item.get("label") if isinstance(item, dict) else item
            evidence.append(
                {
                    "id": f"missing-proof-{index + 1}",
                    "kind": "missing_evidence",
                    "state_slice": "mesh.pilot_go_no_go.missing_evidence",
                    "summary": str(label or "Missing proof"),
                }
            )
        runs = mesh.get("runs", {}).get("runs") if isinstance(mesh.get("runs"), dict) else []
        for run in (runs if isinstance(runs, list) else [])[:2]:
            if not isinstance(run, dict):
                continue
            evidence.append(
                {
                    "id": str(run.get("run_id") or "run"),
                    "kind": "run",
                    "state_slice": "mesh.runs.runs",
                    "summary": f"{run.get('scenario_key') or 'run'} is {run.get('status') or 'unknown'}",
                }
            )
        return evidence

    def _agent_flow_lifecycle_tasks(self, *, mesh: dict[str, Any], preview: dict[str, Any]) -> list[dict[str, Any]]:
        livekit_ready = bool(self.server.config.livekit_url and self.server.config.livekit_api_key and self.server.config.livekit_api_secret)
        runs = mesh.get("runs", {}).get("runs") if isinstance(mesh.get("runs"), dict) else []
        approvals = mesh.get("approvals", {}).get("items") if isinstance(mesh.get("approvals"), dict) else []
        evidence = self._agent_flow_evidence(mesh)
        readiness = mesh.get("readiness") if isinstance(mesh.get("readiness"), dict) else {}
        read_status = "completed" if readiness.get("status") and readiness.get("status") != "unavailable" else "need-help"
        return [
            {
                "id": "1",
                "title": "Harper-696 voice session boundary",
                "description": "Mint or explain the LiveKit browser room for the Harper operator assistant.",
                "status": "completed" if livekit_ready else "need-help",
                "priority": "high",
                "level": 0,
                "dependencies": [],
                "subtasks": [
                    {
                        "id": "1.1",
                        "title": "Bind assistant identity",
                        "description": "Agent name is Harper-696 and authority remains operator assistance.",
                        "status": "completed",
                        "priority": "high",
                        "tools": ["mesh.agent_flow.livekit_session.v1", "Harper-696/src/agent.py"],
                    },
                    {
                        "id": "1.2",
                        "title": "Mint browser token",
                        "description": "Requires LiveKit URL, API key, and API secret; secrets never enter the response.",
                        "status": "completed" if livekit_ready else "need-help",
                        "priority": "high",
                        "tools": ["MESH_LIVEKIT_URL", "MESH_LIVEKIT_API_KEY", "MESH_LIVEKIT_API_SECRET"],
                    },
                ],
            },
            {
                "id": "2",
                "title": "Intent to Mesh read model",
                "description": "Convert the prompt into read-only Mesh inspection before any action.",
                "status": read_status,
                "priority": "high",
                "level": 0,
                "dependencies": ["1"],
                "subtasks": [
                    {
                        "id": "2.1",
                        "title": "Load dashboard context",
                        "description": "Readiness, approvals, proof gaps, and run summaries come from /api/operator/dashboard.",
                        "status": read_status,
                        "priority": "high",
                        "tools": ["mesh.operator-dashboard.read-model.v1", "/api/operator/dashboard"],
                    },
                    {
                        "id": "2.2",
                        "title": "Inspect run and approval counts",
                        "description": f"Mesh returned {len(runs if isinstance(runs, list) else [])} run(s) and {len(approvals if isinstance(approvals, list) else [])} approval item(s).",
                        "status": "completed",
                        "priority": "medium",
                        "tools": ["mesh.runs.runs", "mesh.approvals.approval_queue"],
                    },
                ],
            },
            {
                "id": "3",
                "title": "Mutation preview and confirmation",
                "description": "Draft the action and state slice before any mutating Mesh route can be used.",
                "status": "in-progress",
                "priority": "high",
                "level": 0,
                "dependencies": ["2"],
                "subtasks": [
                    {
                        "id": "3.1",
                        "title": "Build state-slice declaration",
                        "description": f"Preview targets {preview.get('would_touch_state_slice') or 'mesh.run_admission.v1'}.",
                        "status": "completed",
                        "priority": "high",
                        "tools": ["mesh.agent_flow.mutation_preview.v1", str(preview.get("proposed_resource") or "RunSession")],
                    },
                    {
                        "id": "3.2",
                        "title": "Require explicit confirmation",
                        "description": "The preview is draft-only; side effects remain false until Mesh receives an approved route call.",
                        "status": "in-progress",
                        "priority": "high",
                        "tools": ["operator confirmation", "Mesh-owned endpoint"],
                    },
                ],
            },
            {
                "id": "4",
                "title": "Evidence and lifecycle canvas",
                "description": "Expose evidence signals and unresolved proof gaps as lifecycle detail.",
                "status": "need-help" if evidence else "completed",
                "priority": "medium",
                "level": 1,
                "dependencies": ["2", "3"],
                "subtasks": [
                    {
                        "id": "4.1",
                        "title": "Surface proof gaps",
                        "description": f"{len(evidence)} evidence signal(s) are attached to this response.",
                        "status": "need-help" if evidence else "completed",
                        "priority": "high",
                        "tools": ["mesh.pilot_go_no_go.missing_evidence", "mesh.runs.runs"],
                    },
                    {
                        "id": "4.2",
                        "title": "Preserve read-only fallback",
                        "description": "Agent Flow remains inspectable even when live voice or actuation is unavailable.",
                        "status": "completed",
                        "priority": "medium",
                        "tools": ["mesh.agent_flow.chat_response.v1"],
                    },
                ],
            },
        ]

    def _handle_operator_praxis_post(self, path: str, payload: dict[str, Any]) -> None:
        context = self._operator_product_context(payload)
        if context is None:
            return
        try:
            if path == "/api/operator/praxis/generation-requests":
                record = self.server.praxis_store.create_generation_request(
                    payload,
                    operator=context["operator"],
                    scope=context["scope"],
                )
                self._send_json(record, status=HTTPStatus.CREATED)
                return
            prefix = "/api/operator/praxis/generation-requests/"
            if not path.startswith(prefix):
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            parts = [part for part in path[len(prefix):].split("/") if part]
            if len(parts) < 2:
                self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            request_id = parts[0]
            action = "/".join(parts[1:])
            if action == "akto-evidence":
                self._send_json(
                    self.server.praxis_store.import_akto_evidence(
                        request_id,
                        payload,
                        operator=context["operator"],
                        scope=context["scope"],
                    )
                )
                return
            if action == "certification-binding":
                self._send_json(
                    self.server.praxis_store.build_certification_binding(
                        request_id,
                        payload,
                        operator=context["operator"],
                        scope=context["scope"],
                    )
                )
                return
            if action == "dry-run/start":
                self._send_json(
                    self.server.praxis_store.start_dry_run_endpoint(
                        request_id,
                        payload,
                        operator=context["operator"],
                        scope=context["scope"],
                    )
                )
                return
            if action == "dry-run/call":
                result = self.server.praxis_store.call_dry_run_tool(
                    request_id,
                    payload,
                    operator=context["operator"],
                    scope=context["scope"],
                )
                status = HTTPStatus.FORBIDDEN if result.get("status") == "denied" else HTTPStatus.OK
                self._send_json(result, status=status)
                return
            if action == "mcp":
                self._send_json(
                    self.server.praxis_store.mcp_json_rpc(
                        request_id,
                        payload,
                        operator=context["operator"],
                        scope=context["scope"],
                    )
                )
                return
            if action == "revoke":
                self._send_json(
                    self.server.praxis_store.revoke_generated_connector(
                        request_id,
                        payload,
                        operator=context["operator"],
                        scope=context["scope"],
                    )
                )
                return
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except KeyError:
            self._send_json({"error": "Praxis generation request not found"}, status=HTTPStatus.NOT_FOUND)
        except SchemaValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            if self._send_session_value_error(exc):
                return
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _operator_product_context(self, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        token = self._session_token()
        if not token:
            self._send_json({"error": "session required"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        team_id = None
        if isinstance(payload, dict) and payload.get("team_id"):
            team_id = str(payload.get("team_id"))
        try:
            dashboard = self.server.operator_identity.dashboard(token, team_id=team_id, mesh={})
            operator = self.server.operator_identity.operator_context_from_session(token) or {}
            scope = self._praxis_scope_from_dashboard(dashboard)
            if scope["kind"] == "team":
                operator["team_id"] = scope["id"]
            return {"dashboard": dashboard, "operator": operator, "scope": scope, "session_token": token}
        except PermissionError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
        except ValueError as exc:
            if self._send_session_value_error(exc):
                return None
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        return None

    def _praxis_scope_from_dashboard(self, dashboard: dict[str, Any]) -> dict[str, str]:
        scope = dashboard.get("scope") if isinstance(dashboard.get("scope"), dict) else {}
        team = scope.get("team") if isinstance(scope.get("team"), dict) else None
        if scope.get("kind") == "team" and team:
            team_id = str(team["id"])
            return {
                "kind": "team",
                "id": team_id,
                "scope_id": f"team:{team_id}",
                "name": str(team.get("name") or ""),
            }
        session = dashboard.get("session") if isinstance(dashboard.get("session"), dict) else {}
        user = session.get("user") if isinstance(session.get("user"), dict) else {}
        user_id = str(user.get("id") or "unknown")
        return {
            "kind": "user",
            "id": user_id,
            "scope_id": f"user:{user_id}",
            "email": str(user.get("email") or ""),
        }

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

    def _captcha_config(self) -> CaptchaConfig:
        return CaptchaConfig(
            provider=self.server.config.captcha_provider,
            site_key=self.server.config.captcha_site_key,
            secret=self.server.config.captcha_secret_key,
            dev_bypass_enabled=self.server.config.captcha_dev_bypass_enabled,
        )

    def _oauth_config(self, provider: str) -> OAuthProviderConfig:
        if provider == "google":
            return OAuthProviderConfig(
                provider="google",
                client_id=self.server.config.google_oauth_client_id,
                client_secret=self.server.config.google_oauth_client_secret,
                redirect_uri=self.server.config.google_oauth_redirect_url,
            )
        if provider == "github":
            return OAuthProviderConfig(
                provider="github",
                client_id=self.server.config.github_oauth_client_id,
                client_secret=self.server.config.github_oauth_client_secret,
                redirect_uri=self.server.config.github_oauth_redirect_url,
            )
        raise ValueError("unsupported oauth provider")

    def _session_token(self) -> str:
        cookie_header = self.headers.get("Cookie", "")
        cookie_name = self.server.config.session_cookie_name
        for raw_cookie in cookie_header.split(";"):
            name, _, value = raw_cookie.strip().partition("=")
            if name == cookie_name:
                return unquote(value)
        bearer = self.headers.get("Authorization", "")
        if bearer.startswith("Bearer "):
            return bearer[len("Bearer "):].strip()
        return ""

    def _session_cookie_header(self, token: str) -> tuple[str, str]:
        secure = "Secure; " if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
        return (
            "Set-Cookie",
            f"{self.server.config.session_cookie_name}={token}; Path=/; HttpOnly; {secure}SameSite=Lax; Max-Age=1209600",
        )

    def _send_session_value_error(self, exc: ValueError) -> bool:
        message = str(exc)
        if message not in {"session required", "session expired"}:
            return False
        headers = [self._clear_session_cookie_header()] if message == "session expired" else []
        self._send_json({"error": message}, status=HTTPStatus.UNAUTHORIZED, headers=headers)
        return True

    def _clear_session_cookie_header(self) -> tuple[str, str]:
        return (
            "Set-Cookie",
            (
                f"{self.server.config.session_cookie_name}=; Path=/; HttpOnly; SameSite=Lax; "
                "Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0"
            ),
        )

    def _mesh_dashboard_snapshot(self, *, praxis_scope: dict[str, str] | None = None) -> dict[str, Any]:
        coordinator = self.server.coordinator
        return {
            "health": {
                "status": "ok",
                "environment": self.server.config.environment,
                "version": self.server.config.build_version,
                "commit": self.server.config.build_commit,
                "image_digest": self.server.config.build_image_digest or None,
            },
            "read_model": {
                "source": "/api/operator/dashboard",
                "authority": "read_only",
                "degraded_reason": "Nested sections return status=unavailable with an error when a Mesh read-model call fails.",
            },
            "agent_flow": {
                "schema_version": "mesh.agent_flow.dashboard.v1",
                "state_slice": "mesh.agent_flow.dashboard.v1",
                "status": "ready",
                "agent": self.server.config.livekit_agent_name or "Harper-696",
                "source": "Harper-696/src/agent.py",
                "chat_endpoint": "/api/operator/agent-flow/chat",
                "livekit_endpoint": "/api/operator/agent-flow/livekit-session",
                "confirmation_endpoint": "/api/operator/agent-flow/confirm-preview",
                "livekit_configured": bool(
                    self.server.config.livekit_url
                    and self.server.config.livekit_api_key
                    and self.server.config.livekit_api_secret
                ),
                "authority": "draft_only; Mesh-owned endpoints retain mutation authority",
            },
            "readiness": _safe_dashboard_call(coordinator.build_readiness),
            "connectors": _safe_dashboard_call(coordinator.build_connector_certification),
            "approvals": _safe_dashboard_call(coordinator.build_approval_queue),
            "kill_switch": _safe_dashboard_call(coordinator.kill_switch_status),
            "pilot_go_no_go": _safe_dashboard_call(coordinator.generate_pilot_go_no_go),
            "praxis": _safe_dashboard_call(
                lambda: self.server.praxis_store.build_product_dashboard(scope=praxis_scope),
                default=build_praxis_product_dashboard(),
            ),
            "trust_ladder": {"entries": _safe_dashboard_call(coordinator.trust_ladder_list, default=[])},
            "watchers": _safe_dashboard_call(coordinator.watchers_status),
            "graph": _safe_dashboard_call(coordinator.graph_status),
            "runs": {"runs": _safe_dashboard_call(coordinator.list_run_summaries, default=[])},
            "memory": {
                "active": _safe_dashboard_call(coordinator.get_active_memory),
                "graph": _safe_dashboard_call(coordinator.get_memory_graph),
            },
        }

    def _redirect(self, location: str, headers: list[tuple[str, str]] | None = None) -> None:
        self.send_response(HTTPStatus.FOUND)
        self._add_security_headers()
        self._add_cors_headers()
        for name, value in headers or []:
            self.send_header(name, value)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _auth_callback_redirect(self, params: dict[str, str]) -> str:
        query = urlencode(params)
        target = self.server.config.auth_product_redirect_url.strip()
        if target and self._auth_redirect_allowed(target):
            separator = "&" if "?" in target else "?"
            return f"{target}{separator}{query}"
        return f"/?{query}"

    def _auth_redirect_allowed(self, target: str) -> bool:
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        if parsed.username or parsed.password:
            return False
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"}:
            return True
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin in set(self.server.config.auth_allowed_origins)

    def _operator_context(self) -> dict[str, Any]:
        if self.server.config.auth_mode == "app_session":
            session_operator = self.server.operator_identity.operator_context_from_session(self._session_token())
            if session_operator is not None:
                if self.client_address:
                    session_operator["source_ip"] = self.client_address[0]
                return session_operator
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
        identity_required = self.server.config.operator_identity_required or self.server.config.auth_mode == "app_session"
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
                    "detail": "Run `pnpm --dir meshapp/frontend run build` in orbital-mesh before opening the browser.",
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

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._add_security_headers()
            self._add_cors_headers()
            for name, value in headers or []:
                self.send_header(name, value)
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
            allowed = set(self.server.config.auth_allowed_origins)
            if allowed and origin not in allowed:
                return
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Last-Event-ID, Authorization, X-Mesh-Operator, X-Mesh-Roles, X-Mesh-Role, X-Forwarded-User, X-Auth-Request-Email",
            )
            self.send_header("Access-Control-Allow-Credentials", "true")
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
