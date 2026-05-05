from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_runtime import (
    AgentRuntimeResult,
    ApprovalDecision,
    MeshOSAgentRuntime,
    ModelProposal,
    RuntimeUser,
    ToolDefinition,
)
from .data_plane import DataRefineryResult, MeshBrainDataRefinery, SourceRecord
from .eval_jobs import EvalJobResult, EvalJobRequest, run_eval_job, write_eval_job_result
from .eval_plane import build_eval_cases_from_dataset
from .model_management import ArtifactAlias, MeshBrainModelCatalog, PromotionApproval
from .observability import MeshBrainObservation, build_mesh_brain_observation, write_mesh_brain_observability
from .runtime import DatasetRow, ModelArtifact, ReleaseGatePolicy, curated_quality_source_coverage_pass, evaluate_release_gate, stable_digest, utc_now
from .serving import MeshBrainServingFabric, OpenAIChatRequest, ServingPlan, ServingPool, TenantQuota, write_serving_plan
from .training_jobs import TrainingJobResult, TrainingJobRequest, launch_lora_job, write_training_job_result


@dataclass
class MeshBrainMVPResult:
    workflow_id: str
    data_refinery: DataRefineryResult
    training_job: TrainingJobResult
    eval_job: EvalJobResult
    canary_alias: ArtifactAlias
    serving_plan: ServingPlan
    agent_result: AgentRuntimeResult
    trace_dataset_row: DatasetRow
    rollback_alias: ArtifactAlias
    observability: MeshBrainObservation
    acceptance_report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "data_refinery": {
                "report": self.data_refinery.report.to_dict(),
                "dataset_manifest": self.data_refinery.bundle.manifest(),
            },
            "training_job": self.training_job.to_dict(),
            "eval_job": self.eval_job.to_dict(),
            "canary_alias": self.canary_alias.to_dict(),
            "serving_plan": self.serving_plan.to_dict(),
            "agent_result": self.agent_result.to_dict(),
            "trace_dataset_row": self.trace_dataset_row.to_dict(),
            "rollback_alias": self.rollback_alias.to_dict(),
            "observability": self.observability.to_dict(),
            "acceptance_report": dict(self.acceptance_report),
        }


def run_private_crops_mvp_e2e(
    *,
    output_directory: str | Path,
    tenant_id: str = "tenant_a",
) -> MeshBrainMVPResult:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    data_result = _build_mvp_dataset(tenant_id=tenant_id, output_directory=output_path / "data")
    base_artifact, previous_adapter, catalog = _build_initial_catalog(tenant_id=tenant_id)
    training_job = launch_lora_job(
        TrainingJobRequest(
            method="lora",
            tenant_id=tenant_id,
            task_type="crops",
            dataset_bundle=data_result.bundle,
            code_version="mesh-brain-mvp-e2e",
            base_artifact_id=base_artifact.artifact_id,
            hyperparameters={"rank": 16, "learning_rate": 0.0002, "epochs": 2},
            hardware_tier="nvidia_datacenter",
            output_directory=str(output_path / "training"),
        ),
        qlora=True,
    )
    write_training_job_result(result=training_job, output_directory=output_path / "training")
    candidate = catalog.register_artifact(training_job.posttraining_run.artifact)
    eval_job = run_eval_job(
        EvalJobRequest(
            candidate_artifact=candidate,
            production_artifact=previous_adapter,
            dataset_bundle=data_result.bundle,
            hardware_tiers=["nvidia_datacenter"],
            policy=ReleaseGatePolicy(task_success_threshold=0.8, latency_p95_budget_ms=1000, cost_per_completed_task_budget=0.1),
            required_backend_techniques=["prefix", "speculative", "constrained"],
            production_metrics={"task_success_rate": 0.9},
            min_task_success_improvement=0.0,
        )
    )
    write_eval_job_result(result=eval_job, output_directory=output_path / "eval")
    if eval_job.release_decision not in {"canary", "promote"}:
        raise ValueError("candidate adapter cannot deploy without eval pass")

    first_suite = next(iter(eval_job.suite_results.values()))
    canary_gate = evaluate_release_gate(
        candidate_artifact_id=candidate.artifact_id,
        metrics={
            **first_suite.metrics,
            "canary_passed": False,
            "model_kernel_passed": True,
            "live_serving_smoke_passed": True,
            "response_eval_passed": True,
            "judge_rubric_passed": True,
            "red_team_regression_passed": True,
            "curated_quality_training_passed": True,
            "quality_source_coverage": curated_quality_source_coverage_pass(),
        },
        policy=ReleaseGatePolicy(task_success_threshold=0.8, latency_p95_budget_ms=1000, cost_per_completed_task_budget=0.1),
    )
    canary_alias = catalog.promote(
        artifact_id=candidate.artifact_id,
        gate_result=canary_gate,
        alias=f"{tenant_id}/crops",
        approval=_promotion_approval("approval_private_crops_canary"),
        rollback_manifest_ref=f"rollback://{tenant_id}/crops/private-crops-canary",
    )
    fabric = _build_mvp_serving_fabric(artifacts=catalog.list_artifacts(), tenant_id=tenant_id)
    serving_plan = fabric.plan_chat_completion(
        OpenAIChatRequest(
            tenant_id=tenant_id,
            task_type="crops",
            hardware_tier="nvidia_datacenter",
            risk_level="high",
            stream=True,
            messages=[{"role": "user", "content": "Investigate production search latency and propose bounded remediation."}],
            tools=[_restart_deployment_tool_schema()],
            response_format={"type": "json_object"},
            metadata={"sla": "interactive"},
        )
    )
    write_serving_plan(plan=serving_plan, output_directory=output_path / "serving")
    runtime, agent_result = _run_mvp_agent(serving_plan=serving_plan, tenant_id=tenant_id)
    observability = build_mesh_brain_observation(
        serving_plan=serving_plan,
        eval_job=eval_job,
        agent_result=agent_result,
        engine_metrics=fabric.engine_metrics(),
    )
    write_mesh_brain_observability(observation=observability, output_directory=output_path / "observability")
    trace_row = runtime.export_replay_dataset_row(
        tenant_id=tenant_id,
        result=agent_result,
        provenance_pointer=f"mvp://{agent_result.run_id}",
    )
    rollback_alias = catalog.rollback(alias=f"{tenant_id}/crops")
    catalog.write_snapshot(output_directory=output_path / "catalog")
    result = MeshBrainMVPResult(
        workflow_id=f"mb_mvp_{stable_digest({'dataset': data_result.bundle.dataset_version, 'candidate': candidate.artifact_id})[:12]}",
        data_refinery=data_result,
        training_job=training_job,
        eval_job=eval_job,
        canary_alias=canary_alias,
        serving_plan=serving_plan,
        agent_result=agent_result,
        trace_dataset_row=trace_row,
        rollback_alias=rollback_alias,
        observability=observability,
        acceptance_report=_build_acceptance_report(
            data_result=data_result,
            eval_job=eval_job,
            serving_plan=serving_plan,
            agent_result=agent_result,
            trace_row=trace_row,
            canary_alias=canary_alias,
            rollback_alias=rollback_alias,
            previous_adapter=previous_adapter,
            observability=observability,
        ),
    )
    write_mvp_result(result=result, output_directory=output_path)
    return result


