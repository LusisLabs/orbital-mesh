from __future__ import annotations

from typing import Any


_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "password",
    "jwt",
)


def redact_for_observer(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                redacted[key_str] = "<redacted>"
            else:
                redacted[key_str] = redact_for_observer(item)
        return redacted
    if isinstance(value, list):
        return [redact_for_observer(item) for item in value]
    if isinstance(value, tuple):
        return [redact_for_observer(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _redact_string(value: str) -> str:
    if "Bearer " in value:
        return value.split("Bearer ", 1)[0] + "Bearer <redacted>"
    if value.startswith("sk-") or value.startswith("sk_"):
        return "<redacted>"
    return value
