"""Generic webhook ingestion: template-driven normalization into AlertEvent.

Accepts arbitrary JSON payloads from any monitoring vendor (Datadog, Grafana,
PagerDuty, Prometheus Alertmanager, Splunk, etc.) and normalizes them into a
single AlertEvent contract with fire / warn / resolve semantics.

Design goals:
- Zero runtime dependencies (stdlib only).
- Template is pure JSON: a map of alert-event fields to extraction specs.
- Extraction spec shorthand: ``"$.data.alerts[0].labels.service"``.
- Extraction spec full form: ``{"path": "...", "default": "...", "map": {...},
  "format": "unix_ms"}``.
- Required output fields: ``alert_id``, ``action`` (fire|warn|resolve),
  ``timestamp`` (ISO8601 UTC).
- All other fields are optional but recommended: title, description, severity,
  service, environment, labels (dict).

The template is evaluated once per webhook POST. Results are cached schemas but
template objects themselves are cheap to construct on demand.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


ACTION_FIRE = "fire"
ACTION_WARN = "warn"
ACTION_RESOLVE = "resolve"
ALLOWED_ACTIONS = {ACTION_FIRE, ACTION_WARN, ACTION_RESOLVE}

_PATH_SEGMENT = re.compile(r"(?:\.([^.\[\]]+))|(?:\[(-?\d+)\])")


class WebhookTemplateError(ValueError):
    """Raised when a template is malformed or required fields cannot be extracted."""


@dataclass
class AlertEvent:
    """Normalized webhook event, shared across every ingest source."""

    alert_id: str
    source_id: str
    action: str
    timestamp: str
    received_at: str
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    service: str | None = None
    environment: str | None = None
    labels: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    template_source_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "source_id": self.source_id,
            "action": self.action,
            "timestamp": self.timestamp,
            "received_at": self.received_at,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "service": self.service,
            "environment": self.environment,
            "labels": dict(self.labels),
            "raw_payload": dict(self.raw_payload),
            "template_source_type": self.template_source_type,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AlertEvent":
        return cls(
            alert_id=payload["alert_id"],
            source_id=payload["source_id"],
            action=payload["action"],
            timestamp=payload["timestamp"],
            received_at=payload["received_at"],
            title=payload.get("title"),
            description=payload.get("description"),
            severity=payload.get("severity"),
            service=payload.get("service"),
            environment=payload.get("environment"),
            labels=dict(payload.get("labels") or {}),
            raw_payload=dict(payload.get("raw_payload") or {}),
            template_source_type=payload.get("template_source_type"),
        )


@dataclass
class WebhookTemplate:
    """Declarative mapping from a vendor payload to an AlertEvent.

    ``fields`` maps AlertEvent field names to an extraction spec. A spec can be:
    - ``str``: a JSON path, e.g. ``"$.data.alerts[0].status"``.
    - ``dict``: ``{"path", "default", "map", "format", "join"}`` (all optional
      except ``path`` unless ``default`` is provided).

    ``labels_path`` is the path from which to extract the full labels dict,
    copied verbatim. Leave unset to skip label extraction.
    """

    source_id: str
    source_type: str
    fields: dict[str, Any] = field(default_factory=dict)
    labels_path: str | None = None
    display_name: str | None = None
    secret: str | None = None
    signature_header: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "fields": self.fields,
            "labels_path": self.labels_path,
            "display_name": self.display_name,
            "signature_header": self.signature_header,
            # secrets are never serialized over wire
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WebhookTemplate":
        if "source_id" not in payload or "source_type" not in payload:
            raise WebhookTemplateError("template requires source_id and source_type")
        if not isinstance(payload.get("fields"), dict):
            raise WebhookTemplateError("template requires a 'fields' object")
        return cls(
            source_id=payload["source_id"],
            source_type=payload["source_type"],
            fields=dict(payload["fields"]),
            labels_path=payload.get("labels_path"),
            display_name=payload.get("display_name"),
            secret=payload.get("secret"),
            signature_header=payload.get("signature_header"),
        )


def extract_path(payload: Any, path: str) -> Any:
    """Evaluate a JSONPath-style expression against ``payload``.

    Supported syntax: ``$.foo.bar[0].baz``. A leading ``$`` is optional. Missing
    segments return ``None`` instead of raising, so callers can fall back to a
    default.
    """
    if path is None:
        return None
    if not path or path == "$":
        return payload
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    node: Any = payload
    cursor = 0
    # Explicit first segment (no leading dot).
    if path and path[0] not in ".[":
        match = re.match(r"[^.\[\]]+", path)
        if match is None:
            return None
        key = match.group(0)
        node = _descend(node, key)
        cursor = match.end()
    while cursor < len(path) and node is not None:
        segment = _PATH_SEGMENT.match(path, cursor)
        if segment is None:
            return None
        key, index = segment.groups()
        if key is not None:
            node = _descend(node, key)
        elif index is not None:
            node = _descend_index(node, int(index))
        cursor = segment.end()
    return node


def _descend(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        return node.get(key)
    return None


def _descend_index(node: Any, index: int) -> Any:
    if isinstance(node, list) and -len(node) <= index < len(node):
        return node[index]
    return None


def _resolve_field(payload: Any, spec: Any) -> Any:
    """Run one field spec against the raw webhook payload.

    Spec can be a shorthand path string or a dict with optional
    ``path``/``default``/``map``/``format``/``join`` keys. ``join`` converts a
    list result to a delimited string (useful for label lists).
    """
    if isinstance(spec, str):
        return extract_path(payload, spec)
    if not isinstance(spec, dict):
        return spec
    path = spec.get("path")
    raw = extract_path(payload, path) if path is not None else None
    if raw is None and "default" in spec:
        raw = spec["default"]
    mapping = spec.get("map")
    if mapping and isinstance(raw, (str, int, float, bool)):
        key = str(raw)
        if key in mapping:
            raw = mapping[key]
        elif "default" in spec:
            raw = spec["default"]
    fmt = spec.get("format")
    if fmt and raw is not None:
        raw = _apply_format(raw, fmt)
    join = spec.get("join")
    if join is not None and isinstance(raw, list):
        raw = str(join).join(str(item) for item in raw)
    return raw


def _apply_format(value: Any, fmt: str) -> Any:
    if fmt == "unix":
        return _ts_from_unix(float(value), milliseconds=False)
    if fmt == "unix_ms":
        return _ts_from_unix(float(value), milliseconds=True)
    if fmt == "iso8601":
        return _normalize_iso8601(str(value))
    if fmt.startswith("strftime:"):
        pattern = fmt[len("strftime:") :]
        parsed = datetime.strptime(str(value), pattern)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if fmt == "lower":
        return str(value).lower()
    if fmt == "upper":
        return str(value).upper()
    return value


def _ts_from_unix(value: float, milliseconds: bool) -> str:
    seconds = value / 1000.0 if milliseconds else value
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def _normalize_iso8601(value: str) -> str:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise WebhookTemplateError(f"timestamp {value!r} is not valid ISO8601: {exc}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_action(value: Any) -> str:
    if value is None:
        raise WebhookTemplateError("template did not resolve the 'action' field")
    token = str(value).strip().lower()
    if token in ALLOWED_ACTIONS:
        return token
    # Accept common synonyms.
    synonyms = {
        "triggered": ACTION_FIRE,
        "firing": ACTION_FIRE,
        "open": ACTION_FIRE,
        "alerting": ACTION_FIRE,
        "critical": ACTION_FIRE,
        "error": ACTION_FIRE,
        "recovered": ACTION_RESOLVE,
        "resolved": ACTION_RESOLVE,
        "closed": ACTION_RESOLVE,
        "ok": ACTION_RESOLVE,
        "cleared": ACTION_RESOLVE,
        "warning": ACTION_WARN,
        "pending": ACTION_WARN,
        "no data": ACTION_WARN,
    }
    if token in synonyms:
        return synonyms[token]
    raise WebhookTemplateError(
        f"action {value!r} did not normalize to fire/warn/resolve; add an explicit 'map' in the template"
    )


def apply_template(
    template: WebhookTemplate,
    payload: dict[str, Any],
    received_at: str | None = None,
) -> AlertEvent:
    """Transform ``payload`` into a normalized AlertEvent using ``template``.

    Raises ``WebhookTemplateError`` if required fields cannot be resolved.
    """
    if "alert_id" not in template.fields:
        raise WebhookTemplateError("template is missing required field 'alert_id'")
    if "action" not in template.fields:
        raise WebhookTemplateError("template is missing required field 'action'")
    if "timestamp" not in template.fields:
        raise WebhookTemplateError("template is missing required field 'timestamp'")

    alert_id = _resolve_field(payload, template.fields["alert_id"])
    if alert_id is None:
        raise WebhookTemplateError("template could not resolve alert_id from payload")
    action = _normalize_action(_resolve_field(payload, template.fields["action"]))
    timestamp_raw = _resolve_field(payload, template.fields["timestamp"])
    if timestamp_raw is None:
        raise WebhookTemplateError("template could not resolve timestamp from payload")
    timestamp = _coerce_timestamp(timestamp_raw, template.fields["timestamp"])

    labels: dict[str, Any] = {}
    if template.labels_path:
        label_payload = extract_path(payload, template.labels_path)
        if isinstance(label_payload, dict):
            labels.update({str(key): value for key, value in label_payload.items()})

    event = AlertEvent(
        alert_id=str(alert_id),
        source_id=template.source_id,
        action=action,
        timestamp=timestamp,
        received_at=received_at or _utcnow(),
        title=_as_str_or_none(_resolve_field(payload, template.fields.get("title"))),
        description=_as_str_or_none(_resolve_field(payload, template.fields.get("description"))),
        severity=_as_str_or_none(_resolve_field(payload, template.fields.get("severity"))),
        service=_as_str_or_none(_resolve_field(payload, template.fields.get("service"))),
        environment=_as_str_or_none(_resolve_field(payload, template.fields.get("environment"))),
        labels=labels,
        raw_payload=payload,
        template_source_type=template.source_type,
    )
    return event


def _coerce_timestamp(value: Any, spec: Any) -> str:
    if isinstance(spec, dict) and spec.get("format"):
        # _resolve_field already converted the value; trust it.
        if isinstance(value, str):
            return value
        return _normalize_iso8601(str(value))
    if isinstance(value, (int, float)):
        # Heuristic: numeric timestamps without explicit format are assumed ms
        # if they exceed 10^12, else seconds.
        if value > 1_000_000_000_000:
            return _ts_from_unix(float(value), milliseconds=True)
        return _ts_from_unix(float(value), milliseconds=False)
    return _normalize_iso8601(str(value))


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def verify_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    """Validate an HMAC-SHA256 signature against the raw request body.

    Returns ``True`` when the template has no secret (signature optional) or when
    the computed digest matches. Constant-time comparison is used.
    """
    if not secret:
        return True
    if not signature:
        return False
    candidate = signature.strip()
    if candidate.lower().startswith("sha256="):
        candidate = candidate.split("=", 1)[1]
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, candidate)