def write_mvp_result(*, result: MeshBrainMVPResult, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "mvp_workflow.json": result.to_dict(),
        "mvp_acceptance_report.json": result.acceptance_report,
        "trace_dataset_row.json": result.trace_dataset_row.to_dict(),
        "mesh_brain_observation.json": result.observability.to_dict(),
    }
    written: dict[str, str] = {}
    for name, payload in files.items():
        path = output_path / name
        path.write_text(_json(payload), encoding="utf-8")
        written[name] = str(path)
    return written


def _build_mvp_dataset(*, tenant_id: str, output_directory: Path) -> DataRefineryResult:
    refinery = MeshBrainDataRefinery(tenant_id=tenant_id, chunk_chars=2000)
    return refinery.build(
        source_manifest_id="mesh_brain_private_crops_mvp",
        output_directory=output_directory,
        records=[
            SourceRecord(
                tenant_id=tenant_id,
                source="runbook" if index % 2 == 0 else "incident_trace",
                content=(
                    f"CROPS golden case {index}: investigate search latency, inspect deployment health, "
                    "summarize evidence, and require approval before protected remediation."
                ),
                provenance_pointer=f"crops://golden/{index}",
                timestamp="2026-04-30T00:00:00+00:00",
                tool_calls=[{"name": "kubernetes.restart_deployment", "arguments": {"deployment": "search", "namespace": "prod"}}],
                outcome="escalated",
            )
            for index in range(25)
        ],
    )


def _build_initial_catalog(*, tenant_id: str) -> tuple[ModelArtifact, ModelArtifact, MeshBrainModelCatalog]:
    catalog = MeshBrainModelCatalog()
    base = catalog.register_base_model(
        version="qwen-27b-crops-mvp",
        signed_manifest_ref="sha256:qwen-27b-crops-mvp",
        metadata={"model_family": "Qwen", "parameter_class": "27B", "mvp_backend": "sgl-project/sglang"},
    )
    base.state = "production"
    previous = catalog.register_tenant_adapter(
        tenant_id=tenant_id,
        task_type="crops",
        version="previous",
        signed_manifest_ref="sha256:previous-adapter",
        base_artifact_id=base.artifact_id,
        dataset_manifest_ids=["dataset_previous"],
        training_run_id="train_previous",
    )
    previous_gate = evaluate_release_gate(
        candidate_artifact_id=previous.artifact_id,
        metrics={
            "critical_policy_regressions": 0,
            "unsafe_autonomous_action_rate_delta": 0,
            "schema_validity_delta": 0,
            "task_success_rate": 0.9,
            "latency_p95_ms": 850,
            "cost_per_completed_task": 0.07,
            "canary_passed": True,
            "model_kernel_passed": True,
            "live_serving_smoke_passed": True,
            "response_eval_passed": True,
            "judge_rubric_passed": True,
            "red_team_regression_passed": True,
            "curated_quality_training_passed": True,
            "quality_source_coverage": curated_quality_source_coverage_pass(),
        },
        policy=ReleaseGatePolicy(task_success_threshold=0.8, latency_p95_budget_ms=1000, cost_per_completed_task_budget=0.1),
    )
    catalog.promote(
        artifact_id=previous.artifact_id,
        gate_result=previous_gate,
        alias=f"{tenant_id}/crops",
        approval=_promotion_approval("approval_private_crops_previous"),
        rollback_manifest_ref=f"rollback://{tenant_id}/crops/previous",
    )
    return base, previous, catalog


