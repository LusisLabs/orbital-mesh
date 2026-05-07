from __future__ import annotations

from typing import Any, cast

from ._utils import stable_id, string_list, timestamp, validate


RUNTIME_EVIDENCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "artifact_key": "remediation_safety",
        "action_type": "darkharness_remediation_safety_gate",
        "action_class": "attest",
        "policy_ref": "policy://darkharness/pilot/remediation-safety-required",
    },
    {
        "artifact_key": "trust_ladder",
        "action_type": "darkharness_trust_ladder_gate",
        "action_class": "attest",
        "policy_ref": "policy://darkharness/pilot/trust-ladder-ceiling",
    },
    {
        "artifact_key": "integration_readiness",
        "action_type": "darkharness_readiness_gap_gate",
        "action_class": "attest",
        "policy_ref": "policy://darkharness/pilot/readiness-required",
    },
)


def materialize_runtime_evidence_action_records(
    run_export: dict[str, Any],
    *,
    tenant_id: str,
    reservoir_refs: list[str] | None = None,
    proof_refs: list[str] | None = None,
    operator_authority_refs: list[str] | None = None,
) -> list[dict[str, Any]]:
    session = _record(run_export.get("session"))
    artifacts = _record(session.get("artifacts"))
    decision = _record(run_export.get("decision_record"))
    evaluation = _record(run_export.get("evaluation_record"))
    generated_at = str(run_export.get("generated_at") or session.get("updated_at") or timestamp())
    records = [
        _record_for_artifact(
            spec,
            run_export=run_export,
            session=session,
            artifacts=artifacts,
            decision=decision,
            evaluation=evaluation,
            generated_at=generated_at,
            tenant_id=tenant_id,
            reservoir_refs=reservoir_refs,
            proof_refs=proof_refs,
            operator_authority_refs=operator_authority_refs,
        )
        for spec in RUNTIME_EVIDENCE_SPECS
        if spec["artifact_key"] in artifacts
    ]
    records.extend(
        _approval_records(
            run_export,
            session=session,
            decision=decision,
            evaluation=evaluation,
            generated_at=generated_at,
            tenant_id=tenant_id,
            reservoir_refs=reservoir_refs,
            proof_refs=proof_refs,
            operator_authority_refs=operator_authority_refs,
        )
    )
    rollback_record = _rollback_record(
        run_export,
        session=session,
        decision=decision,
        evaluation=evaluation,
        generated_at=generated_at,
        tenant_id=tenant_id,
        reservoir_refs=reservoir_refs,
        proof_refs=proof_refs,
        operator_authority_refs=operator_authority_refs,
    )
    if rollback_record is not None:
        records.append(rollback_record)
    return records


def runtime_evidence_refs(run_export: dict[str, Any]) -> list[str]:
    session = _record(run_export.get("session"))
    artifacts = _record(session.get("artifacts"))
    refs = [
        _artifact_ref(str(spec["artifact_key"]), artifacts[spec["artifact_key"]])
        for spec in RUNTIME_EVIDENCE_SPECS
        if spec["artifact_key"] in artifacts
    ]
    refs.extend(_operator_authority_refs(run_export))
    rollback_ref = _rollback_ref(_record(run_export.get("decision_record")))
    if rollback_ref:
        refs.append(rollback_ref)
    return list(dict.fromkeys(ref for ref in refs if ref))


def _record_for_artifact(
    spec: dict[str, Any],
    *,
    run_export: dict[str, Any],
    session: dict[str, Any],
    artifacts: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    generated_at: str,
    tenant_id: str,
    reservoir_refs: list[str] | None,
    proof_refs: list[str] | None,
    operator_authority_refs: list[str] | None,
) -> dict[str, Any]:
    artifact_key = str(spec["artifact_key"])
    artifact = artifacts[artifact_key]
    return _base_record(
        run_export,
        session=session,
        decision=decision,
        evaluation=evaluation,
        generated_at=_observed_at(artifact, generated_at),
        tenant_id=tenant_id,
        reservoir_refs=reservoir_refs,
        proof_refs=proof_refs,
        operator_authority_refs=operator_authority_refs,
        action_class=str(spec["action_class"]),
        action_type=str(spec["action_type"]),
        resource_ref=_artifact_ref(artifact_key, artifact),
        policy_refs=[str(spec["policy_ref"])],
        evidence_refs=[_artifact_ref(artifact_key, artifact)],
        status=_artifact_status(artifact, "observed"),
        rollback_ref=_rollback_ref(decision),
    )


