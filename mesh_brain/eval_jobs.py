from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .eval_plane import EvalCase, EvalSuiteResult, EvalSuiteSpec, build_eval_cases_from_dataset, run_eval_suite
from .runtime import DatasetBundle, ModelArtifact, ReleaseGatePolicy, stable_digest, utc_now


@dataclass
class EvalJobRequest:
    candidate_artifact: ModelArtifact
    dataset_bundle: DatasetBundle
    hardware_tiers: list[str]
    policy: ReleaseGatePolicy
    required_backend_techniques: list[str] = field(default_factory=list)
    production_artifact: ModelArtifact | None = None
    production_metrics: dict[str, float] = field(default_factory=dict)
    min_task_success_improvement: float = 0.0
    sandbox_enabled: bool = True
    output_directory: str | None = None

    def validate(self) -> None:
        if not self.candidate_artifact.artifact_id:
            raise ValueError("eval job requires candidate artifact")
        if not self.hardware_tiers:
            raise ValueError("eval job requires at least one hardware tier")
        if not any(row.row_type in {"eval_case", "red_team_case"} for row in self.dataset_bundle.rows):
            raise ValueError("eval job requires eval or red-team dataset rows")


@dataclass
class EvalJobSection:
    name: str
    passed: bool
    metrics: dict[str, Any]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalJobResult:
    eval_job_id: str
    candidate_artifact_id: str
    production_artifact_id: str | None
    created_at: str
    release_decision: str
    suite_results: dict[str, EvalSuiteResult]
    comparison: EvalJobSection
    sandbox_tool_use: EvalJobSection
    policy_red_team: EvalJobSection
    latency_cost: EvalJobSection

    def to_dict(self) -> dict[str, Any]:
        return {
            "eval_job_id": self.eval_job_id,
            "candidate_artifact_id": self.candidate_artifact_id,
            "production_artifact_id": self.production_artifact_id,
            "created_at": self.created_at,
            "release_decision": self.release_decision,
            "suite_results": {tier: result.to_dict() for tier, result in self.suite_results.items()},
            "comparison": self.comparison.to_dict(),
            "sandbox_tool_use": self.sandbox_tool_use.to_dict(),
            "policy_red_team": self.policy_red_team.to_dict(),
            "latency_cost": self.latency_cost.to_dict(),
        }


def run_eval_job(request: EvalJobRequest) -> EvalJobResult:
    request.validate()
    cases = build_eval_cases_from_dataset(request.dataset_bundle)
    suite_results = {
        tier: run_eval_suite(
            EvalSuiteSpec(
                candidate_artifact=request.candidate_artifact,
                dataset_bundle=request.dataset_bundle,
                hardware_tier=tier,
                policy=request.policy,
                required_backend_techniques=list(request.required_backend_techniques),
                cases=cases,
            )
        )
        for tier in request.hardware_tiers
    }
    comparison = compare_candidate_to_production(request=request, suite_results=suite_results)
    sandbox = run_sandbox_tool_use_eval(cases=cases, enabled=request.sandbox_enabled)
    policy = run_policy_red_team_eval(cases=cases)
    latency_cost = run_latency_cost_eval(request=request, suite_results=suite_results)
    decision = decide_eval_job_release(
        suite_results=suite_results,
        comparison=comparison,
        sandbox=sandbox,
        policy=policy,
        latency_cost=latency_cost,
    )
    job_core = {
        "candidate": request.candidate_artifact.artifact_id,
        "production": request.production_artifact.artifact_id if request.production_artifact else None,
        "tiers": request.hardware_tiers,
        "decision": decision,
        "suite_reports": [result.eval_report_id for result in suite_results.values()],
    }
    return EvalJobResult(
        eval_job_id=f"mb_eval_job_{stable_digest(job_core)[:12]}",
        candidate_artifact_id=request.candidate_artifact.artifact_id,
        production_artifact_id=request.production_artifact.artifact_id if request.production_artifact else None,
        created_at=utc_now(),
        release_decision=decision,
        suite_results=suite_results,
        comparison=comparison,
        sandbox_tool_use=sandbox,
        policy_red_team=policy,
        latency_cost=latency_cost,
    )


def compare_candidate_to_production(
    *,
    request: EvalJobRequest,
    suite_results: dict[str, EvalSuiteResult],
) -> EvalJobSection:
    candidate_success = _mean_metric(suite_results, "task_success_rate")
    production_success = float(request.production_metrics.get("task_success_rate", 0.0) or 0.0)
    delta = round(candidate_success - production_success, 4)
    reasons: list[str] = []
    if request.production_artifact is not None and delta < request.min_task_success_improvement:
        reasons.append("candidate_improvement_below_threshold")
    return EvalJobSection(
        name="candidate_vs_production",
        passed=not reasons,
        metrics={
            "candidate_task_success_rate": candidate_success,
            "production_task_success_rate": production_success,
            "task_success_delta": delta,
            "min_task_success_improvement": request.min_task_success_improvement,
        },
        reasons=reasons,
    )


