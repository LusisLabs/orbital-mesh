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
    eval_outcome: str
    policy_route: str
    samples: list[MeshBrainMetricSample]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "recorded_at": self.recorded_at,
            "labels": dict(self.labels),
            "token_count": self.token_count,
            "cache_hit_rate": self.cache_hit_rate,
            "eval_outcome": self.eval_outcome,
            "policy_route": self.policy_route,
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
    cache_hit_rate = _cache_hit_rate(serving_plan=serving_plan, engine_metrics=engine_metrics or {})
    eval_outcome = eval_job.release_decision
    policy_route = _policy_route(agent_result)
    labels = {
        "model": serving_plan.model_artifact_id or "unresolved",
        "adapter": ",".join(serving_plan.adapter_artifact_ids) if serving_plan.adapter_artifact_ids else "none",
        "engine": serving_plan.backend_name,
        "tenant": serving_plan.route.tenant_id,
        "task_type": serving_plan.route.task_type,
        "eval_outcome": eval_outcome,
        "policy_route": policy_route,
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
    ]
    return MeshBrainObservation(
        observation_id=f"mb_obs_{stable_digest({'labels': labels, 'tokens': token_count, 'cache': cache_hit_rate})[:12]}",
        recorded_at=utc_now(),
        labels=labels,
        token_count=token_count,
        cache_hit_rate=cache_hit_rate,
        eval_outcome=eval_outcome,
        policy_route=policy_route,
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


def _cache_hit_rate(*, serving_plan: ServingPlan, engine_metrics: dict[str, dict[str, Any]]) -> float:
    pool_metrics = engine_metrics.get(serving_plan.route.hardware_tier, {}).get("metrics", {})
    if isinstance(pool_metrics, dict) and "cache_hit_rate" in pool_metrics:
        return float(pool_metrics["cache_hit_rate"])
    if serving_plan.route.prefix_cache:
        return 1.0
    return 0.0


def _policy_route(agent_result: AgentRuntimeResult) -> str:
    if agent_result.status == "approval_required":
        return "approval_required"
    if agent_result.status.startswith("blocked"):
        return "block"
    return "allow"


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


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
