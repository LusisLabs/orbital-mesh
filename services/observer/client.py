"""OpenAI-compatible Chat Completions client.

Speaks the OpenAI ``/v1/chat/completions`` shape, which is the de-facto
standard most providers (OpenAI, Anthropic via SDK adapters, Together,
Groq, OpenRouter, vLLM, llama.cpp, Ollama with the OpenAI-compat layer)
implement. Switching providers means changing one base URL and one API
key — no code changes.

# Why a hand-rolled client and not the openai SDK

The rest of the codebase intentionally avoids large vendor SDKs in favor
of a stdlib HTTP shim (see ``bare_metal_node._rpc_call``). The observer
is hot-path enough that a 700ms cold-import on the SDK would dominate
startup, and we'd inherit a transitive dependency tree we don't want in
a control-plane. The wire format is ~150 lines; we own it.

# Prompt caching

Most OpenAI-compatible providers support prompt caching with different
opt-in conventions:

* OpenAI: automatic on prompts with ``>= 1024`` tokens; nothing to do.
* Anthropic (via OpenAI adapter): requires ``cache_control`` markers on
  message content blocks. We send the marker as metadata; servers that
  ignore it pay the price of a cache miss but otherwise work fine.
* vLLM, Together, Groq: automatic if enabled server-side.

We keep the static parts of the prompt (system instructions, policy
file, hypothesis templates, action allowlist) at the *beginning* of the
message stream so that any prefix-cache implementation matches them
across calls. Per-run evidence goes at the end.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def _post_with_retry(
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout_seconds: float,
    max_retries: int = 1,
) -> bytes:
    """POST with one retry on transient 429/5xx, honoring ``Retry-After``
    only within the caller's overall ``timeout_seconds`` budget.

    Production providers commonly rate-limit; we surface the first
    failure as an observer error after retries are exhausted, so the
    deterministic decision still stands. Single retry is sufficient for
    the simulation's burst-then-pause access pattern; longer backoff is
    not the right loop shape because the observer is on the critical
    path and operators expect a verdict promptly or not at all.

    The retry obeys the **same** wall-clock budget as the original
    call. If the provider's ``Retry-After`` would push us past
    ``timeout_seconds``, we don't sleep — we surface the 429 immediately
    so the observer can fail-open. Otherwise an 8-second observer
    timeout could become a 30-second hang the moment Anthropic returns a
    long Retry-After.
    """
    start = time.monotonic()
    attempt = 0
    # Reserve a 0.5s safety floor for the actual retried call so we
    # don't sleep up to the budget then time out the socket.
    _MIN_RETRY_CALL_BUDGET = 0.5
    while True:
        elapsed = time.monotonic() - start
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            raise ObserverClientError(
                f"observer budget exhausted after {elapsed:.1f}s"
            )
        per_call_timeout = min(remaining, timeout_seconds)
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=per_call_timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt >= max_retries:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    detail = ""
                raise ObserverClientError(f"observer http {exc.code}: {detail}") from exc
            wait_s = 5.0
            try:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after:
                    wait_s = float(retry_after)
            except (TypeError, ValueError):
                pass
            elapsed = time.monotonic() - start
            remaining = timeout_seconds - elapsed
            if wait_s + _MIN_RETRY_CALL_BUDGET >= remaining:
                # Retry-After would exceed our budget; abandon the retry
                # and let the caller fall back. Drain any error body so
                # the message is useful.
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    detail = ""
                raise ObserverClientError(
                    f"observer http {exc.code}: retry-after={wait_s:.1f}s "
                    f"exceeds remaining budget {remaining:.1f}s; {detail}"
                ) from exc
            time.sleep(wait_s)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt >= max_retries:
                raise ObserverClientError(f"observer transport: {exc}") from exc
            elapsed = time.monotonic() - start
            remaining = timeout_seconds - elapsed
            if remaining <= _MIN_RETRY_CALL_BUDGET + 2.0:
                # Not enough budget left for a 2s backoff + a real call.
                raise ObserverClientError(f"observer transport: {exc}") from exc
            time.sleep(2.0)
        attempt += 1


_LOG = logging.getLogger("mesh.observer.client")


class ObserverClientError(RuntimeError):
    """Raised when the upstream provider rejects the call or replies
    with an unparseable response. Callers catch this and fall back to
    the deterministic decision."""


@dataclass
class ChatMessage:
    role: str       # "system" | "user" | "assistant"
    content: str
    cache_hint: bool = False  # informational; not all providers honor it


def chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[ChatMessage],
    timeout_seconds: float = 8.0,
    response_format: dict[str, Any] | None = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
    provider: str = "openai",
) -> dict[str, Any]:
    """Call the provider's chat-completion endpoint.

    ``provider="openai"`` (default) hits ``/v1/chat/completions`` on
    ``base_url``. Works with OpenAI, vLLM, Ollama, Together, Groq,
    OpenRouter, llama.cpp's OpenAI shim, etc.

    ``provider="anthropic"`` hits Anthropic's native Messages API at
    ``base_url + /v1/messages``. The ``system`` role becomes the top-
    level ``system`` field; user/assistant roles become messages.
    Anthropic ignores ``response_format`` (it doesn't have a JSON-mode
    knob), but we keep the same prompt convention — the system message
    instructs the model to emit JSON only, which works in practice.

    Returns the parsed JSON response. On transport, parse, or HTTP error,
    raises ``ObserverClientError`` with a short, decision-loggable
    message; the caller decides whether to fall back.
    """
    if provider == "anthropic":
        return _anthropic_messages(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    url = base_url.rstrip("/") + "/v1/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        body["response_format"] = response_format

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    encoded = json.dumps(body).encode("utf-8")
    raw = _post_with_retry(url, encoded, headers, timeout_seconds)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ObserverClientError(f"observer invalid JSON: {exc}") from exc

    if not isinstance(payload, dict) or "choices" not in payload:
        raise ObserverClientError(f"observer payload missing 'choices': {payload!r}")

    return payload


def _anthropic_messages(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[ChatMessage],
    timeout_seconds: float,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """Call Anthropic's native Messages API and adapt the response to
    OpenAI shape so callers don't need to branch.

    We also opt in to ephemeral prompt caching on the system block —
    Anthropic's prompt cache lifetime is 5 minutes, exactly the right
    granularity for repeated observer calls during a fault-injection
    burst.
    """
    url = base_url.rstrip("/") + "/v1/messages"
    system_text = ""
    convo: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_text = m.content if not system_text else system_text + "\n" + m.content
        elif m.role in ("user", "assistant"):
            convo.append({"role": m.role, "content": m.content})

    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": convo,
    }
    if system_text:
        body["system"] = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    encoded = json.dumps(body).encode("utf-8")
    raw = _post_with_retry(url, encoded, headers, timeout_seconds)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ObserverClientError(f"observer invalid JSON: {exc}") from exc

    # Anthropic returns ``content: [{type: text, text: ...}, ...]``;
    # adapt to OpenAI's ``choices[0].message.content``.
    content_blocks = payload.get("content")
    if not isinstance(content_blocks, list) or not content_blocks:
        raise ObserverClientError(f"anthropic payload missing 'content': {payload!r}")
    text_parts: list[str] = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
    if not text_parts:
        raise ObserverClientError(f"anthropic content has no text blocks: {payload!r}")

    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": "\n".join(text_parts)},
                "finish_reason": payload.get("stop_reason"),
            }
        ],
        "usage": payload.get("usage", {}),
        # Surface cache stats so the simulation report can show savings.
        "_anthropic_cache_creation_input_tokens": (payload.get("usage") or {}).get(
            "cache_creation_input_tokens"
        ),
        "_anthropic_cache_read_input_tokens": (payload.get("usage") or {}).get(
            "cache_read_input_tokens"
        ),
    }


def extract_message_content(payload: dict[str, Any]) -> str:
    """Pull the assistant message out of an OpenAI-shaped response."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ObserverClientError("observer response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ObserverClientError("observer choice has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ObserverClientError("observer message has no string content")
    return content
