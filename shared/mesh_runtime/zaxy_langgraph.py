from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .control_plane_models import RunEvent


ZAXY_EVENTLOOM_RECORD_VERSION = "mesh.zaxy_eventloom_mirror.v1"
ZAXY_CHECKOUT_VERSION = "mesh.zaxy_memory_checkout.v1"
LANGGRAPH_WORKFLOW_RECORD_VERSION = "mesh.langgraph_proposal_workflow.v1"
_SECRET_MARKERS = ("secret", "token", "password", "api_key", "apikey", "authorization", "credential")


def mirror_run_event_to_zaxy(config: Any, event: RunEvent) -> dict[str, Any]:
    """Mirror a Mesh run event into the optional Zaxy sidecar.

    Mesh persistence has already succeeded when callers invoke this function.
    Every failure is returned as degraded metadata so Zaxy cannot block the
    control plane.
    """

    record = build_zaxy_eventloom_record(config, event)
    if not bool(getattr(config, "zaxy_enabled", False)):
        return {**record, "delivery": {"status": "disabled"}}

    delivery: dict[str, Any] = {"status": "recorded"}
    outbox_path = str(getattr(config, "zaxy_eventloom_outbox_path", "") or "").strip()
    if outbox_path:
        try:
            path = Path(outbox_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            delivery["outbox_path"] = str(path)
        except OSError as exc:
            delivery = {"status": "degraded", "reason": f"outbox_write_failed: {exc}"}

    endpoint = str(getattr(config, "zaxy_eventloom_url", "") or "").strip()
    if endpoint:
        http_delivery = _post_json(
            endpoint,
            record,
            timeout_seconds=float(getattr(config, "zaxy_timeout_seconds", 2.0) or 2.0),
        )
        if http_delivery["status"] != "recorded":
            delivery = {"status": "degraded", "outbox": delivery, "http": http_delivery}
        else:
            delivery["http"] = http_delivery

    return {**record, "delivery": delivery}


def build_zaxy_eventloom_record(config: Any, event: RunEvent) -> dict[str, Any]:
    payload = _sanitize_payload(event.payload)
    if not bool(getattr(config, "zaxy_packet_capture_enabled", False)):
        payload = {
            "packet_capture": "disabled",
            "summary": _sanitize_payload(event.summary or {}),
        }
    record = {
        "version": ZAXY_EVENTLOOM_RECORD_VERSION,
        "namespace": str(getattr(config, "zaxy_namespace", "mesh") or "mesh"),
        "tenant_id": str(getattr(config, "zaxy_tenant_id", "local") or "local"),
        "scope": _event_scope(config, event),
        "mesh": {
            "run_id": event.run_id,
            "event_id": event.event_id,
            "sequence": event.sequence,
            "stage": event.stage,
            "event_type": event.event_type,
            "recorded_at": event.recorded_at,
            "artifact_key": event.artifact_key,
            "integration_name": event.integration_name,
            "status": event.status,
            "merkle_leaf_hash": event.merkle_leaf_hash,
        },
        "source_refs": _source_refs(event),
        "citations": _citations(event),
        "payload": payload,
        "authority": {
            "mesh_control_plane_authoritative": True,
            "zaxy_sidecar_authoritative": False,
            "production_actuation_allowed": False,
        },
    }
    record["record_hash"] = f"sha256:{_canonical_sha256(record)}"
    return record


def checkout_zaxy_memory(config: Any, request: dict[str, Any]) -> dict[str, Any]:
    if not bool(getattr(config, "zaxy_enabled", False)):
        return _checkout_status("disabled", candidates=[])
    endpoint = str(getattr(config, "zaxy_mcp_url", "") or "").strip()
    if not endpoint:
        return _checkout_status("unavailable", reason="MESH_ZAXY_MCP_URL is not configured", candidates=[])
    limit = max(1, min(int(request.get("limit", 5) or 5), 25))
    body = {
        "version": ZAXY_CHECKOUT_VERSION,
        "query": str(request.get("query", "") or ""),
        "scope": dict(request.get("scope") or {}),
        "limit": limit,
    }
    parsed = urlparse(endpoint)
    try:
        if parsed.scheme in {"", "file"}:
            path = Path(parsed.path if parsed.scheme == "file" else endpoint)
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = _post_json(
                endpoint,
                body,
                timeout_seconds=float(getattr(config, "zaxy_timeout_seconds", 2.0) or 2.0),
                return_payload=True,
            )
            if payload.get("status") == "degraded":
                return _checkout_status("degraded", reason=str(payload.get("reason")), candidates=[])
    except (OSError, ValueError, URLError) as exc:
        return _checkout_status("degraded", reason=str(exc), candidates=[])
    candidates = _checkout_candidates(payload, scope=body["scope"], limit=limit)
    return _checkout_status("recorded", candidates=candidates)


def zaxy_readiness(config: Any) -> dict[str, Any]:
    enabled = bool(getattr(config, "zaxy_enabled", False))
    eventloom_url = str(getattr(config, "zaxy_eventloom_url", "") or "").strip()
    mcp_url = str(getattr(config, "zaxy_mcp_url", "") or "").strip()
    outbox_path = str(getattr(config, "zaxy_eventloom_outbox_path", "") or "").strip()
    neo4j_enabled = bool(getattr(config, "zaxy_neo4j_projection_enabled", False))
    ready = enabled and bool(eventloom_url or outbox_path or mcp_url)
    warnings = []
    if enabled and not bool(eventloom_url or outbox_path):
        warnings.append("zaxy_eventloom_sink_missing")
    if enabled and not mcp_url:
        warnings.append("zaxy_mcp_checkout_missing")
    return {
        "ready": ready,
        "detail": "enabled optional memory sidecar" if ready else ("disabled" if not enabled else "enabled but no sink configured"),
        "eventloom_url_configured": bool(eventloom_url),
        "eventloom_outbox_path": outbox_path or None,
        "mcp_url_configured": bool(mcp_url),
        "neo4j_projection_enabled": neo4j_enabled,
        "packet_capture_enabled": bool(getattr(config, "zaxy_packet_capture_enabled", False)),
        "warnings": warnings,
    }


def langgraph_readiness(config: Any) -> dict[str, Any]:
    enabled = bool(getattr(config, "langgraph_enabled", False)) or getattr(config, "agent_fabric_mode", "") == "langgraph"
    checkpointer = str(getattr(config, "langgraph_checkpointer_url", "") or "").strip()
    try:
        import langgraph  # noqa: F401

        package_available = True
    except ImportError:
        package_available = False
    ready = enabled and package_available and bool(checkpointer)
    warnings = []
    if enabled and not package_available:
        warnings.append("langgraph_dependency_missing")
    if enabled and not checkpointer:
        warnings.append("langgraph_checkpointer_missing")
    return {
        "ready": ready,
        "detail": (
            "enabled with checkpointing"
            if ready
            else ("disabled" if not enabled else "enabled but checkpointing is not ready")
        ),
        "package_available": package_available,
        "checkpointer_configured": bool(checkpointer),
        "warnings": warnings,
    }


def langgraph_workflow_record(config: Any, *, task_id: str, run_id: str, agent: str, checkpoint_id: str) -> dict[str, Any]:
    record = {
        "version": LANGGRAPH_WORKFLOW_RECORD_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "agent": agent,
        "checkpoint_id": checkpoint_id,
        "checkpointer_url_configured": bool(str(getattr(config, "langgraph_checkpointer_url", "") or "").strip()),
        "authority": {
            "mesh_control_plane_authoritative": True,
            "langgraph_workflow_authoritative": False,
            "production_actuation_allowed": False,
        },
    }
    record["record_hash"] = f"sha256:{_canonical_sha256(record)}"
    return record


def _checkout_status(status: str, *, candidates: list[dict[str, Any]], reason: str | None = None) -> dict[str, Any]:
    payload = {
        "version": ZAXY_CHECKOUT_VERSION,
        "status": status,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "authority": {
            "mesh_verification_required": True,
            "zaxy_checkout_authoritative": False,
        },
    }
    if reason:
        payload["reason"] = reason
    return payload


def _checkout_candidates(payload: Any, *, scope: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("items") or payload.get("candidates") or []
    if not isinstance(raw_items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_scope = item.get("scope")
        if isinstance(item_scope, dict) and not _scope_compatible(item_scope, scope):
            continue
        candidate_id = str(item.get("id") or item.get("memory_id") or "").strip()
        content = str(item.get("content") or item.get("summary") or "").strip()
        if not candidate_id or not content:
            continue
        out.append(
            {
                "id": candidate_id,
                "content": content[:2000],
                "scope": item_scope if isinstance(item_scope, dict) else {},
                "source_refs": item.get("source_refs") if isinstance(item.get("source_refs"), list) else [],
                "score": float(item.get("score", 0.0) or 0.0),
            }
        )
        if len(out) >= limit:
            break
    return out


def _scope_compatible(item_scope: dict[str, Any], request_scope: dict[str, Any]) -> bool:
    for key in ("tenant_id", "project_id", "service", "agent"):
        requested = request_scope.get(key)
        observed = item_scope.get(key)
        if requested and observed and requested != observed:
            return False
    return True


def _event_scope(config: Any, event: RunEvent) -> dict[str, Any]:
    service = None
    if isinstance(event.payload, dict):
        service = event.payload.get("service") or event.payload.get("target_service")
    return {
        "tenant_id": str(getattr(config, "zaxy_tenant_id", "local") or "local"),
        "project_id": str(getattr(config, "zaxy_project_id", "mesh") or "mesh"),
        "service": service,
        "run_id": event.run_id,
    }


def _source_refs(event: RunEvent) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "mesh_run_event",
            "run_id": event.run_id,
            "event_id": event.event_id,
            "sequence": event.sequence,
            "artifact_key": event.artifact_key,
            "merkle_leaf_hash": event.merkle_leaf_hash,
        }
    ]


def _citations(event: RunEvent) -> list[dict[str, Any]]:
    refs = []
    if isinstance(event.payload, dict):
        raw = event.payload.get("citations") or event.payload.get("source_refs") or []
        if isinstance(raw, list):
            refs = [item for item in raw if isinstance(item, dict)]
    return refs


def _sanitize_payload(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "<redacted:depth_limit>"
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in _SECRET_MARKERS):
                cleaned[key_text] = "<redacted>"
            else:
                cleaned[key_text] = _sanitize_payload(item, depth + 1)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_payload(item, depth + 1) for item in value[:200]]
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + "\n[truncated]"
    return deepcopy(value)


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    return_payload: bool = False,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            if return_payload:
                return json.loads(body) if body.strip() else {}
            return {"status": "recorded", "status_code": response.status}
    except Exception as exc:  # noqa: BLE001 - sidecar degradation must be non-blocking.
        return {"status": "degraded", "reason": str(exc)}


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
