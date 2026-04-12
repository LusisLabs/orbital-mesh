"""MiniMax via OpenAI-compatible or Anthropic-compatible HTTP APIs (stdlib only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def minimax_openai_base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_HOST") or "https://api.minimax.io/v1").rstrip("/")


def minimax_anthropic_base_url() -> str:
    return (
        os.getenv("ANTHROPIC_BASE_URL") or os.getenv("ANTHROPIC_HOST") or "https://api.minimax.io/anthropic"
    ).rstrip("/")


def minimax_model() -> str:
    return (
        os.getenv("MINIMAX_MODEL")
        or os.getenv("HERMES_MODEL")
        or os.getenv("LLM_MODEL")
        or os.getenv("GOOSE_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or "MiniMax-M2.5"
    )


def _openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY")


def _anthropic_api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")


def minimax_route_label() -> str:
    if _openai_api_key():
        return "openai"
    if _anthropic_api_key():
        return "anthropic"
    return "none"


def research_chat_timeout_seconds() -> float:
    """Long-running MiniMax calls (multi-wave synthesis). Override with MINIMAX_CHAT_TIMEOUT_SECONDS or MESH_MINIMAX_TIMEOUT_SECONDS."""
    raw = os.getenv("MINIMAX_CHAT_TIMEOUT_SECONDS") or os.getenv("MESH_MINIMAX_TIMEOUT_SECONDS")
    if raw is not None and str(raw).strip():
        return max(30.0, float(raw))
    return 600.0


def _split_messages_for_anthropic(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_chunks: list[str] = []
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_chunks.append(content)
        elif role in ("user", "assistant"):
            out.append({"role": role, "content": [{"type": "text", "text": content}]})
    system = "\n\n".join(system_chunks) if system_chunks else None
    return system, out


def _anthropic_response_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in data.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and "text" in block:
            parts.append(str(block["text"]))
        # Some responses use "thinking" blocks; skip or include — user-facing text only
    return "\n".join(p.strip() for p in parts if p).strip()


def _chat_completion_openai(
    messages: list[dict[str, str]],
    *,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    timeout_seconds: float,
    api_key: str,
) -> str:
    base = minimax_openai_base_url()
    url = f"{base}/chat/completions"
    payload: dict[str, Any] = {
        "model": model or minimax_model(),
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except TimeoutError as exc:
        raise RuntimeError(
            f"MiniMax OpenAI request timed out after {timeout_seconds}s (large prompts need longer). "
            "Set MINIMAX_CHAT_TIMEOUT_SECONDS=600 or 900 in the environment."
        ) from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"MiniMax OpenAI API HTTP {exc.code}: {detail}") from exc
    data = json.loads(raw)
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected MiniMax OpenAI response shape: {raw[:2000]}") from exc


def _chat_completion_anthropic(
    messages: list[dict[str, str]],
    *,
    model: str | None,
    max_tokens: int | None,
    timeout_seconds: float,
    api_key: str,
) -> str:
    base = minimax_anthropic_base_url()
    url = f"{base}/v1/messages"
    system, anth_messages = _split_messages_for_anthropic(messages)
    payload: dict[str, Any] = {
        "model": model or minimax_model(),
        "max_tokens": max_tokens if max_tokens is not None else 8192,
        "messages": anth_messages,
    }
    if system:
        payload["system"] = system
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except TimeoutError as exc:
        raise RuntimeError(
            f"MiniMax Anthropic request timed out after {timeout_seconds}s. "
            "Set MINIMAX_CHAT_TIMEOUT_SECONDS=600 or 900 in the environment."
        ) from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"MiniMax Anthropic API HTTP {exc.code}: {detail}") from exc
    data = json.loads(raw)
    text = _anthropic_response_text(data)
    if not text:
        raise RuntimeError(f"Unexpected MiniMax Anthropic response shape: {raw[:2000]}")
    return text


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float = 180.0,
) -> str:
    """
    Call MiniMax using either:
    - OpenAI-compatible: OPENAI_BASE_URL + OPENAI_API_KEY (or MINIMAX_API_KEY), or
    - Anthropic-compatible fallback: ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN),
      as used elsewhere in this repo for MiniMax.
    OpenAI route takes precedence when OPENAI_API_KEY (or MINIMAX_API_KEY) is set.
    """
    okey = _openai_api_key()
    akey = _anthropic_api_key()
    if okey:
        return _chat_completion_openai(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            api_key=okey,
        )
    if akey:
        return _chat_completion_anthropic(
            messages,
            model=model,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            api_key=akey,
        )
    raise RuntimeError(
        "Set OPENAI_API_KEY (OpenAI-compatible MiniMax) or ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN "
        "(Anthropic-compatible MiniMax fallback), matching .env.example."
    )
