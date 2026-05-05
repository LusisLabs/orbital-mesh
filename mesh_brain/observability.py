from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_runtime import AgentRuntimeResult
from .eval_jobs import EvalJobResult
from .runtime import stable_digest, utc_now
from .serving import ServingPlan


REQUIRED_OBSERVABILITY_LABELS = (
    "model",
    "adapter",
    "engine",
    "tenant",
    "task_type",
    "eval_outcome",
    "policy_route",
    "approval_route",
)


@dataclass
class MeshBrainMetricSample:
    name: str
    value: float
    labels: dict[str, str]
    help_text: str
    metric_type: str = "gauge"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MeshBrainObservation:
    observation_id: str
    recorded_at: str
    labels: dict[str, str]
    token_count: int
    cache_hit_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    token_throughput: float
    error_rate: float
    eval_outcome: str
    policy_route: str
    approval_route: str
    samples: list[MeshBrainMetricSample]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "recorded_at": self.recorded_at,
            "labels": dict(self.labels),
            "token_count": self.token_count,
            "cache_hit_rate": self.cache_hit_rate,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "token_throughput": self.token_throughput,
            "error_rate": self.error_rate,
            "eval_outcome": self.eval_outcome,
            "policy_route": self.policy_route,
            "approval_route": self.approval_route,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def build_mesh_brain_observation(
    *,
    serving_plan: ServingPlan,
    eval_job: EvalJobResult,
    agent_result: AgentRuntimeResult,
    engine_metrics: dict[str, dict[str, Any]] | None = None,
) -> MeshBrainObservation:
    token_count = int(serving_plan.trace.get("estimated_tokens", 0) or 0)
    pool_metrics = _pool_metrics(serving_plan=serving_plan, engine_metrics=engine_metrics or {})
    cache_hit_rate = _cache_hit_rate(serving_plan=serving_plan, pool_metrics=pool_metrics)
    latency_p50_ms = _metric(pool_metrics, "latency_p50_ms", default=_metric(pool_metrics, "latency_p95_ms", default=0.0))
    latency_p95_ms = _metric(pool_metrics, "latency_p95_ms", default=latency_p50_ms)
    latency_p99_ms = _metric(pool_metrics, "latency_p99_ms", default=latency_p95_ms)
    token_throughput = _metric(pool_metrics, "tokens_per_second", default=0.0)
    error_rate = _metric(pool_metrics, "error_rate", default=0.0)
    eval_outcome = eval_job.release_decision
    policy_route = _policy_route(agent_result)
    approval_route = _approval_route(agent_result)
    labels = {
        "model": serving_plan.model_artifact_id or "unresolved",
        "adapter": ",".join(serving_plan.adapter_artifact_ids) if serving_plan.adapter_artifact_ids else "none",
        "engine": serving_plan.backend_name,
        "tenant": serving_plan.route.tenant_id,
        "task_type": serving_plan.route.task_type,
        "eval_outcome": eval_outcome,
        "policy_route": policy_route,
        "approval_route": approval_route,
    }
    _validate_labels(labels)
    samples = [
        MeshBrainMetricSample(
            name="mesh_brain_requests_total",
            value=1.0,
            labels=labels,
            help_text="Mesh Brain serving requests by model, adapter, engine, tenant, task, eval outcome, and policy route",
            metric_type="counter",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_token_count",
            value=float(token_count),
            labels=labels,
            help_text="Estimated Mesh Brain request token count",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_cache_hit_rate",
            value=cache_hit_rate,
            labels=labels,
            help_text="Serving engine cache hit rate observed for Mesh Brain request path",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_latency_p50_ms",
            value=latency_p50_ms,
            labels=labels,
            help_text="Mesh Brain serving latency p50 in milliseconds for the selected backend route",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_latency_p95_ms",
            value=latency_p95_ms,
            labels=labels,
            help_text="Mesh Brain serving latency p95 in milliseconds for the selected backend route",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_latency_p99_ms",
            value=latency_p99_ms,
            labels=labels,
            help_text="Mesh Brain serving latency p99 in milliseconds for the selected backend route",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_token_throughput",
            value=token_throughput,
            labels=labels,
            help_text="Mesh Brain backend token throughput in tokens per second",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_error_rate",
            value=error_rate,
            labels=labels,
            help_text="Mesh Brain backend error rate for the selected route",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_eval_outcome",
            value=_outcome_value(eval_outcome),
            labels=labels,
            help_text="Release outcome for the evaluated Mesh Brain artifact: block=0, manual_review=0.5, canary=0.75, promote=1",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_policy_route",
            value=_policy_value(policy_route),
            labels=labels,
            help_text="Policy route for Mesh Brain tool path: block=0, approval_required=0.5, allow=1",
        ),
        MeshBrainMetricSample(
            name="mesh_brain_approval_route",
            value=_approval_value(approval_route),
            labels=labels,
            help_text="Approval route for Mesh Brain canary/tool path: blocked=0, not_required=0.5, operator_approval_required=1",
        ),
    ]
    return MeshBrainObservation(
        observation_id=f"mb_obs_{stable_digest({'labels': labels, 'tokens': token_count, 'cache': cache_hit_rate})[:12]}",
        recorded_at=utc_now(),
        labels=labels,
        token_count=token_count,
        cache_hit_rate=cache_hit_rate,
        latency_p50_ms=latency_p50_ms,
        latency_p95_ms=latency_p95_ms,
        latency_p99_ms=latency_p99_ms,
        token_throughput=token_throughput,
        error_rate=error_rate,
        eval_outcome=eval_outcome,
        policy_route=policy_route,
        approval_route=approval_route,
        samples=samples,
    )


