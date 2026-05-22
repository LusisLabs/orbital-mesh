from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, cast

from mesh_darkharness.schema_validation import validate_payload


def as_plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, dict):
            return payload
    if is_dataclass(value) and not isinstance(value, type):
        payload = asdict(cast(Any, value))
        if isinstance(payload, dict):
            return payload
    raise TypeError(f"expected mapping-like payload, got {type(value).__name__}")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, *parts: Any) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def validate(schema_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    validate_payload(schema_name, payload)
    return payload


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None]
    return [str(value)]
