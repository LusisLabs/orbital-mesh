from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mvp import MeshBrainMVPResult
from .observability import mesh_brain_observation_to_prometheus
from .run_mvp_e2e import persisted_artifact_paths
from .runtime import utc_now


MESH_BRAIN_ARTIFACT_KEYS = (
    "mesh_brain_dataset_manifest",
    "mesh_brain_training_job",
    "mesh_brain_eval_job",
    "mesh_brain_serving_plan",
    "mesh_brain_runtime_trace",
    "mesh_brain_observability_metrics",
    "mesh_brain_catalog_snapshot",
)

MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS = (
    "mesh_brain_live_serving_execution",
    "mesh_brain_live_smoke_gate",
    "mesh_brain_live_response_eval",
    "mesh_brain_live_judge_eval",
    "mesh_brain_live_release_gate",
    "mesh_brain_live_serving_summary",
)


@dataclass(frozen=True)
class MeshBrainArtifactRef:
    artifact_key: str
    path: str
    exists: bool
    sha256: str | None
    content_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "path": self.path,
            "exists": self.exists,
            "sha256": self.sha256,
            "content_type": self.content_type,
        }


@dataclass(frozen=True)
class MeshBrainArtifactBundle:
    workflow_id: str
    tenant_id: str
    output_directory: str
    artifacts: dict[str, MeshBrainArtifactRef]
    release_decision: str
    deployment_record: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "tenant_id": self.tenant_id,
            "output_directory": self.output_directory,
            "artifacts": {key: ref.to_dict() for key, ref in self.artifacts.items()},
            "release_decision": self.release_decision,
            "deployment_record": dict(self.deployment_record),
        }


def build_mesh_brain_artifact_bundle(
    *,
    result: MeshBrainMVPResult,
    output_directory: str | Path,
) -> MeshBrainArtifactBundle:
    output_path = Path(output_directory)
    paths = persisted_artifact_paths(output_path)
    artifact_paths = {
        "mesh_brain_dataset_manifest": paths["dataset_manifest"],
        "mesh_brain_training_job": paths["training_job"],
        "mesh_brain_eval_job": paths["eval_job"],
        "mesh_brain_serving_plan": paths["serving_plan"],
        "mesh_brain_runtime_trace": paths["trace_dataset_row"],
        "mesh_brain_observability_metrics": paths["observability_metrics"],
        "mesh_brain_catalog_snapshot": paths["catalog_snapshot"],
    }
    refs = {
        key: _artifact_ref(key, Path(path))
        for key, path in artifact_paths.items()
    }
    release_decision = result.eval_job.release_decision
    return MeshBrainArtifactBundle(
        workflow_id=result.workflow_id,
        tenant_id=result.serving_plan.route.tenant_id,
        output_directory=str(output_path),
        artifacts=refs,
        release_decision=release_decision,
        deployment_record={
            "status": "blocked" if release_decision == "block" else "recorded",
            "deployed": release_decision in {"canary", "promote"},
            "release_decision": release_decision,
            "candidate_artifact_id": result.eval_job.candidate_artifact_id,
            "serving_backend": result.serving_plan.backend_name if release_decision != "block" else None,
            "canary_state": result.canary_alias.state if release_decision != "block" else None,
            "rollback_state": result.rollback_alias.state,
        },
    )


def mesh_brain_mvp_to_run_record(
    *,
    result: MeshBrainMVPResult,
    bundle: MeshBrainArtifactBundle,
    run_id: str,
) -> dict[str, Any]:
    audit_events = [event.to_dict() for event in result.agent_result.events]
    policy_events = [
        event
        for event in audit_events
        if event.get("event_type") in {"policy_decision", "approval_decision"}
    ]
    return {
        "run_id": run_id,
        "tenant_id": bundle.tenant_id,
        "stage": "failed" if bundle.release_decision == "block" else "completed",
        "status": "blocked" if bundle.release_decision == "block" else "completed",
        "artifact_refs": {key: ref.to_dict() for key, ref in bundle.artifacts.items()},
        "audit_events": audit_events,
        "policy_events": policy_events,
        "summary_metrics": {
            "golden_eval_case_count": result.acceptance_report["golden_eval_case_count"],
            "token_count": result.observability.token_count,
            "cache_hit_rate": result.observability.cache_hit_rate,
            "policy_route": result.observability.policy_route,
            "serving_backend": result.serving_plan.backend_name,
        },
        "final_release_decision": bundle.release_decision,
    }


def mesh_brain_result_prometheus(result: MeshBrainMVPResult) -> str:
    return mesh_brain_observation_to_prometheus(result.observability)


def _artifact_ref(artifact_key: str, path: Path) -> MeshBrainArtifactRef:
    exists = path.exists()
    return MeshBrainArtifactRef(
        artifact_key=artifact_key,
        path=str(path),
        exists=exists,
        sha256=_sha256(path) if exists else None,
        content_type="text/plain" if path.suffix == ".prom" else "application/json",
    )


def mesh_brain_artifact_ref(artifact_key: str, path: str | Path) -> MeshBrainArtifactRef:
    return _artifact_ref(artifact_key, Path(path))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blocked_eval_result(result: MeshBrainMVPResult) -> MeshBrainMVPResult:
    result.eval_job.release_decision = "block"
    result.acceptance_report["candidate_eval_passed"] = False
    result.acceptance_report["reported_at"] = utc_now()
    result.observability.eval_outcome = "block"
    result.observability.labels["eval_outcome"] = "block"
    for sample in result.observability.samples:
        sample.labels["eval_outcome"] = "block"
        if sample.name == "mesh_brain_eval_outcome":
            sample.value = 0.0
    return result