def mesh_brain_samples_to_prometheus(samples: list[MeshBrainMetricSample]) -> str:
    grouped: dict[str, MeshBrainMetricSample] = {}
    lines: list[str] = []
    for sample in samples:
        if sample.name not in grouped:
            grouped[sample.name] = sample
            lines.append(f"# HELP {sample.name} {sample.help_text}")
            lines.append(f"# TYPE {sample.name} {sample.metric_type}")
        label_str = ",".join(f'{key}="{_escape(value)}"' for key, value in sorted(sample.labels.items()))
        lines.append(f"{sample.name}{{{label_str}}} {sample.value}")
    return "\n".join(lines) + "\n"


def mesh_brain_observation_to_prometheus(observation: MeshBrainObservation) -> str:
    return mesh_brain_samples_to_prometheus(observation.samples)


def write_mesh_brain_observability(*, observation: MeshBrainObservation, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    json_path = output_path / "mesh_brain_observation.json"
    prometheus_path = output_path / "mesh_brain_metrics.prom"
    json_path.write_text(_json(observation.to_dict()), encoding="utf-8")
    prometheus_path.write_text(mesh_brain_observation_to_prometheus(observation), encoding="utf-8")
    return {
        "mesh_brain_observation.json": str(json_path),
        "mesh_brain_metrics.prom": str(prometheus_path),
    }


def _pool_metrics(*, serving_plan: ServingPlan, engine_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pool_metrics = engine_metrics.get(serving_plan.route.hardware_tier, {}).get("metrics", {})
    return dict(pool_metrics) if isinstance(pool_metrics, dict) else {}


def _cache_hit_rate(*, serving_plan: ServingPlan, pool_metrics: dict[str, Any]) -> float:
    if "cache_hit_rate" in pool_metrics:
        return float(pool_metrics["cache_hit_rate"])
    if serving_plan.route.prefix_cache:
        return 1.0
    return 0.0


def _metric(metrics: dict[str, Any], key: str, *, default: float) -> float:
    value = metrics.get(key)
    if value is None:
        return default
    return float(value)


def _policy_route(agent_result: AgentRuntimeResult) -> str:
    if agent_result.status == "approval_required":
        return "approval_required"
    if agent_result.status.startswith("blocked"):
        return "block"
    return "allow"


def _approval_route(agent_result: AgentRuntimeResult) -> str:
    if agent_result.status == "approval_required":
        return "operator_approval_required"
    if agent_result.status.startswith("blocked"):
        return "blocked"
    return "not_required"


def _validate_labels(labels: dict[str, str]) -> None:
    missing = [label for label in REQUIRED_OBSERVABILITY_LABELS if not labels.get(label)]
    if missing:
        raise ValueError(f"missing Mesh Brain observability labels: {', '.join(missing)}")


def _outcome_value(outcome: str) -> float:
    return {
        "block": 0.0,
        "manual_review": 0.5,
        "canary": 0.75,
        "promote": 1.0,
    }.get(outcome, 0.0)


def _policy_value(policy_route: str) -> float:
    return {
        "block": 0.0,
        "approval_required": 0.5,
        "allow": 1.0,
    }.get(policy_route, 0.0)


def _approval_value(approval_route: str) -> float:
    return {
        "blocked": 0.0,
        "not_required": 0.5,
        "operator_approval_required": 1.0,
    }.get(approval_route, 0.0)


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
