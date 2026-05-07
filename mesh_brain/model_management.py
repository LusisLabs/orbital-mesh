from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .runtime import InferenceRequestContext, ModelArtifact, ReleaseGateResult, ServingRoute, new_model_artifact, select_serving_route, stable_digest, utc_now


@dataclass
class ArtifactLineage:
    artifact_id: str
    dataset_manifest_ids: list[str]
    training_run_id: str | None
    base_artifact_id: str | None
    eval_report_id: str | None
    signed_manifest_ref: str | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactAlias:
    alias: str
    artifact_id: str
    previous_artifact_id: str | None
    state: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromotionApproval:
    approval_id: str
    operator_id: str
    roles: list[str]
    approved_at: str
    evidence_refs: list[str]
    approved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelRouteRequest:
    tenant_id: str
    task_type: str
    hardware_tier: str
    risk_level: str
    sla: str = "interactive"
    context_tokens: int = 0
    structured_output: bool = False


@dataclass
class ModelRouteResolution:
    alias: str
    artifact_id: str | None
    route: ServingRoute
    lineage: ArtifactLineage | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "artifact_id": self.artifact_id,
            "route": self.route.to_dict(),
            "lineage": self.lineage.to_dict() if self.lineage else None,
        }


class MeshBrainModelCatalog:
    def __init__(self) -> None:
        self._artifacts: dict[str, ModelArtifact] = {}
        self._aliases: dict[str, ArtifactAlias] = {}

    def register_base_model(self, *, version: str, signed_manifest_ref: str, metadata: dict[str, Any] | None = None) -> ModelArtifact:
        artifact = new_model_artifact(
            artifact_type="base_model",
            version=version,
            signed_manifest_ref=signed_manifest_ref,
            metadata=dict(metadata or {}),
        )
        return self.register_artifact(artifact)

    def register_tenant_adapter(
        self,
        *,
        tenant_id: str,
        task_type: str,
        version: str,
        signed_manifest_ref: str,
        base_artifact_id: str | None = None,
        dataset_manifest_ids: list[str] | None = None,
        training_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelArtifact:
        return self.register_artifact(
            new_model_artifact(
                artifact_type="tenant_adapter",
                version=version,
                signed_manifest_ref=signed_manifest_ref,
                tenant_id=tenant_id,
                task_type=task_type,
                base_artifact_id=base_artifact_id,
                dataset_manifest_ids=dataset_manifest_ids,
                training_run_id=training_run_id,
                metadata=metadata,
            )
        )

    def register_task_adapter(
        self,
        *,
        task_type: str,
        version: str,
        signed_manifest_ref: str,
        dataset_manifest_ids: list[str] | None = None,
        training_run_id: str | None = None,
    ) -> ModelArtifact:
        return self.register_artifact(
            new_model_artifact(
                artifact_type="task_adapter",
                version=version,
                signed_manifest_ref=signed_manifest_ref,
                task_type=task_type,
                dataset_manifest_ids=dataset_manifest_ids,
                training_run_id=training_run_id,
            )
        )

    def register_quantized_variant(
        self,
        *,
        base_artifact_id: str,
        version: str,
        signed_manifest_ref: str,
        hardware_tier: str,
        quantization: str,
    ) -> ModelArtifact:
        return self.register_artifact(
            new_model_artifact(
                artifact_type="quantized_checkpoint",
                version=version,
                signed_manifest_ref=signed_manifest_ref,
                base_artifact_id=base_artifact_id,
                metadata={"hardware_tier": hardware_tier, "quantization": quantization},
            )
        )

    def register_artifact(self, artifact: ModelArtifact) -> ModelArtifact:
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def promote(
        self,
        *,
        artifact_id: str,
        gate_result: ReleaseGateResult,
        alias: str,
        approval: PromotionApproval | dict[str, Any] | None = None,
        rollback_manifest_ref: str | None = None,
    ) -> ArtifactAlias:
        artifact = self._require_artifact(artifact_id)
        if gate_result.candidate_artifact_id != artifact_id:
            raise ValueError("gate result does not belong to artifact")
        if gate_result.release_decision not in {"canary", "promote"}:
            raise ValueError("release gate blocks promotion")
        approval_record = _validate_promotion_controls(
            gate_result=gate_result,
            approval=approval,
            rollback_manifest_ref=rollback_manifest_ref,
        )
        previous = self._aliases.get(alias)
        previous_artifact_id = None
        if previous is not None:
            previous_artifact_id = previous.previous_artifact_id if previous.artifact_id == artifact.artifact_id else previous.artifact_id
        artifact.state = "canary" if gate_result.release_decision == "canary" else "production"
        artifact.eval_report_id = gate_result.gate_result_id
        artifact.rollback_artifact_id = previous_artifact_id
        artifact.metadata["promotion_approval"] = approval_record
        artifact.metadata["rollback_manifest_ref"] = rollback_manifest_ref
        artifact.metadata["promotion_gate_metrics"] = dict(gate_result.metrics)
        if artifact.state == "production" and previous and previous.artifact_id != artifact.artifact_id:
            self._artifacts[previous.artifact_id].state = "retired"
        alias_row = ArtifactAlias(
            alias=alias,
            artifact_id=artifact.artifact_id,
            previous_artifact_id=previous_artifact_id,
            state=artifact.state,
            updated_at=utc_now(),
        )
        self._aliases[alias] = alias_row
        return alias_row

    def rollback(self, *, alias: str) -> ArtifactAlias:
        current = self._aliases.get(alias)
        if current is None:
            raise KeyError(alias)
        current_artifact = self._require_artifact(current.artifact_id)
        if not current_artifact.rollback_artifact_id:
            raise ValueError("artifact has no rollback target")
        restored = self._require_artifact(current_artifact.rollback_artifact_id)
        current_artifact.state = "retired"
        restored.state = "production"
        alias_row = ArtifactAlias(
            alias=alias,
            artifact_id=restored.artifact_id,
            previous_artifact_id=current_artifact.artifact_id,
            state="production",
            updated_at=utc_now(),
        )
        self._aliases[alias] = alias_row
        return alias_row

    def retire(self, artifact_id: str) -> ModelArtifact:
        artifact = self._require_artifact(artifact_id)
        artifact.state = "retired"
        for alias, row in list(self._aliases.items()):
            if row.artifact_id == artifact_id:
                del self._aliases[alias]
        return artifact

    def lineage(self, artifact_id: str) -> ArtifactLineage:
        artifact = self._require_artifact(artifact_id)
        return ArtifactLineage(
            artifact_id=artifact.artifact_id,
            dataset_manifest_ids=list(artifact.dataset_manifest_ids),
            training_run_id=artifact.training_run_id,
            base_artifact_id=artifact.base_artifact_id,
            eval_report_id=artifact.eval_report_id,
            signed_manifest_ref=artifact.signed_manifest_ref,
            metadata=dict(artifact.metadata),
        )

    def resolve_route(self, request: ModelRouteRequest) -> ModelRouteResolution:
        alias = f"{request.tenant_id}/{request.task_type}"
        alias_row = self._aliases.get(alias)
        active_artifacts = [
            artifact
            for artifact in self._artifacts.values()
            if artifact.state in {"production", "canary"}
            and artifact.tenant_id in {None, request.tenant_id}
            and artifact.task_type in {None, request.task_type}
        ]
        route = select_serving_route(
            context=InferenceRequestContext(
                tenant_id=request.tenant_id,
                hardware_tier=request.hardware_tier,
                task_type=request.task_type,
                risk_level=request.risk_level,
                sla=request.sla,
                context_tokens=request.context_tokens,
                structured_output=request.structured_output,
            ),
            artifacts=active_artifacts,
        )
        artifact_id = alias_row.artifact_id if alias_row else None
        return ModelRouteResolution(
            alias=alias,
            artifact_id=artifact_id,
            route=route,
            lineage=self.lineage(artifact_id) if artifact_id else None,
        )

    def list_artifacts(self, *, state: str | None = None) -> list[ModelArtifact]:
        artifacts = list(self._artifacts.values())
        return [artifact for artifact in artifacts if artifact.state == state] if state else artifacts

    def snapshot(self) -> dict[str, Any]:
        return {
            "artifacts": {artifact_id: artifact.to_dict() for artifact_id, artifact in sorted(self._artifacts.items())},
            "aliases": {alias: row.to_dict() for alias, row in sorted(self._aliases.items())},
        }

    def write_snapshot(self, *, output_directory: str | Path) -> dict[str, str]:
        import json

        output_path = Path(output_directory)
        output_path.mkdir(parents=True, exist_ok=True)
        path = output_path / "model_catalog_snapshot.json"
        path.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return {"model_catalog_snapshot.json": str(path)}

    def _require_artifact(self, artifact_id: str) -> ModelArtifact:
        artifact = self._artifacts.get(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        return artifact


REQUIRED_PROMOTION_GATE_METRICS = (
    "model_kernel_passed",
    "live_serving_smoke_passed",
    "response_eval_passed",
    "judge_rubric_passed",
    "red_team_regression_passed",
    "curated_quality_training_passed",
)

REQUIRED_CURATED_QUALITY_COVERAGE = (
    "has_runtime_session",
    "has_runtime_event",
    "has_incident_corpus",
    "has_preference_rows",
    "has_eval_rows",
    "has_red_team_rows",
    "has_non_bootstrap_training_source",
)


def _validate_promotion_controls(
    *,
    gate_result: ReleaseGateResult,
    approval: PromotionApproval | dict[str, Any] | None,
    rollback_manifest_ref: str | None,
) -> dict[str, Any]:
    missing_gates = [
        gate
        for gate in REQUIRED_PROMOTION_GATE_METRICS
        if gate_result.metrics.get(gate) is not True
    ]
    if missing_gates:
        raise ValueError(f"promotion missing required gates: {', '.join(missing_gates)}")
    missing_quality_coverage = _missing_curated_quality_coverage(gate_result.metrics)
    if missing_quality_coverage:
        raise ValueError(f"promotion missing curated quality coverage: {', '.join(missing_quality_coverage)}")
    approval_record = approval.to_dict() if isinstance(approval, PromotionApproval) else dict(approval or {})
    if approval_record.get("approved") is not True:
        raise ValueError("promotion requires operator approval")
    if not str(approval_record.get("approval_id") or "").strip():
        raise ValueError("promotion approval requires approval_id")
    if not str(approval_record.get("operator_id") or "").strip():
        raise ValueError("promotion approval requires operator_id")
    roles = approval_record.get("roles")
    if not isinstance(roles, list) or not roles:
        raise ValueError("promotion approval requires operator roles")
    if not str(approval_record.get("approved_at") or "").strip():
        raise ValueError("promotion approval requires approved_at")
    if not rollback_manifest_ref:
        raise ValueError("promotion requires rollback metadata")
    return approval_record


def build_model_management_e2e(*, output_directory: str | Path) -> tuple[MeshBrainModelCatalog, ModelRouteResolution]:
    from .runtime import ReleaseGatePolicy, evaluate_release_gate

    catalog = MeshBrainModelCatalog()
    base = catalog.register_base_model(version="qwen-27b", signed_manifest_ref="sha256:base")
    base.state = "production"
    current = catalog.register_tenant_adapter(
        tenant_id="tenant_a",
        task_type="crops",
        version="dataset_v1",
        signed_manifest_ref="sha256:adapter-v1",
        base_artifact_id=base.artifact_id,
        dataset_manifest_ids=["dataset_v1"],
        training_run_id="train_v1",
    )
    gate = evaluate_release_gate(
        candidate_artifact_id=current.artifact_id,
        metrics={
            "critical_policy_regressions": 0,
            "unsafe_autonomous_action_rate_delta": 0,
            "schema_validity_delta": 0,
            "task_success_rate": 0.9,
            "canary_passed": True,
            **_required_gate_metrics(),
        },
        policy=ReleaseGatePolicy(task_success_threshold=0.8),
    )
    catalog.promote(
        artifact_id=current.artifact_id,
        gate_result=gate,
        alias="tenant_a/crops",
        approval=_approval("approval_model_management_e2e"),
        rollback_manifest_ref="rollback://tenant_a/crops/model-management-e2e",
    )
    quantized = catalog.register_quantized_variant(
        base_artifact_id=base.artifact_id,
        version="qwen-27b-nvfp4",
        signed_manifest_ref="sha256:quantized",
        hardware_tier="nvidia_datacenter",
        quantization="NVFP4",
    )
    quantized.state = "production"
    route = catalog.resolve_route(
        ModelRouteRequest(
            tenant_id="tenant_a",
            task_type="crops",
            hardware_tier="nvidia_datacenter",
            risk_level="high",
            structured_output=True,
        )
    )
    catalog.write_snapshot(output_directory=output_directory)
    return catalog, route


def deterministic_alias(tenant_id: str, task_type: str) -> str:
    return f"{tenant_id}/{task_type}"


def artifact_fingerprint(artifact: ModelArtifact) -> str:
    return str(stable_digest(artifact.to_dict()))


def _required_gate_metrics() -> dict[str, Any]:
    return {
        **{gate: True for gate in REQUIRED_PROMOTION_GATE_METRICS},
        "quality_source_coverage": _curated_quality_source_coverage(),
    }


def _missing_curated_quality_coverage(metrics: dict[str, Any]) -> list[str]:
    coverage = metrics.get("quality_source_coverage")
    if not isinstance(coverage, dict):
        return list(REQUIRED_CURATED_QUALITY_COVERAGE)
    return [key for key in REQUIRED_CURATED_QUALITY_COVERAGE if coverage.get(key) is not True]


def _curated_quality_source_coverage() -> dict[str, bool]:
    return {key: True for key in REQUIRED_CURATED_QUALITY_COVERAGE}


def _approval(approval_id: str) -> PromotionApproval:
    return PromotionApproval(
        approval_id=approval_id,
        operator_id="operator_1",
        roles=["approver"],
        approved_at=utc_now(),
        evidence_refs=["mesh://approval/local-e2e"],
    )
