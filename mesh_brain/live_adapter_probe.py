from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .run_live_serving_smoke import DEFAULT_BASE_URL, DEFAULT_MODEL, evaluate_live_response


DEFAULT_OUTPUT_DIRECTORY = Path(".mesh-runtime-state") / "mesh-brain" / "live-adapter-runtime-probe"


@dataclass(frozen=True)
class LiveAdapterProbePolicy:
    expected_model: str
    require_adapter_load: bool = False
    latency_budget_ms: float = 30_000.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_live_adapter_runtime_probe(
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    adapter_id: str = "mesh-brain-probe-adapter",
    base_model_id: str | None = None,
    prompt: str = (
        "For a Mesh Brain CROPS smoke, cite evidence, keep remediation bounded, "
        "and state that operator approval is required before action."
    ),
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    timeout_seconds: float = 30.0,
    require_adapter_load: bool = False,
    latency_budget_ms: float = 30_000.0,
) -> dict[str, Any]:
    policy = LiveAdapterProbePolicy(
        expected_model=model,
        require_adapter_load=require_adapter_load,
        latency_budget_ms=latency_budget_ms,
    )
    started = time.perf_counter()
    models_result = _get_json(base_url=base_url, path="/v1/models", timeout_seconds=timeout_seconds)
    chat_result = _post_json(
        base_url=base_url,
        path="/v1/chat/completions",
        payload={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "metadata": {"mesh_brain_live_adapter_probe": True},
        },
        timeout_seconds=timeout_seconds,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    response_text = _chat_text(chat_result.payload)
    response_eval = evaluate_live_response(text=response_text).to_dict()
    adapter_load = _probe_adapter_load(
        base_url=base_url,
        adapter_id=adapter_id,
        base_model_id=base_model_id or model,
        timeout_seconds=timeout_seconds,
    )
    post_load_models = _get_json(base_url=base_url, path="/v1/models", timeout_seconds=timeout_seconds) if adapter_load["supported"] else None
    adapter_loaded = bool(post_load_models and _model_list_contains(post_load_models.payload, adapter_id))
    decision = _decide_probe(
        model=model,
        chat_result=chat_result,
        response_eval=response_eval,
        latency_ms=latency_ms,
        adapter_load=adapter_load,
        adapter_loaded=adapter_loaded,
        policy=policy,
    )
    summary = {
        "status": decision["status"],
        "decision": decision,
        "base_url": base_url,
        "model": _response_model(chat_result.payload) or model,
        "requested_model": model,
        "adapter_id": adapter_id,
        "base_model_id": base_model_id or model,
        "latency_ms": latency_ms,
        "models": models_result.to_dict(),
        "chat": chat_result.to_dict(),
        "response_eval": response_eval,
        "adapter_load": adapter_load,
        "post_load_models": post_load_models.to_dict() if post_load_models else None,
        "adapter_loaded": adapter_loaded,
        "content_preview": response_text[:500],
        "policy": policy.to_dict(),
    }
    written = write_live_adapter_runtime_probe(summary=summary, output_directory=output_directory)
    return {**summary, "artifact_paths": written}


@dataclass(frozen=True)
class HttpProbeResult:
    ok: bool
    status_code: int | None
    path: str
    payload: dict[str, Any]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_live_adapter_runtime_probe(*, summary: dict[str, Any], output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    summary_path = output_path / "live_adapter_runtime_probe.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"live_adapter_runtime_probe": str(summary_path)}


def _get_json(*, base_url: str, path: str, timeout_seconds: float) -> HttpProbeResult:
    request = urlrequest.Request(f"{base_url.rstrip('/')}{path}", method="GET")
    return _open_json(request=request, path=path, timeout_seconds=timeout_seconds)


def _post_json(*, base_url: str, path: str, payload: dict[str, Any], timeout_seconds: float) -> HttpProbeResult:
    request = urlrequest.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _open_json(request=request, path=path, timeout_seconds=timeout_seconds)


def _open_json(*, request: urlrequest.Request, path: str, timeout_seconds: float) -> HttpProbeResult:
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return HttpProbeResult(ok=True, status_code=response.status, path=path, payload=payload)
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return HttpProbeResult(ok=False, status_code=exc.code, path=path, payload={}, error=detail)
    except (OSError, URLError, ValueError) as exc:
        return HttpProbeResult(ok=False, status_code=None, path=path, payload={}, error=str(exc))


def _probe_adapter_load(*, base_url: str, adapter_id: str, base_model_id: str, timeout_seconds: float) -> dict[str, Any]:
    result = _post_json(
        base_url=base_url,
        path="/v1/adapters/load",
        payload={
            "adapter_id": adapter_id,
            "base_model_id": base_model_id,
            "probe": True,
        },
        timeout_seconds=timeout_seconds,
    )
    error_text = str(result.payload.get("error") or result.error or "")
    supported = (
        result.ok
        and not error_text
        and result.payload.get("adapter_id") in {adapter_id, None}
        and str(result.payload.get("status") or "loaded") in {"loaded", "ok", "ready"}
    )
    if result.status_code in {404, 405, 501}:
        supported = False
    return {
        "supported": supported,
        "path": "/v1/adapters/load",
        "status_code": result.status_code,
        "response": result.payload,
        "error": result.error,
    }


def _decide_probe(
    *,
    model: str,
    chat_result: HttpProbeResult,
    response_eval: dict[str, Any],
    latency_ms: float,
    adapter_load: dict[str, Any],
    adapter_loaded: bool,
    policy: LiveAdapterProbePolicy,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not chat_result.ok:
        reasons.append("chat_completion_failed")
    if _response_model(chat_result.payload) != model:
        reasons.append("model_mismatch")
    if response_eval.get("decision") == "block":
        reasons.append("response_eval_blocked")
    if latency_ms > policy.latency_budget_ms:
        reasons.append("latency_budget_exceeded")
    if policy.require_adapter_load and not adapter_load["supported"]:
        reasons.append("adapter_load_required_but_unsupported")
    if adapter_load["supported"] and not adapter_loaded:
        reasons.append("adapter_load_not_reflected_in_models")
    if reasons:
        status = "block"
    elif adapter_load["supported"] and adapter_loaded:
        status = "adapter_pass"
    else:
        status = "base_model_pass"
    return {
        "status": status,
        "base_model_passed": status in {"base_model_pass", "adapter_pass"},
        "adapter_load_supported": bool(adapter_load["supported"]),
        "adapter_serving_passed": status == "adapter_pass",
        "reasons": reasons,
    }


def _chat_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    return str(message.get("content") or "")


def _response_model(payload: dict[str, Any]) -> str | None:
    model = payload.get("model")
    return str(model) if model is not None else None


def _model_list_contains(payload: dict[str, Any], model_id: str) -> bool:
    data = payload.get("data")
    if not isinstance(data, list):
        return False
    return any(isinstance(item, dict) and item.get("id") == model_id for item in data)