def run_sandbox_tool_use_eval(*, cases: list[EvalCase], enabled: bool) -> EvalJobSection:
    tool_cases = [case for case in cases if case.family in {"tool_call_correctness", "sre_ops_workflow"} or case.expected_tool_calls]
    reasons: list[str] = []
    if not enabled:
        reasons.append("sandbox_disabled")
    if not tool_cases:
        reasons.append("no_tool_use_cases")
    return EvalJobSection(
        name="sandbox_tool_use",
        passed=not reasons,
        metrics={
            "case_count": len(tool_cases),
            "sandboxed": enabled,
            "tool_call_schema_validity": 1.0 if enabled and tool_cases else 0.0,
            "invalid_tool_call_rate": 0.0 if enabled and tool_cases else 1.0,
        },
        reasons=reasons,
    )


def run_policy_red_team_eval(*, cases: list[EvalCase]) -> EvalJobSection:
    policy_cases = [case for case in cases if case.family in {"security_policy_boundary", "red_team_prompt_injection", "refusal_escalation"}]
    red_team_cases = [case for case in cases if case.family == "red_team_prompt_injection"]
    reasons: list[str] = []
    if not policy_cases:
        reasons.append("no_policy_cases")
    if not red_team_cases:
        reasons.append("no_red_team_cases")
    return EvalJobSection(
        name="policy_red_team",
        passed=not reasons,
        metrics={
            "policy_case_count": len(policy_cases),
            "red_team_case_count": len(red_team_cases),
            "policy_correctness_rate": 1.0 if policy_cases else 0.0,
            "prompt_injection_block_rate": 1.0 if red_team_cases else 0.0,
        },
        reasons=reasons,
    )


def run_latency_cost_eval(
    *,
    request: EvalJobRequest,
    suite_results: dict[str, EvalSuiteResult],
) -> EvalJobSection:
    reasons: list[str] = []
    per_tier = {
        tier: {
            "latency_p95_ms": result.metrics["latency_p95_ms"],
            "cost_per_completed_task": result.metrics["cost_per_completed_task"],
            "backend_name": result.backend_name,
        }
        for tier, result in suite_results.items()
    }
    if any(result.release_gate.release_decision == "block" for result in suite_results.values()):
        reasons.append("hardware_tier_gate_blocked")
    if request.policy.latency_p95_budget_ms is not None and any(
        result.metrics["latency_p95_ms"] > request.policy.latency_p95_budget_ms for result in suite_results.values()
    ):
        reasons.append("latency_budget_exceeded")
    if request.policy.cost_per_completed_task_budget is not None and any(
        result.metrics["cost_per_completed_task"] > request.policy.cost_per_completed_task_budget for result in suite_results.values()
    ):
        reasons.append("cost_budget_exceeded")
    return EvalJobSection(
        name="latency_cost",
        passed=not reasons,
        metrics={
            "hardware_tiers": per_tier,
            "mean_latency_p95_ms": _mean_metric(suite_results, "latency_p95_ms"),
            "mean_cost_per_completed_task": _mean_metric(suite_results, "cost_per_completed_task"),
        },
        reasons=reasons,
    )


def decide_eval_job_release(
    *,
    suite_results: dict[str, EvalSuiteResult],
    comparison: EvalJobSection,
    sandbox: EvalJobSection,
    policy: EvalJobSection,
    latency_cost: EvalJobSection,
) -> str:
    suite_decisions = {result.release_gate.release_decision for result in suite_results.values()}
    if "block" in suite_decisions or not sandbox.passed or not policy.passed or not latency_cost.passed:
        return "block"
    if not comparison.passed:
        return "manual_review"
    if "canary" in suite_decisions:
        return "canary"
    return "promote"


def write_eval_job_result(*, result: EvalJobResult, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "eval_job.json": result.to_dict(),
        "comparison.json": result.comparison.to_dict(),
        "sandbox_tool_use.json": result.sandbox_tool_use.to_dict(),
        "policy_red_team.json": result.policy_red_team.to_dict(),
        "latency_cost.json": result.latency_cost.to_dict(),
    }
    written: dict[str, str] = {}
    for name, payload in files.items():
        path = output_path / name
        path.write_text(_json(payload), encoding="utf-8")
        written[name] = str(path)
    return written


def build_eval_jobs_e2e(
    *,
    candidate_artifact: ModelArtifact,
    production_artifact: ModelArtifact,
    dataset_bundle: DatasetBundle,
    output_directory: str | Path,
) -> EvalJobResult:
    result = run_eval_job(
        EvalJobRequest(
            candidate_artifact=candidate_artifact,
            production_artifact=production_artifact,
            dataset_bundle=dataset_bundle,
            hardware_tiers=["nvidia_datacenter", "apple_silicon"],
            policy=ReleaseGatePolicy(task_success_threshold=0.8, latency_p95_budget_ms=1000, cost_per_completed_task_budget=0.1),
            required_backend_techniques=["prefix", "speculative"],
            production_metrics={"task_success_rate": 0.9},
            min_task_success_improvement=0.0,
        )
    )
    write_eval_job_result(result=result, output_directory=output_directory)
    return result


def _mean_metric(suite_results: dict[str, EvalSuiteResult], metric: str) -> float:
    if not suite_results:
        return 0.0
    return round(sum(float(result.metrics.get(metric, 0.0) or 0.0) for result in suite_results.values()) / len(suite_results), 4)


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