def _approval_records(
    run_export: dict[str, Any],
    *,
    session: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    generated_at: str,
    tenant_id: str,
    reservoir_refs: list[str] | None,
    proof_refs: list[str] | None,
    operator_authority_refs: list[str] | None,
) -> list[dict[str, Any]]:
    approvals = run_export.get("approval_records")
    if not isinstance(approvals, list):
        return []
    records = []
    for index, approval in enumerate(approvals):
        if not isinstance(approval, dict):
            continue
        approval_ref = _approval_ref(approval, index=index)
        records.append(
            _base_record(
                run_export,
                session=session,
                decision=decision,
                evaluation=evaluation,
                generated_at=str(approval.get("recorded_at") or approval.get("created_at") or generated_at),
                tenant_id=tenant_id,
                reservoir_refs=reservoir_refs,
                proof_refs=proof_refs,
                operator_authority_refs=operator_authority_refs,
                action_class="approve",
                action_type="darkharness_operator_approval",
                actor=_approval_actor(approval),
                resource_ref=approval_ref,
                policy_refs=["policy://darkharness/pilot/operator-approval-required"],
                evidence_refs=[approval_ref],
                status="approved",
                rollback_ref=_rollback_ref(decision),
            )
        )
    return records


def _rollback_record(
    run_export: dict[str, Any],
    *,
    session: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    generated_at: str,
    tenant_id: str,
    reservoir_refs: list[str] | None,
    proof_refs: list[str] | None,
    operator_authority_refs: list[str] | None,
) -> dict[str, Any] | None:
    rollback_ref = _rollback_ref(decision)
    if rollback_ref is None:
        return None
    return _base_record(
        run_export,
        session=session,
        decision=decision,
        evaluation=evaluation,
        generated_at=generated_at,
        tenant_id=tenant_id,
        reservoir_refs=reservoir_refs,
        proof_refs=proof_refs,
        operator_authority_refs=operator_authority_refs,
        action_class="rollback",
        action_type="darkharness_rollback_plan",
        resource_ref=rollback_ref,
        policy_refs=["policy://darkharness/pilot/rollback-proof-required"],
        evidence_refs=[rollback_ref],
        status="proposed",
        rollback_ref=rollback_ref,
    )


