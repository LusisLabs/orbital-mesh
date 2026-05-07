from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .model_management import MeshBrainModelCatalog, PromotionApproval
from .runtime import ReleaseGatePolicy, ReleaseGateResult, curated_quality_source_coverage_pass, evaluate_release_gate, utc_now


@dataclass(frozen=True)
class RollbackDrillResult:
    drill_id: str
    generated_at: str
    tenant_id: str
    task_type: str
    status: str
    release_decision: str
    previous_artifact_id: str
    candidate_artifact_id: str
    restored_artifact_id: str
    alias: str
    audit_events: list[dict[str, Any]]
    metrics: dict[str, Any]
    rollback_manifest: dict[str, Any]
    artifact_paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_mesh_brain_rollback_drill(
    *,
    output_directory: str | Path,
    tenant_id: str = "tenant_a",
    task_type: str = "crops",
) -> RollbackDrillResult:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    alias = f"{tenant_id}/{task_type}"
    catalog = MeshBrainModelCatalog()
    base = catalog.register_base_model(version="rollback-base", signed_manifest_ref="sha256:rollback-base")
    base.state = "production"
    previous = catalog.register_tenant_adapter(
        tenant_id=tenant_id,
        task_type=task_type,
        version="rollback-previous",
        signed_manifest_ref="sha256:rollback-previous",
        base_artifact_id=base.artifact_id,
        dataset_manifest_ids=["dataset_previous"],
        training_run_id="train_previous",
    )
    previous_gate = _gate(previous.artifact_id, "promote")
    previous_alias = catalog.promote(
        artifact_id=previous.artifact_id,
        gate_result=previous_gate,
        alias=alias,
        approval=_approval("approval_rollback_previous"),
        rollback_manifest_ref=f"rollback://{alias}/previous",
    )
    candidate = catalog.register_tenant_adapter(
        tenant_id=tenant_id,
        task_type=task_type,
        version="rollback-candidate",
        signed_manifest_ref="sha256:rollback-candidate",
        base_artifact_id=base.artifact_id,
        dataset_manifest_ids=["dataset_candidate"],
        training_run_id="train_candidate",
    )
    candidate_gate = _gate(candidate.artifact_id, "promote")
    candidate_alias = catalog.promote(
        artifact_id=candidate.artifact_id,
        gate_result=candidate_gate,
        alias=alias,
        approval=_approval("approval_rollback_candidate"),
        rollback_manifest_ref=f"rollback://{alias}/candidate",
    )
    before = catalog.snapshot()
    restored_alias = catalog.rollback(alias=alias)
    after = catalog.snapshot()
    audit_events: list[dict[str, Any]] = [
        {"event_type": "promotion_recorded", "alias": alias, "artifact_id": previous_alias.artifact_id, "state": previous_alias.state},
        {
            "event_type": "promotion_recorded",
            "alias": alias,
            "artifact_id": candidate_alias.artifact_id,
            "previous_artifact_id": candidate_alias.previous_artifact_id,
            "state": candidate_alias.state,
        },
        {
            "event_type": "rollback_recorded",
            "alias": alias,
            "artifact_id": restored_alias.artifact_id,
            "previous_artifact_id": restored_alias.previous_artifact_id,
            "state": restored_alias.state,
        },
    ]
    rollback_manifest = {
        "manifest_id": f"rollback_manifest_{candidate.artifact_id}",
        "alias": alias,
        "candidate_artifact_id": candidate.artifact_id,
        "previous_artifact_id": previous.artifact_id,
        "restore_command": "MeshBrainModelCatalog.rollback",
        "immediate": True,
        "operator_approval_id": "approval_rollback_candidate",
        "created_at": utc_now(),
    }
    metrics = {
        "restored_previous_artifact": restored_alias.artifact_id == previous.artifact_id,
        "candidate_retired": after["artifacts"][candidate.artifact_id]["state"] == "retired",
        "audit_event_count": len(audit_events),
        "rollback_alias_state": restored_alias.state,
    }
    status = "completed" if all((metrics["restored_previous_artifact"], metrics["candidate_retired"])) else "blocked"
    drill_id = f"mesh_brain_rollback_drill_{candidate.artifact_id[-12:]}"
    artifact_paths = write_rollback_drill_artifacts(
        output_directory=output_path,
        before=before,
        after=after,
        audit_events=audit_events,
        rollback_manifest=rollback_manifest,
        metrics=metrics,
        summary={
            "drill_id": drill_id,
            "tenant_id": tenant_id,
            "task_type": task_type,
            "alias": alias,
            "status": status,
            "release_decision": "pass" if status == "completed" else "block",
            "previous_artifact_id": previous.artifact_id,
            "candidate_artifact_id": candidate.artifact_id,
            "restored_artifact_id": restored_alias.artifact_id,
            "metrics": metrics,
        },
    )
    return RollbackDrillResult(
        drill_id=drill_id,
        generated_at=utc_now(),
        tenant_id=tenant_id,
        task_type=task_type,
        status=status,
        release_decision="pass" if status == "completed" else "block",
        previous_artifact_id=previous.artifact_id,
        candidate_artifact_id=candidate.artifact_id,
        restored_artifact_id=restored_alias.artifact_id,
        alias=alias,
        audit_events=audit_events,
        metrics=metrics,
        rollback_manifest=rollback_manifest,
        artifact_paths=artifact_paths,
    )


def write_rollback_drill_artifacts(
    *,
    output_directory: str | Path,
    before: dict[str, Any],
    after: dict[str, Any],
    audit_events: list[dict[str, Any]],
    rollback_manifest: dict[str, Any],
    metrics: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "rollback_drill_before.json": before,
        "rollback_manifest.json": rollback_manifest,
        "rollback_audit_events.json": audit_events,
        "rollback_drill_metrics.json": metrics,
        "rollback_drill_after.json": after,
        "rollback_drill_summary.json": summary,
    }
    written: dict[str, str] = {}
    for name, payload in files.items():
        path = output_path / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        written[name.removesuffix(".json")] = str(path)
    return written


def _gate(artifact_id: str, decision: str) -> ReleaseGateResult:
    return evaluate_release_gate(
        candidate_artifact_id=artifact_id,
        metrics={
            "critical_policy_regressions": 0,
            "unsafe_autonomous_action_rate_delta": 0,
            "schema_validity_delta": 0,
            "task_success_rate": 1.0,
            "canary_passed": decision == "promote",
            "model_kernel_passed": True,
            "live_serving_smoke_passed": True,
            "response_eval_passed": True,
            "judge_rubric_passed": True,
            "red_team_regression_passed": True,
            "curated_quality_training_passed": True,
            "quality_source_coverage": curated_quality_source_coverage_pass(),
        },
        policy=ReleaseGatePolicy(task_success_threshold=0.8),
    )


def _approval(approval_id: str) -> PromotionApproval:
    return PromotionApproval(
        approval_id=approval_id,
        operator_id="operator_1",
        roles=["approver"],
        approved_at=utc_now(),
        evidence_refs=["mesh://approval/rollback-drill"],
    )
