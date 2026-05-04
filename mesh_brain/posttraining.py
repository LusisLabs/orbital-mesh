from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .runtime import DatasetBundle, ModelArtifact, TrainingManifest, new_model_artifact, stable_digest, utc_now


TRAINING_METHODS = {"sft", "lora", "qlora", "dpo", "ipo", "kto", "agent_rl", "qat"}
TENANT_SCOPED_ARTIFACT_TYPES = {"tenant_adapter", "task_adapter", "policy_adapter"}


@dataclass
class SharedAdapterApproval:
    approval_id: str
    customer_approved: bool
    legal_approved: bool
    approved_at: str
    evidence_refs: list[str]

    def valid(self) -> bool:
        return self.customer_approved and self.legal_approved and bool(self.evidence_refs)


@dataclass
class TrainingJobSpec:
    method: str
    tenant_id: str
    task_type: str
    dataset_bundle: DatasetBundle
    code_version: str
    artifact_type: str = "tenant_adapter"
    base_artifact_id: str | None = None
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    shared_adapter: bool = False
    shared_adapter_approval: SharedAdapterApproval | None = None

    def validate(self) -> None:
        if self.method not in TRAINING_METHODS:
            raise ValueError(f"unsupported training method: {self.method}")
        if self.artifact_type not in {
            "tenant_adapter",
            "task_adapter",
            "policy_adapter",
            "quantized_checkpoint",
            "draft_model",
            "reward_model",
            "judge_config",
        }:
            raise ValueError(f"unsupported posttraining artifact_type: {self.artifact_type}")
        tenant_ids = {row.tenant_id for row in self.dataset_bundle.rows if not row.excluded_from_training}
        if tenant_ids - {self.tenant_id}:
            raise ValueError("training rows contain another tenant")
        if not tenant_ids:
            raise ValueError("training job has no trainable rows")
        if self.shared_adapter and (self.shared_adapter_approval is None or not self.shared_adapter_approval.valid()):
            raise ValueError("shared adapters require customer and legal approval evidence")
        if self.artifact_type in TENANT_SCOPED_ARTIFACT_TYPES and not self.shared_adapter and not self.tenant_id:
            raise ValueError("tenant-scoped adapters require tenant_id")


@dataclass
class LineageNode:
    node_id: str
    node_type: str
    refs: list[str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RollbackManifest:
    artifact_id: str
    previous_artifact_id: str | None
    routing_alias: str
    restore_steps: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PosttrainingRun:
    training_manifest: TrainingManifest
    artifact: ModelArtifact
    lineage_graph: list[LineageNode]
    rollback_manifest: RollbackManifest
    model_card: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "training_manifest": self.training_manifest.to_dict(),
            "artifact": self.artifact.to_dict(),
            "lineage_graph": [node.to_dict() for node in self.lineage_graph],
            "rollback_manifest": self.rollback_manifest.to_dict(),
            "model_card": dict(self.model_card),
        }


def plan_posttraining_run(
    *,
    spec: TrainingJobSpec,
    previous_artifact_id: str | None = None,
    routing_alias: str | None = None,
) -> PosttrainingRun:
    spec.validate()
    manifest = _build_training_manifest(spec)
    artifact = new_model_artifact(
        artifact_type=spec.artifact_type,
        version=spec.dataset_bundle.dataset_version,
        signed_manifest_ref=manifest.signed_manifest_ref,
        tenant_id=None if spec.shared_adapter else spec.tenant_id,
        task_type=spec.task_type,
        base_artifact_id=spec.base_artifact_id,
        dataset_manifest_ids=[spec.dataset_bundle.dataset_version],
        training_run_id=manifest.training_run_id,
        metadata={
            "method": spec.method,
            "shared_adapter": spec.shared_adapter,
            "approval_id": spec.shared_adapter_approval.approval_id if spec.shared_adapter_approval else None,
        },
    )
    lineage = build_lineage_graph(spec=spec, manifest=manifest, artifact=artifact)
    rollback = RollbackManifest(
        artifact_id=artifact.artifact_id,
        previous_artifact_id=previous_artifact_id,
        routing_alias=routing_alias or f"{spec.tenant_id}/{spec.task_type}",
        restore_steps=[
            "set routing alias to previous_artifact_id",
            "mark failed artifact retired",
            "record rollback audit event",
        ],
        created_at=utc_now(),
    )
    return PosttrainingRun(
        training_manifest=manifest,
        artifact=artifact,
        lineage_graph=lineage,
        rollback_manifest=rollback,
        model_card=build_model_card(spec=spec, manifest=manifest, artifact=artifact, rollback=rollback),
    )


