"""WebhookIngestService: register vendor-specific templates and normalize
arbitrary webhook payloads into the shared AlertEvent contract.

This is the generic front door Resolve-style: any monitor that can POST JSON
now plugs in without bespoke adapters. When a source opts into ``auto_run``,
``fire`` events synthesize a mesh signal and hand off to the RunCoordinator.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from shared.mesh_runtime.alert_store import AlertStore
from shared.mesh_runtime.webhook_templates import (
    ACTION_FIRE,
    AlertEvent,
    WebhookTemplate,
    WebhookTemplateError,
    apply_template,
    verify_signature,
)


class WebhookIngestError(ValueError):
    pass


class SignatureMismatchError(WebhookIngestError):
    pass


class UnknownWebhookSourceError(WebhookIngestError):
    pass


class WebhookIngestService:
    """Manage webhook source configs and transform inbound payloads."""

    def __init__(
        self,
        alert_store: AlertStore,
        run_factory: Callable[[AlertEvent, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.alert_store = alert_store
        self._run_factory = run_factory
        self._templates: dict[str, dict[str, Any]] = alert_store.load_sources()

    # ---- source registry --------------------------------------------------

    def register_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        template = WebhookTemplate.from_dict(payload)
        record = {
            **template.to_dict(),
            "auto_run": bool(payload.get("auto_run", False)),
            "goal_id": payload.get("goal_id"),
            "require_signature": bool(payload.get("require_signature", bool(template.secret))),
            "created_at": payload.get("created_at", _utcnow()),
            "updated_at": _utcnow(),
        }
        # Secret is stored but never serialized outbound.
        if template.secret:
            record["secret"] = template.secret
        self._templates[template.source_id] = record
        self.alert_store.save_sources(self._templates)
        return _redact_secret(record)

    def delete_source(self, source_id: str) -> None:
        if source_id not in self._templates:
            raise UnknownWebhookSourceError(source_id)
        self._templates.pop(source_id)
        self.alert_store.save_sources(self._templates)

    def list_sources(self) -> list[dict[str, Any]]:
        return [_redact_secret(record) for record in self._templates.values()]

    def get_source(self, source_id: str) -> dict[str, Any]:
        record = self._templates.get(source_id)
        if record is None:
            raise UnknownWebhookSourceError(source_id)
        return _redact_secret(record)

    # ---- ingest -----------------------------------------------------------

    def ingest(
        self,
        source_id: str,
        payload: dict[str, Any],
        raw_body: bytes | None = None,
        signature: str | None = None,
    ) -> dict[str, Any]:
        record = self._templates.get(source_id)
        if record is None:
            raise UnknownWebhookSourceError(source_id)

        template = WebhookTemplate.from_dict(record)
        template.secret = record.get("secret")
        template.signature_header = record.get("signature_header")

        body_bytes = raw_body if raw_body is not None else b""
        if record.get("require_signature") or template.secret:
            if not verify_signature(body_bytes, signature, template.secret):
                raise SignatureMismatchError(f"signature verification failed for source {source_id!r}")

        try:
            event = apply_template(template, payload)
        except WebhookTemplateError as exc:
            raise WebhookIngestError(str(exc)) from exc

        self.alert_store.append(event)

        result: dict[str, Any] = {"alert": event.to_dict(), "spawned_run": None}
        if record.get("auto_run") and event.action == ACTION_FIRE and self._run_factory is not None:
            try:
                run = self._run_factory(event, record)
            except Exception as exc:  # pragma: no cover - defensive wrapper
                result["spawn_error"] = str(exc)
            else:
                result["spawned_run"] = run
        return result

    def list_events(self, source_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.alert_store.list_events(source_id, limit)]


def _redact_secret(record: dict[str, Any]) -> dict[str, Any]:
    copy = dict(record)
    if "secret" in copy:
        copy["secret"] = "***"
    return copy


def build_signal_from_alert(event: AlertEvent) -> dict[str, Any]:
    """Best-effort mapping from AlertEvent to a minimum mesh signal payload.

    The resulting dict is not guaranteed to satisfy the full trigger schema
    because webhook payloads rarely carry p95 latency / sample-size context. It
    is good enough to queue an operator-reviewed run and ship the raw alert
    into the vault alongside the evidence bundle. Callers that need strict
    telemetry should provide their own run_factory.
    """
    labels = event.labels or {}
    observed_at = event.timestamp or _utcnow()
    return {
        "signal_id": f"webhook_{event.source_id}_{event.alert_id}",
        "signal_type": "webhook_alert",
        "environment": event.environment or labels.get("env") or "production",
        "service": event.service or labels.get("service") or event.source_id,
        "endpoint": labels.get("endpoint") or event.title or "unknown",
        "observed_at": observed_at,
        "severity": event.severity or labels.get("severity"),
        "title": event.title,
        "description": event.description,
        "alert_event": event.to_dict(),
    }


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