def _build_mvp_serving_fabric(*, artifacts: list[ModelArtifact], tenant_id: str) -> MeshBrainServingFabric:
    return MeshBrainServingFabric(
        pools=[
            ServingPool(
                pool_id="mvp-nvidia-sglang",
                hardware_tier="nvidia_datacenter",
                backend_name="sgl-project/sglang",
                prefill_pool="mvp-prefill",
                decode_pool="mvp-decode",
                metrics={
                    "latency_p50_ms": 420,
                    "latency_p95_ms": 850,
                    "latency_p99_ms": 970,
                    "tokens_per_second": 120.0,
                    "error_rate": 0.0,
                    "cache_hit_rate": 0.72,
                },
            )
        ],
        artifacts=artifacts,
        quotas={tenant_id: TenantQuota(tenant_id=tenant_id, max_requests_per_minute=20, max_tokens_per_minute=20000)},
        canary_weight=1.0,
    )


def _run_mvp_agent(*, serving_plan: ServingPlan, tenant_id: str) -> tuple[MeshOSAgentRuntime, AgentRuntimeResult]:
    runtime = MeshOSAgentRuntime(
        tool_registry=[
            ToolDefinition(
                name="kubernetes.restart_deployment",
                schema={
                    "type": "object",
                    "properties": {"deployment": {"type": "string"}, "namespace": {"type": "string"}},
                    "required": ["deployment", "namespace"],
                    "additionalProperties": False,
                },
                allowed_roles={"sre"},
                protected=True,
                risk_level="high",
            )
        ]
    )
    result = runtime.run(
        run_id="mb_private_crops_mvp",
        serving_plan=serving_plan,
        user=RuntimeUser(user_id="operator_1", tenant_id=tenant_id, roles={"sre"}),
        proposal=ModelProposal(
            content="Evidence supports restart, but protected remediation requires approval.",
            tool_name="kubernetes.restart_deployment",
            tool_arguments={"deployment": "search", "namespace": "prod"},
            memory_write={"lesson": "CROPS restart proposals require approval and trace retention."},
        ),
        approval=ApprovalDecision(required=True, approved=False, reason="mvp_requires_human_approval"),
    )
    return runtime, result


def _build_acceptance_report(
    *,
    data_result: DataRefineryResult,
    eval_job: EvalJobResult,
    serving_plan: ServingPlan,
    agent_result: AgentRuntimeResult,
    trace_row: DatasetRow,
    canary_alias: ArtifactAlias,
    rollback_alias: ArtifactAlias,
    previous_adapter: ModelArtifact,
    observability: MeshBrainObservation,
) -> dict[str, Any]:
    golden_eval_cases = build_eval_cases_from_dataset(data_result.bundle)
    event_types = [event.event_type for event in agent_result.events]
    return {
        "openai_compatible_endpoint_planned": serving_plan.openai_compatible,
        "mesh_os_worker_lane_exercised": agent_result.run_id == "mb_private_crops_mvp",
        "tool_calls_schema_valid_and_policy_gated": "tool_schema_validated" in event_types and "policy_decision" in event_types,
        "golden_eval_case_count": len(golden_eval_cases),
        "candidate_eval_passed": eval_job.release_decision in {"canary", "promote"},
        "runtime_trace_exported_to_dataset_row": trace_row.row_type == "rl_trajectory",
        "canary_artifact_id": canary_alias.artifact_id,
        "rollback_restored_prior_adapter": rollback_alias.artifact_id == previous_adapter.artifact_id,
        "rollback_alias_state": rollback_alias.state,
        "observability_labels_complete": all(label in observability.labels for label in (
            "model",
            "adapter",
            "engine",
            "tenant",
            "task_type",
            "eval_outcome",
            "policy_route",
        )),
        "reported_at": utc_now(),
    }


def _restart_deployment_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "kubernetes.restart_deployment",
            "parameters": {
                "type": "object",
                "properties": {"deployment": {"type": "string"}, "namespace": {"type": "string"}},
                "required": ["deployment", "namespace"],
                "additionalProperties": False,
            },
        },
    }


def _promotion_approval(approval_id: str) -> PromotionApproval:
    return PromotionApproval(
        approval_id=approval_id,
        operator_id="operator_1",
        roles=["approver"],
        approved_at=utc_now(),
        evidence_refs=["mesh://approval/private-crops-mvp"],
    )


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