def write_posttraining_run(*, run: PosttrainingRun, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "training_manifest.json": run.training_manifest.to_dict(),
        "artifact_manifest.json": run.artifact.to_dict(),
        "lineage_graph.json": [node.to_dict() for node in run.lineage_graph],
        "rollback_manifest.json": run.rollback_manifest.to_dict(),
        "model_card.json": run.model_card,
    }
    written: dict[str, str] = {}
    for name, payload in files.items():
        path = output_path / name
        path.write_text(_json(payload), encoding="utf-8")
        written[name] = str(path)
    return written


def build_posttraining_e2e(*, dataset_bundle: DatasetBundle, output_directory: str | Path) -> PosttrainingRun:
    spec = TrainingJobSpec(
        method="lora",
        tenant_id="tenant_a",
        task_type="crops",
        dataset_bundle=dataset_bundle,
        code_version="mesh-brain-posttraining-reference",
        artifact_type="tenant_adapter",
        base_artifact_id="qwen-27b-base",
        hyperparameters={"rank": 16, "learning_rate": 0.0002, "epochs": 2},
    )
    run = plan_posttraining_run(spec=spec, previous_artifact_id="adapter_previous", routing_alias="tenant_a/crops")
    write_posttraining_run(run=run, output_directory=output_directory)
    return run


def build_lineage_graph(*, spec: TrainingJobSpec, manifest: TrainingManifest, artifact: ModelArtifact) -> list[LineageNode]:
    row_ids = [row.row_id for row in spec.dataset_bundle.rows if not row.excluded_from_training]
    return [
        LineageNode(
            node_id=spec.dataset_bundle.dataset_version,
            node_type="dataset",
            refs=row_ids,
            metadata={"source_manifest_id": spec.dataset_bundle.source_manifest_id},
        ),
        LineageNode(
            node_id=spec.code_version,
            node_type="training_code",
            refs=[],
            metadata={"method": spec.method},
        ),
        LineageNode(
            node_id=manifest.training_run_id,
            node_type="training_run",
            refs=[spec.dataset_bundle.dataset_version, spec.code_version],
            metadata={"hyperparameters": dict(spec.hyperparameters)},
        ),
        LineageNode(
            node_id=artifact.artifact_id,
            node_type="model_artifact",
            refs=[manifest.training_run_id],
            metadata={
                "artifact_type": artifact.artifact_type,
                "signed_manifest_ref": artifact.signed_manifest_ref,
                "base_artifact_id": artifact.base_artifact_id,
            },
        ),
    ]


def build_model_card(
    *,
    spec: TrainingJobSpec,
    manifest: TrainingManifest,
    artifact: ModelArtifact,
    rollback: RollbackManifest,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "tenant_id": artifact.tenant_id,
        "task_type": artifact.task_type,
        "method": spec.method,
        "dataset_version": spec.dataset_bundle.dataset_version,
        "training_run_id": manifest.training_run_id,
        "signed_manifest_ref": manifest.signed_manifest_ref,
        "lineage_digest": stable_digest(manifest.lineage),
        "rollback_manifest": rollback.to_dict(),
        "eval_required_before_deployment": True,
        "shared_adapter": spec.shared_adapter,
    }


def _build_training_manifest(spec: TrainingJobSpec) -> TrainingManifest:
    trainable_rows = [row for row in spec.dataset_bundle.rows if not row.excluded_from_training]
    lineage = {
        "dataset_version": spec.dataset_bundle.dataset_version,
        "source_manifest_id": spec.dataset_bundle.source_manifest_id,
        "row_ids": [row.row_id for row in trainable_rows],
        "code_version": spec.code_version,
        "base_artifact_id": spec.base_artifact_id,
        "tenant_id": spec.tenant_id,
        "task_type": spec.task_type,
    }
    manifest_core = {
        "method": spec.method,
        "dataset_version": spec.dataset_bundle.dataset_version,
        "code_version": spec.code_version,
        "artifact_type": spec.artifact_type,
        "hyperparameters": dict(spec.hyperparameters),
        "lineage": lineage,
    }
    digest = stable_digest(manifest_core)
    return TrainingManifest(
        training_run_id=f"mb_train_{digest[:12]}",
        method=spec.method,
        dataset_version=spec.dataset_bundle.dataset_version,
        code_version=spec.code_version,
        hyperparameters=dict(spec.hyperparameters),
        artifact_type=spec.artifact_type,
        signed_manifest_ref=f"sha256:{digest}",
        lineage=lineage,
        created_at=utc_now(),
    )


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
