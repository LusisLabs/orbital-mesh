from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .model_client import MeshBrainModelClientResult
from .runtime import ModelArtifact, stable_digest, utc_now
from .serving import OpenAIChatRequest, ServingPlan


@dataclass(frozen=True)
class AdapterRuntimeRequest:
    adapter_artifact: ModelArtifact
    base_model_id: str
    serving_backend: str
    timeout_seconds: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_artifact": self.adapter_artifact.to_dict(),
            "base_model_id": self.base_model_id,
            "serving_backend": self.serving_backend,
            "timeout_seconds": self.timeout_seconds,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AdapterRuntimeResult:
    runtime_name: str
    status: str
    adapter_artifact_id: str
    base_model_id: str
    serving_backend: str
    recorded_at: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MeshBrainAdapterRuntime(Protocol):
    runtime_name: str

    def verify(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult: ...

    def load(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult: ...

    def readiness(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult: ...

    def infer(
        self,
        *,
        request: AdapterRuntimeRequest,
        plan: ServingPlan,
        chat_request: OpenAIChatRequest,
    ) -> MeshBrainModelClientResult: ...


class FilesystemAdapterRuntime:
    runtime_name = "filesystem_adapter_runtime"

    def verify(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult:
        outputs = _adapter_outputs(request.adapter_artifact)
        missing = [output for output in outputs if not Path(str(output.get("path", ""))).exists()]
        hash_mismatches = [
            output
            for output in outputs
            if Path(str(output.get("path", ""))).exists()
            and output.get("sha256")
            and not _file_matches_digest(Path(str(output["path"])), str(output["sha256"]))
        ]
        base_compatible = request.adapter_artifact.base_artifact_id in {None, request.base_model_id}
        status = "passed" if outputs and not missing and not hash_mismatches and base_compatible else "failed"
        return _runtime_result(
            runtime_name=self.runtime_name,
            status=status,
            request=request,
            details={
                "output_count": len(outputs),
                "missing_outputs": missing,
                "hash_mismatches": hash_mismatches,
                "base_compatible": base_compatible,
            },
        )

    def load(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult:
        verified = self.verify(request)
        status = "loaded" if verified.status == "passed" else "failed"
        return _runtime_result(
            runtime_name=self.runtime_name,
            status=status,
            request=request,
            details={"verified": verified.to_dict(), "loaded_adapter_id": request.adapter_artifact.artifact_id},
        )

    def readiness(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult:
        loaded = self.load(request)
        status = "ready" if loaded.status == "loaded" else "failed"
        return _runtime_result(
            runtime_name=self.runtime_name,
            status=status,
            request=request,
            details={"loaded": loaded.to_dict()},
        )

    def infer(
        self,
        *,
        request: AdapterRuntimeRequest,
        plan: ServingPlan,
        chat_request: OpenAIChatRequest,
    ) -> MeshBrainModelClientResult:
        readiness = self.readiness(request)
        if readiness.status != "ready":
            raise RuntimeError("adapter runtime is not ready")
        content = (
            "Filesystem adapter runtime response. "
            f"adapter={request.adapter_artifact.artifact_id} base={request.base_model_id}"
        )
        usage = {
            "prompt_tokens": chat_request.estimated_tokens(),
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": 0,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return MeshBrainModelClientResult(
            completion_id=f"mb_adapter_completion_{stable_digest({'adapter': request.adapter_artifact.artifact_id, 'plan': plan.request_id})[:16]}",
            request_id=plan.request_id,
            backend_name=plan.backend_name,
            model=request.adapter_artifact.artifact_id,
            content=content,
            finish_reason="stop",
            usage=usage,
            raw_response={"adapter_runtime": readiness.to_dict()},
        )


class DeterministicAdapterRuntime(FilesystemAdapterRuntime):
    runtime_name = "deterministic_adapter_runtime"

    def infer(
        self,
        *,
        request: AdapterRuntimeRequest,
        plan: ServingPlan,
        chat_request: OpenAIChatRequest,
    ) -> MeshBrainModelClientResult:
        readiness = self.readiness(request)
        if readiness.status != "ready":
            raise RuntimeError("adapter runtime is not ready")
        content = (
            "Deterministic adapter runtime response. "
            f"adapter={request.adapter_artifact.artifact_id} base={request.base_model_id}"
        )
        usage = {
            "prompt_tokens": chat_request.estimated_tokens(),
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": 0,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return MeshBrainModelClientResult(
            completion_id=f"mb_det_adapter_completion_{stable_digest({'adapter': request.adapter_artifact.artifact_id, 'plan': plan.request_id})[:16]}",
            request_id=plan.request_id,
            backend_name=plan.backend_name,
            model=request.adapter_artifact.artifact_id,
            content=content,
            finish_reason="stop",
            usage=usage,
            raw_response={"adapter_runtime": readiness.to_dict()},
        )


class OpenAICompatibleAdapterRuntime(FilesystemAdapterRuntime):
    runtime_name = "openai_compatible_adapter_runtime"

    def __init__(self, *, base_url: str, api_key: str | None = None, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def load(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult:
        verified = self.verify(request)
        if verified.status != "passed":
            return _runtime_result(
                runtime_name=self.runtime_name,
                status="failed",
                request=request,
                details={"verified": verified.to_dict()},
            )
        payload = {
            "adapter_id": request.adapter_artifact.artifact_id,
            "base_model_id": request.base_model_id,
            "outputs": _adapter_outputs(request.adapter_artifact),
        }
        raw = self._request_json("/v1/adapters/load", payload)
        loaded_adapter = raw.get("adapter_id") or raw.get("loaded_adapter_id")
        status = "loaded" if loaded_adapter == request.adapter_artifact.artifact_id else "failed"
        return _runtime_result(
            runtime_name=self.runtime_name,
            status=status,
            request=request,
            details={"verified": verified.to_dict(), "response": raw, "loaded_adapter_id": loaded_adapter},
        )

    def readiness(self, request: AdapterRuntimeRequest) -> AdapterRuntimeResult:
        raw = self._get_json("/health")
        models = self._get_json("/v1/models")
        loaded = _model_list_contains(models, request.adapter_artifact.artifact_id)
        status = "ready" if raw.get("status") in {"ok", "ready", "healthy"} and loaded else "failed"
        return _runtime_result(
            runtime_name=self.runtime_name,
            status=status,
            request=request,
            details={"health": raw, "models": models, "adapter_loaded": loaded},
        )

    def infer(
        self,
        *,
        request: AdapterRuntimeRequest,
        plan: ServingPlan,
        chat_request: OpenAIChatRequest,
    ) -> MeshBrainModelClientResult:
        payload = {
            "model": request.adapter_artifact.artifact_id,
            "messages": list(chat_request.messages),
            "stream": False,
            "metadata": {
                **dict(chat_request.metadata),
                "mesh_brain_adapter_artifact_id": request.adapter_artifact.artifact_id,
                "mesh_brain_base_model_id": request.base_model_id,
                "mesh_brain_request_id": plan.request_id,
            },
        }
        raw = self._request_json("/v1/chat/completions", payload)
        return _parse_completion(raw=raw, request=request, plan=plan, chat_request=chat_request)

    def _get_json(self, path: str) -> dict[str, Any]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = urlrequest.Request(f"{self.base_url}{path}", headers=headers, method="GET")
        return self._open_json(http_request)

    def _request_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = urlrequest.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._open_json(http_request)

    def _open_json(self, http_request: urlrequest.Request) -> dict[str, Any]:
        try:
            with urlrequest.urlopen(http_request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"adapter runtime HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError, ValueError) as exc:
            raise RuntimeError(f"adapter runtime request failed: {exc}") from exc


def _runtime_result(
    *,
    runtime_name: str,
    status: str,
    request: AdapterRuntimeRequest,
    details: dict[str, Any],
) -> AdapterRuntimeResult:
    return AdapterRuntimeResult(
        runtime_name=runtime_name,
        status=status,
        adapter_artifact_id=request.adapter_artifact.artifact_id,
        base_model_id=request.base_model_id,
        serving_backend=request.serving_backend,
        recorded_at=utc_now(),
        details=details,
    )


def _adapter_outputs(artifact: ModelArtifact) -> list[dict[str, Any]]:
    outputs = artifact.metadata.get("posttraining_proof_outputs")
    if not isinstance(outputs, list):
        return []
    return [dict(output) for output in outputs if isinstance(output, dict)]


def _file_matches_digest(path: Path, expected: str) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    if stable_digest(text) == expected:
        return True
    try:
        return stable_digest(json.loads(text)) == expected
    except ValueError:
        return False


def _model_list_contains(payload: dict[str, Any], model_id: str) -> bool:
    data = payload.get("data")
    if not isinstance(data, list):
        return False
    return any(isinstance(item, dict) and item.get("id") == model_id for item in data)


def _parse_completion(
    *,
    raw: dict[str, Any],
    request: AdapterRuntimeRequest,
    plan: ServingPlan,
    chat_request: OpenAIChatRequest,
) -> MeshBrainModelClientResult:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("adapter runtime completion response missing choices")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = str(message.get("content") or "")
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    parsed_usage = {
        "prompt_tokens": int(usage.get("prompt_tokens", chat_request.estimated_tokens()) or 0),
        "completion_tokens": int(usage.get("completion_tokens", max(1, len(content) // 4)) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }
    if parsed_usage["total_tokens"] <= 0:
        parsed_usage["total_tokens"] = parsed_usage["prompt_tokens"] + parsed_usage["completion_tokens"]
    return MeshBrainModelClientResult(
        completion_id=str(raw.get("id") or f"mb_adapter_openai_completion_{stable_digest(raw)[:16]}"),
        request_id=plan.request_id,
        backend_name=request.serving_backend,
        model=str(raw.get("model") or request.adapter_artifact.artifact_id),
        content=content,
        finish_reason=str(first.get("finish_reason") or "unknown"),
        usage=parsed_usage,
        raw_response=raw,
    )
