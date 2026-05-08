"""Tiny shared HTTP helpers for read-only HTTP-backed tool packs.

Loki and Jaeger both speak pure HTTP/GET against external read-only
APIs and want the same shape: bounded response size, JSON decode,
error normalization. ``urllib.request`` keeps the hard-dep surface
zero (no ``requests``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..harness import RawToolOutput


MAX_RESPONSE_BYTES = 96 * 1024


def http_get_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
) -> tuple[Any, str | None]:
    """GET ``url``, decode JSON, return ``(body, error_message)``.

    Returns ``(None, "...")`` on any HTTP/network/decode failure.
    Body is capped at ``MAX_RESPONSE_BYTES`` — over-cap responses
    return as a "response too large" error.
    """
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return None, f"http {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return None, f"url error: {exc.reason}"
    except OSError as exc:
        return None, f"io error: {exc}"
    if len(raw) > MAX_RESPONSE_BYTES:
        return None, "response too large"
    try:
        return json.loads(raw.decode("utf-8") or "null"), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"decode error: {exc}"


def failure_result(domain: str, tool_name: str, message: str) -> RawToolOutput:
    return RawToolOutput(
        output={"error": message},
        output_summary=f"{domain}:{tool_name} failed: {message[:400]}",
        citations=[{"source_type": f"{domain}_query", "source_ref": tool_name}],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )
