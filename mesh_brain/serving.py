from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .inference_catalog import backend_capability_report, default_backend_for_hardware
from .runtime import InferenceRequestContext, ModelArtifact, ServingRoute, select_serving_route, stable_digest, utc_now


@dataclass
class ServingPool:
    pool_id: str
    hardware_tier: str
    backend_name: str
    health: str = "healthy"
    prefill_pool: str | None = None
    decode_pool: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TenantQuota:
    tenant_id: str
    max_requests_per_minute: int
    max_tokens_per_minute: int
    used_requests: int = 0
    used_tokens: int = 0

    def admit(self, *, estimated_tokens: int) -> bool:
        return (
            self.used_requests + 1 <= self.max_requests_per_minute
            and self.used_tokens + estimated_tokens <= self.max_tokens_per_minute
        )

    def consume(self, *, estimated_tokens: int) -> None:
        if not self.admit(estimated_tokens=estimated_tokens):
            raise ValueError("tenant quota exceeded")
        self.used_requests += 1
        self.used_tokens += estimated_tokens


@dataclass
class OpenAIChatRequest:
    tenant_id: str
    messages: list[dict[str, str]]
    task_type: str
    hardware_tier: str
    risk_level: str
    model: str = "mesh-brain"
    stream: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    response_format: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def estimated_tokens(self) -> int:
        message_chars = sum(len(str(message.get("content", ""))) for message in self.messages)
        tool_chars = sum(len(str(tool)) for tool in self.tools)
        return max(1, (message_chars + tool_chars) // 4)


@dataclass
class ServingPlan:
    request_id: str
    route: ServingRoute
    backend_name: str
    pool_id: str
    model_artifact_id: str | None
    adapter_artifact_ids: list[str]
    openai_compatible: bool
    streaming: bool
    structured_output: bool
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ServingExecution:
    plan: ServingPlan
    completion: dict[str, Any]
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "completion": dict(self.completion),
            "trace": dict(self.trace),
        }


class ChatCompletionClient(Protocol):
    def complete_chat(
        self,
        *,
        plan: ServingPlan,
        request: OpenAIChatRequest,
    ) -> Any: ...


class MeshBrainServingFabric:
    def __init__(
        self,
        *,
        pools: list[ServingPool],
        artifacts: list[ModelArtifact],
        quotas: dict[str, TenantQuota] | None = None,
        canary_weight: float = 0.0,
    ):
        self._pools = {pool.hardware_tier: pool for pool in pools}
        self._artifacts = list(artifacts)
        self._quotas = dict(quotas or {})
        self._canary_weight = canary_weight
        if not 0 <= self._canary_weight <= 1:
            raise ValueError("canary_weight must be between 0 and 1")

    def plan_chat_completion(self, request: OpenAIChatRequest) -> ServingPlan:
        quota = self._quotas.get(request.tenant_id)
        estimated_tokens = request.estimated_tokens()
        if quota is not None:
            quota.consume(estimated_tokens=estimated_tokens)
        pool = self._select_pool(request.hardware_tier)
        structured_output = request.response_format is not None or bool(request.tools)
        route = select_serving_route(
            context=InferenceRequestContext(
                tenant_id=request.tenant_id,
                hardware_tier=request.hardware_tier,
                task_type=request.task_type,
                risk_level=request.risk_level,
                sla=str(request.metadata.get("sla") or "interactive"),
                context_tokens=estimated_tokens,
                structured_output=structured_output,
            ),
            artifacts=self._select_artifacts_for_request(request),
        )
        capabilities = backend_capability_report(
            hardware_tier=request.hardware_tier,
            required_techniques=_required_techniques(route),
        )
        trace = {
            "request_id": _request_id(request),
            "tenant_id": request.tenant_id,
            "task_type": request.task_type,
            "risk_level": request.risk_level,
            "estimated_tokens": estimated_tokens,
            "backend_capabilities": capabilities,
            "quota": asdict(quota) if quota else None,
            "recorded_at": utc_now(),
        }
        return ServingPlan(
            request_id=trace["request_id"],
            route=route,
            backend_name=pool.backend_name,
            pool_id=pool.pool_id,
            model_artifact_id=route.model_artifact_id,
            adapter_artifact_ids=route.adapter_artifact_ids,
            openai_compatible=True,
            streaming=request.stream,
            structured_output=structured_output,
            trace=trace,
        )

    def execute_chat_completion(
        self,
        request: OpenAIChatRequest,
        *,
        client: ChatCompletionClient,
    ) -> ServingExecution:
        plan = self.plan_chat_completion(request)
        completion = client.complete_chat(plan=plan, request=request)
        completion_payload = completion.to_dict() if hasattr(completion, "to_dict") else dict(completion)
        return ServingExecution(
            plan=plan,
            completion=completion_payload,
            trace={
                **dict(plan.trace),
                "completion_id": completion_payload.get("completion_id"),
                "finish_reason": completion_payload.get("finish_reason"),
                "client_boundary": client.__class__.__name__,
                "completed_at": utc_now(),
            },
        )

    def hot_swap_adapter(self, artifact: ModelArtifact) -> None:
        if artifact.artifact_type not in {"tenant_adapter", "task_adapter", "policy_adapter", "quantized_checkpoint"}:
            raise ValueError("only adapter-like artifacts can be hot-swapped")
        self._artifacts = [existing for existing in self._artifacts if existing.artifact_id != artifact.artifact_id]
        self._artifacts.append(artifact)

    def rollback_adapter(self, *, current_artifact_id: str, rollback_artifact_id: str) -> None:
        current = _find_artifact(self._artifacts, current_artifact_id)
        rollback = _find_artifact(self._artifacts, rollback_artifact_id)
        current.state = "retired"
        rollback.state = "production"

    def engine_metrics(self) -> dict[str, dict[str, Any]]:
        return {
            hardware_tier: {
                "pool_id": pool.pool_id,
                "backend_name": pool.backend_name,
                "health": pool.health,
                "metrics": dict(pool.metrics),
                "prefill_pool": pool.prefill_pool,
                "decode_pool": pool.decode_pool,
            }
            for hardware_tier, pool in self._pools.items()
        }

    def _select_pool(self, hardware_tier: str) -> ServingPool:
        pool = self._pools.get(hardware_tier)
        if pool is None:
            backend = default_backend_for_hardware(hardware_tier)
            return ServingPool(pool_id=f"pool_{hardware_tier}", hardware_tier=hardware_tier, backend_name=backend.name)
        if pool.health != "healthy":
            raise ValueError(f"serving pool is not healthy: {pool.pool_id}")
        return pool

    def _select_artifacts_for_request(self, request: OpenAIChatRequest) -> list[ModelArtifact]:
        production = [
            artifact
            for artifact in self._artifacts
            if artifact.state == "production"
            and artifact.tenant_id in {None, request.tenant_id}
            and artifact.task_type in {None, request.task_type}
        ]
        canary = [
            artifact
            for artifact in self._artifacts
            if artifact.state == "canary"
            and artifact.tenant_id in {None, request.tenant_id}
            and artifact.task_type in {None, request.task_type}
        ]
        if canary and _canary_bucket(request) < self._canary_weight:
            return _prefer_artifacts(canary, production)
        return production


