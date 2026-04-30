from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .runtime import stable_digest, utc_now
from .serving import OpenAIChatRequest, ServingPlan


class MeshBrainModelClient(Protocol):
    def complete_chat(
        self,
        *,
        plan: ServingPlan,
        request: OpenAIChatRequest,
    ) -> "MeshBrainModelClientResult": ...


@dataclass
class MeshBrainModelClientResult:
    completion_id: str
    request_id: str
    backend_name: str
    model: str
    content: str
    finish_reason: str
    usage: dict[str, int]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeterministicMeshBrainModelClient:
    def __init__(self, *, content: str = "Deterministic Mesh Brain response.") -> None:
        self._content = content

    def complete_chat(
        self,
        *,
        plan: ServingPlan,
        request: OpenAIChatRequest,
    ) -> MeshBrainModelClientResult:
        prompt = _last_user_message(request.messages)
        content = f"{self._content} request={plan.request_id} prompt={prompt[:80]}"
        usage = {
            "prompt_tokens": int(plan.trace.get("estimated_tokens", request.estimated_tokens()) or 0),
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": 0,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return MeshBrainModelClientResult(
            completion_id=f"mb_det_completion_{stable_digest({'request': plan.request_id, 'content': content})[:16]}",
            request_id=plan.request_id,
            backend_name=plan.backend_name,
            model=plan.model_artifact_id or request.model,
            content=content,
            finish_reason="stop",
            usage=usage,
            raw_response={
                "deterministic": True,
                "route": plan.route.to_dict(),
                "openai_compatible": plan.openai_compatible,
            },
        )


class OpenAICompatibleMeshBrainModelClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def complete_chat(
        self,
        *,
        plan: ServingPlan,
        request: OpenAIChatRequest,
    ) -> MeshBrainModelClientResult:
        payload = _openai_payload(plan=plan, request=request)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = urlrequest.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlrequest.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI-compatible backend returned HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError, ValueError) as exc:
            raise RuntimeError(f"OpenAI-compatible backend request failed: {exc}") from exc
        return _parse_openai_response(raw=raw, plan=plan, request=request)


def _openai_payload(*, plan: ServingPlan, request: OpenAIChatRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": plan.model_artifact_id or request.model,
        "messages": list(request.messages),
        "stream": bool(request.stream),
        "metadata": {
            **dict(request.metadata),
            "mesh_brain_request_id": plan.request_id,
            "mesh_brain_pool_id": plan.pool_id,
            "mesh_brain_backend": plan.backend_name,
        },
    }
    if request.tools:
        payload["tools"] = list(request.tools)
    if request.response_format is not None:
        payload["response_format"] = dict(request.response_format)
    return payload


def _parse_openai_response(
    *,
    raw: dict[str, Any],
    plan: ServingPlan,
    request: OpenAIChatRequest,
) -> MeshBrainModelClientResult:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI-compatible backend response missing choices")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if content is None:
        content = ""
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    parsed_usage = {
        "prompt_tokens": int(usage.get("prompt_tokens", plan.trace.get("estimated_tokens", 0)) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }
    if parsed_usage["total_tokens"] <= 0:
        parsed_usage["total_tokens"] = parsed_usage["prompt_tokens"] + parsed_usage["completion_tokens"]
    return MeshBrainModelClientResult(
        completion_id=str(raw.get("id") or f"mb_openai_completion_{stable_digest(raw)[:16]}"),
        request_id=plan.request_id,
        backend_name=plan.backend_name,
        model=str(raw.get("model") or plan.model_artifact_id or request.model),
        content=str(content),
        finish_reason=str(first.get("finish_reason") or "unknown"),
        usage=parsed_usage,
        tool_calls=list(message.get("tool_calls", [])) if isinstance(message.get("tool_calls"), list) else [],
        raw_response=raw,
    )


def _last_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""