def _base_record(
    run_export: dict[str, Any],
    *,
    session: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    generated_at: str,
    tenant_id: str,
    reservoir_refs: list[str] | None,
    proof_refs: list[str] | None,
    operator_authority_refs: list[str] | None,
    action_class: str,
    action_type: str,
    resource_ref: str,
    policy_refs: list[str],
    evidence_refs: list[str],
    status: str,
    rollback_ref: str | None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = str(run_export.get("run_id") or session.get("run_id") or "")
    record = {
        "contract": "perennial.agent_action_record.v1",
        "action_record_id": stable_id("aar_runtime", run_id, action_type, resource_ref),
        "observed_at": generated_at,
        "actor": actor
        or {
            "actor_type": "service",
            "actor_id": "orbital-mesh.control-plane",
            "display_name": "Orbital Mesh control plane",
            "authority_source": "service_account",
        },
        "action": {
            "action_class": action_class,
            "action_type": action_type,
            "target": {
                "environment": _environment(decision),
                "service": _service(decision),
                "namespace": _namespace(decision),
                "resource_ref": resource_ref,
                "reservoir_id": None,
            },
            "production_impact": "none",
        },
        "context": {
            "run_id": run_id or None,
            "run_event_id": None,
            "decision_id": decision.get("decision_id"),
            "evaluation_id": evaluation.get("evaluation_id"),
            "feedback_id": _record(run_export.get("feedback_record")).get("feedback_id"),
            "source_system": "orbital-mesh-runtime-evidence",
        },
        "governance": {
            "risk_tier": _risk_tier(decision, evaluation),
            "autonomy_tier": str(decision.get("autonomy_tier") or "approval_required"),
            "policy_refs": policy_refs,
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "proof_refs": list(proof_refs or []),
            "operator_authority_refs": list(operator_authority_refs or _operator_authority_refs(run_export)),
        },
        "outcome": {
            "status": status,
            "denial_reasons": string_list(evaluation.get("blocking_reasons")) if status == "denied" else [],
            "rollback_ref": rollback_ref,
            "side_effect_refs": [],
        },
        "boundary": {
            "tenant_id": tenant_id,
            "data_boundary": "on_prem",
            "reservoir_refs": list(reservoir_refs or []),
        },
    }
    return validate("perennial/agent-action-record.schema.json", record)


def _operator_authority_refs(run_export: dict[str, Any]) -> list[str]:
    approvals = run_export.get("approval_records")
    if not isinstance(approvals, list):
        return []
    refs: list[str] = []
    for index, approval in enumerate(approvals):
        if isinstance(approval, dict):
            refs.append(_approval_ref(approval, index=index))
    return list(dict.fromkeys(refs))


def _approval_ref(approval: dict[str, Any], *, index: int) -> str:
    raw_ref = approval.get("authority_ref") or approval.get("ref")
    if raw_ref:
        return str(raw_ref)
    approval_id = approval.get("event_id") or approval.get("approval_id") or f"approval_{index + 1}"
    return f"operator-approval://{approval_id}"


def _approval_actor(approval: dict[str, Any]) -> dict[str, Any]:
    operator_id = str(approval.get("operator_id") or approval.get("actor_id") or "unknown-operator")
    return {
        "actor_type": "human",
        "actor_id": operator_id,
        "display_name": approval.get("operator_name") or approval.get("display_name") or operator_id,
        "authority_source": str(approval.get("authority_source") or "proxy_header"),
    }


def _artifact_ref(key: str, value: Any) -> str:
    if isinstance(value, str) and value:
        return value if "://" in value else f"artifact://{key}"
    if isinstance(value, dict):
        raw_ref = value.get("uri") or value.get("path") or value.get("ref")
        if raw_ref:
            return str(raw_ref)
        artifact_key = value.get("artifact_key") or key
        return f"artifact://{artifact_key}"
    return f"artifact://{key}"


def _artifact_status(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        status = str(value.get("status") or "").lower()
        if status in {"approved", "denied", "failed"}:
            return status
    return fallback


def _observed_at(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        for field in ("recorded_at", "created_at", "updated_at", "completed_at"):
            raw_value = value.get(field)
            if raw_value:
                return str(raw_value)
    return fallback


def _rollback_ref(decision: dict[str, Any]) -> str | None:
    plan = _record(decision.get("execution_plan"))
    raw_ref = plan.get("rollback_plan") or plan.get("rollback_ref")
    return str(raw_ref) if raw_ref else None


def _risk_tier(decision: dict[str, Any], evaluation: dict[str, Any]) -> str:
    if evaluation.get("blocking_reasons") or evaluation.get("final_recommendation") == "reject":
        return "high"
    risk = _record(decision.get("risk"))
    level = str(risk.get("level") or decision.get("risk_level") or "unknown")
    return {"low": "minimal", "medium": "moderate", "high": "high", "critical": "unacceptable"}.get(level, "unknown")


def _execution_parameters(decision: dict[str, Any]) -> dict[str, Any]:
    plan = _record(decision.get("execution_plan"))
    return _record(plan.get("parameters"))


def _environment(decision: dict[str, Any]) -> str:
    return str(_execution_parameters(decision).get("environment") or "pilot")


def _service(decision: dict[str, Any]) -> str | None:
    service = _execution_parameters(decision).get("service")
    return str(service) if service is not None else None


def _namespace(decision: dict[str, Any]) -> str | None:
    namespace = _execution_parameters(decision).get("namespace")
    return str(namespace) if namespace is not None else None


def _record(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}
