from __future__ import annotations

from typing import Any, cast

from ._utils import stable_id, string_list, timestamp, validate


MESH_BRAIN_RECORD_SPECS: tuple[dict[str, Any], ...] = (
    {
        "action_type": "mesh_brain_dataset_provenance",
        "action_class": "observe",
        "run_record_keys": ("mesh_brain_run_record",),
        "artifact_keys": (
            "mesh_brain_dataset_manifest",
            "mesh_brain_posttraining_dataset_manifest",
            "mesh_brain_mlx_lm_lora_mesh_dataset_manifest",
        ),
    },
    {
        "action_type": "mesh_brain_training_job",
        "action_class": "attest",
        "run_record_keys": ("mesh_brain_run_record",),
        "artifact_keys": (
            "mesh_brain_training_job",
            "mesh_brain_posttraining_training_job",
            "mesh_brain_mlx_lm_lora_command_plan",
        ),
    },
    {
        "action_type": "mesh_brain_eval_score",
        "action_class": "attest",
        "run_record_keys": ("mesh_brain_run_record", "mesh_brain_backend_matrix_record"),
        "artifact_keys": (
            "mesh_brain_eval_job",
            "mesh_brain_backend_matrix_results",
            "mesh_brain_posttraining_eval_job",
            "mesh_brain_mlx_lm_lora_native_response_eval",
        ),
    },
    {
        "action_type": "mesh_brain_serving_smoke",
        "action_class": "attest",
        "run_record_keys": ("mesh_brain_live_serving_run_record",),
        "artifact_keys": (
            "mesh_brain_live_serving_summary",
            "mesh_brain_posttraining_serving_smoke",
            "mesh_brain_mlx_lm_lora_native_server_probe",
        ),
    },
    {
        "action_type": "mesh_brain_model_kernel_proof",
        "action_class": "attest",
        "run_record_keys": ("mesh_brain_model_kernel_run_record",),
        "artifact_keys": (
            "mesh_brain_model_kernel_gate",
            "mesh_brain_model_kernel_probe_summary",
        ),
    },
    {
        "action_type": "mesh_brain_quality_update",
        "action_class": "attest",
        "run_record_keys": (
            "mesh_brain_run_record",
            "mesh_brain_backend_matrix_record",
            "mesh_brain_rollback_drill_run_record",
        ),
        "artifact_keys": (
            "mesh_brain_backend_matrix_summary",
            "mesh_brain_posttraining_deployment_record",
            "mesh_brain_mlx_lm_lora_run_summary",
            "live_quality_training_summary",
            "quality_training_result",
        ),
    },
)


def materialize_mesh_brain_action_records(
    run_export: dict[str, Any],
    *,
    tenant_id: str,
    reservoir_refs: list[str] | None = None,
    proof_refs: list[str] | None = None,
) -> list[dict[str, Any]]:
    session = _record(run_export.get("session"))
    artifacts = _record(session.get("artifacts"))
    generated_at = str(run_export.get("generated_at") or session.get("updated_at") or timestamp())
    records: list[dict[str, Any]] = []
    for spec in MESH_BRAIN_RECORD_SPECS:
        evidence_refs = _evidence_refs_for_spec(artifacts, spec)
        if not evidence_refs:
            continue
        action_type = str(spec["action_type"])
        records.append(
            validate(
                "perennial/agent-action-record.schema.json",
                {
                    "contract": "perennial.agent_action_record.v1",
                    "action_record_id": stable_id(
                        "aar_mesh_brain",
                        run_export.get("run_id"),
                        action_type,
                        evidence_refs,
                    ),
                    "observed_at": _observed_at_for_spec(artifacts, spec, generated_at),
                    "actor": {
                        "actor_type": "service",
                        "actor_id": "mesh-brain.control-plane",
                        "display_name": "Mesh Brain control plane",
                        "authority_source": "service_account",
                    },
                    "action": {
                        "action_class": str(spec["action_class"]),
                        "action_type": action_type,
                        "target": {
                            "environment": "on_prem",
                            "service": "mesh-brain",
                            "namespace": "post-training",
                            "resource_ref": _resource_ref_for_spec(artifacts, spec, action_type),
                            "reservoir_id": None,
                        },
                        "production_impact": "none",
                    },
                    "context": {
                        "run_id": run_export.get("run_id") or session.get("run_id"),
                        "run_event_id": None,
                        "decision_id": _record(run_export.get("decision_record")).get("decision_id"),
                        "evaluation_id": _record(run_export.get("evaluation_record")).get("evaluation_id"),
                        "feedback_id": artifacts.get("feedback_id"),
                        "source_system": "mesh_brain",
                    },
                    "governance": {
                        "risk_tier": "moderate",
                        "autonomy_tier": "advisory",
                        "policy_refs": ["policy://mesh-brain/artifact-attestation"],
                        "evidence_refs": evidence_refs,
                        "proof_refs": list(proof_refs or []),
                        "operator_authority_refs": [],
                    },
                    "outcome": {
                        "status": "observed",
                        "denial_reasons": [],
                        "rollback_ref": _rollback_ref(artifacts),
                        "side_effect_refs": [],
                    },
                    "boundary": {
                        "tenant_id": tenant_id,
                        "data_boundary": "on_prem",
                        "reservoir_refs": list(reservoir_refs or []),
                    },
                },
            )
        )
    return records