def build_serving_fabric_e2e(*, artifacts: list[ModelArtifact]) -> tuple[MeshBrainServingFabric, ServingPlan]:
    fabric = MeshBrainServingFabric(
        pools=[
            ServingPool(
                pool_id="nvidia-datacenter-primary",
                hardware_tier="nvidia_datacenter",
                backend_name="sgl-project/sglang",
                prefill_pool="prefill-a",
                decode_pool="decode-a",
                metrics={"latency_p95_ms": 850, "tokens_per_second": 120.0, "cache_hit_rate": 0.72},
            )
        ],
        artifacts=artifacts,
        quotas={"tenant_a": TenantQuota(tenant_id="tenant_a", max_requests_per_minute=10, max_tokens_per_minute=10000)},
        canary_weight=0.0,
    )
    plan = fabric.plan_chat_completion(
        OpenAIChatRequest(
            tenant_id="tenant_a",
            task_type="crops",
            hardware_tier="nvidia_datacenter",
            risk_level="high",
            stream=True,
            messages=[{"role": "user", "content": "Investigate search latency and propose bounded remediation."}],
            tools=[{"type": "function", "function": {"name": "kubernetes.get_deployment"}}],
            response_format={"type": "json_object"},
        )
    )
    return fabric, plan


def write_serving_plan(*, plan: ServingPlan, output_directory: str | Path) -> dict[str, str]:
    import json

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    plan_path = output_path / "serving_plan.json"
    trace_path = output_path / "request_trace.json"
    plan_path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    trace_path.write_text(json.dumps(plan.trace, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"serving_plan.json": str(plan_path), "request_trace.json": str(trace_path)}


def _required_techniques(route: ServingRoute) -> list[str]:
    techniques = ["prefix"] if route.prefix_cache else []
    if route.speculative_decoding:
        techniques.append("speculative")
    if route.constrained_decoding:
        techniques.append("constrained")
    if route.chunked_prefill:
        techniques.append("chunked prefill")
    if route.kv_aware_routing:
        techniques.append("KV")
    if route.continuous_batching:
        techniques.append("batching")
    return techniques


def _request_id(request: OpenAIChatRequest) -> str:
    return f"mb_req_{stable_digest({'tenant': request.tenant_id, 'messages': request.messages, 'task': request.task_type})[:16]}"


def _canary_bucket(request: OpenAIChatRequest) -> float:
    digest = stable_digest({"tenant": request.tenant_id, "messages": request.messages, "task": request.task_type})
    return int(digest[:8], 16) / 0xFFFFFFFF


def _prefer_artifacts(preferred: list[ModelArtifact], fallback: list[ModelArtifact]) -> list[ModelArtifact]:
    preferred_keys = {(artifact.artifact_type, artifact.tenant_id, artifact.task_type) for artifact in preferred}
    return preferred + [
        artifact
        for artifact in fallback
        if (artifact.artifact_type, artifact.tenant_id, artifact.task_type) not in preferred_keys
    ]


def _find_artifact(artifacts: list[ModelArtifact], artifact_id: str) -> ModelArtifact:
    for artifact in artifacts:
        if artifact.artifact_id == artifact_id:
            return artifact
    raise KeyError(artifact_id)