def mesh_brain_evidence_refs(session: dict[str, Any]) -> list[str]:
    artifacts = _record(session.get("artifacts"))
    refs: list[str] = []
    for spec in MESH_BRAIN_RECORD_SPECS:
        refs.extend(_evidence_refs_for_spec(artifacts, spec))
    return list(dict.fromkeys(refs))


def _evidence_refs_for_spec(artifacts: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in cast(tuple[str, ...], spec["run_record_keys"]):
        record = _record(artifacts.get(key))
        if record:
            refs.append(_run_record_ref(key, record))
            refs.extend(_artifact_refs(record.get("artifact_refs")))
    for key in cast(tuple[str, ...], spec["artifact_keys"]):
        ref = _artifact_ref(key, artifacts.get(key))
        if ref:
            refs.append(ref)
    return list(dict.fromkeys(refs))


def _run_record_ref(key: str, record: dict[str, Any]) -> str:
    lane = {
        "mesh_brain_run_record": "mvp",
        "mesh_brain_model_kernel_run_record": "model-kernel",
        "mesh_brain_live_serving_run_record": "live-serving",
        "mesh_brain_rollback_drill_run_record": "rollback-drill",
        "mesh_brain_backend_matrix_record": "backend-matrix",
    }.get(key, key.removeprefix("mesh_brain_").removesuffix("_run_record"))
    run_id = record.get("run_id") or record.get("workflow_id") or record.get("id") or key
    return f"mesh_brain://{lane}/{run_id}"


def _artifact_refs(raw_refs: Any) -> list[str]:
    refs = _record(raw_refs)
    out: list[str] = []
    for key, value in refs.items():
        ref = _artifact_ref(str(key), value)
        if ref:
            out.append(ref)
    return out


def _artifact_ref(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value if "://" in value else f"artifact://{key}"
    if not isinstance(value, dict):
        return f"artifact://{key}"
    for field in ("uri", "path"):
        raw_ref = value.get(field)
        if raw_ref:
            return str(raw_ref)
    artifact_key = value.get("artifact_key") or key
    return f"artifact://{artifact_key}"


def _observed_at_for_spec(artifacts: dict[str, Any], spec: dict[str, Any], fallback: str) -> str:
    for key in cast(tuple[str, ...], spec["run_record_keys"]):
        record = _record(artifacts.get(key))
        for field in ("completed_at", "updated_at", "created_at", "recorded_at"):
            raw_value = record.get(field)
            if raw_value:
                return str(raw_value)
    return fallback


def _resource_ref_for_spec(artifacts: dict[str, Any], spec: dict[str, Any], action_type: str) -> str:
    for key in cast(tuple[str, ...], spec["run_record_keys"]):
        record = _record(artifacts.get(key))
        run_id = record.get("run_id") or record.get("workflow_id")
        if run_id:
            return f"mesh_brain://{action_type}/{run_id}"
    for key in cast(tuple[str, ...], spec["artifact_keys"]):
        if key in artifacts:
            return f"artifact://{key}"
    return f"mesh_brain://{action_type}"


def _rollback_ref(artifacts: dict[str, Any]) -> str | None:
    record = _record(artifacts.get("mesh_brain_rollback_drill_run_record"))
    if not record:
        return None
    for ref in string_list(record.get("rollback_refs") or record.get("rollback_ref")):
        return ref
    artifact_refs = _record(record.get("artifact_refs"))
    ref = _artifact_ref("mesh_brain_rollback_drill_summary", artifact_refs.get("mesh_brain_rollback_drill_summary"))
    return ref


def _record(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}
