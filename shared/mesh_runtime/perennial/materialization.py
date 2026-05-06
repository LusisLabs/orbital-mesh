from __future__ import annotations

from typing import Any, cast

from ._utils import as_plain_dict, stable_id, string_list, timestamp, validate
from .crypto_agility import proposed_kem_proof, proposed_pqc_signature_proof, proposed_zk_proof
from .mesh_brain import mesh_brain_evidence_refs
from .signing import build_ed25519_signature_proof, build_hmac_signature_proof


def materialize_agent_action_records(
    events: list[Any],
    *,
    run: Any | None = None,
    decision: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
    tenant_id: str = "unknown",
    reservoir_refs: list[str] | None = None,
    proof_refs: list[str] | None = None,
    operator_authority_refs: list[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        materialize_agent_action_record(
            event,
            run=run,
            decision=decision,
            evaluation=evaluation,
            tenant_id=tenant_id,
            reservoir_refs=reservoir_refs,
            proof_refs=proof_refs,
            operator_authority_refs=operator_authority_refs,
        )
        for event in events
    ]


def materialize_agent_action_record(
    event: Any,
    *,
    run: Any | None = None,
    decision: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
    tenant_id: str = "unknown",
    reservoir_refs: list[str] | None = None,
    proof_refs: list[str] | None = None,
    operator_authority_refs: list[str] | None = None,
) -> dict[str, Any]:
    event_payload = as_plain_dict(event)
    run_payload = as_plain_dict(run) if run is not None else {}
    raw_payload = event_payload.get("payload")
    payload: dict[str, Any] = cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
    decision_payload = decision or {}
    evaluation_payload = evaluation or {}
    raw_run_artifacts = run_payload.get("artifacts")
    run_artifacts: dict[str, Any] = cast(dict[str, Any], raw_run_artifacts) if isinstance(raw_run_artifacts, dict) else {}
    action_class, outcome_status = _action_class_and_status(event_payload, payload)
    action_type = _action_type(event_payload, payload, decision_payload)
    target = _target(payload, decision_payload)
    production_impact = _production_impact(payload, decision_payload, action_type)
    denial_reasons = _denial_reasons(event_payload, payload, evaluation_payload, outcome_status)
    authority_refs = operator_authority_refs if operator_authority_refs is not None else _operator_authority_refs(payload)
    record = {
        "contract": "perennial.agent_action_record.v1",
        "action_record_id": stable_id("aar", event_payload.get("run_id"), event_payload.get("event_id"), action_type),
        "observed_at": event_payload.get("recorded_at") or timestamp(),
        "actor": _actor(payload, event_payload),
        "action": {
            "action_class": action_class,
            "action_type": action_type,
            "target": target,
            "production_impact": production_impact,
        },
        "context": {
            "run_id": event_payload.get("run_id") or run_payload.get("run_id"),
            "run_event_id": event_payload.get("event_id"),
            "decision_id": decision_payload.get("decision_id"),
            "evaluation_id": evaluation_payload.get("evaluation_id"),
            "feedback_id": run_artifacts.get("feedback_id"),
            "source_system": event_payload.get("integration_name") or "orbital-mesh-control-plane",
        },
        "governance": {
            "risk_tier": _risk_tier(decision_payload, outcome_status),
            "autonomy_tier": _autonomy_tier(decision_payload),
            "policy_refs": string_list(payload.get("policy_refs") or decision_payload.get("policy_refs")),
            "evidence_refs": _evidence_refs(event_payload, payload, decision_payload),
            "proof_refs": list(proof_refs or []),
            "operator_authority_refs": list(authority_refs or []),
        },
        "outcome": {
            "status": outcome_status,
            "denial_reasons": denial_reasons,
            "rollback_ref": payload.get("rollback_ref") or _execution_plan(decision_payload).get("rollback_plan"),
            "side_effect_refs": string_list(payload.get("side_effect_refs")),
        },
        "boundary": {
            "tenant_id": tenant_id,
            "data_boundary": _data_boundary(payload),
            "reservoir_refs": list(reservoir_refs or payload.get("reservoir_refs") or []),
        },
    }
    return validate("perennial/agent-action-record.schema.json", record)


def _data_boundary(payload: dict[str, Any]) -> str:
    raw_boundary = payload.get("data_boundary")
    if isinstance(raw_boundary, str):
        return raw_boundary
    return "on_prem"


def materialize_epistemic_state(
    scenario_analysis: dict[str, Any],
    *,
    run_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    analysis_id = scenario_analysis.get("analysis_id") or stable_id("analysis", scenario_analysis)
    claims: list[dict[str, Any]] = []
    for node in scenario_analysis.get("evidence_nodes") or []:
        node_id = node.get("evidence_id") or stable_id("evidence", node)
        claims.append(
            {
                "claim_id": f"claim_{node_id}",
                "claim_type": "observation",
                "statement": node.get("summary") or node.get("kind") or "Observed Mesh evidence.",
                "confidence": float(node.get("confidence", scenario_analysis.get("confidence", 0.5))),
                "evidence_refs": [node_id],
                "contradicted_by": string_list(node.get("contradicted_by")),
                "source": node.get("analyzer") or "scenario-analysis",
                "status": "active" if node.get("trusted", True) else "disputed",
            }
        )
    for subdecision in scenario_analysis.get("subdecisions") or []:
        subdecision_id = subdecision.get("subdecision_id") or stable_id("subdecision", subdecision)
        claims.append(
            {
                "claim_id": f"claim_{subdecision_id}",
                "claim_type": "hypothesis",
                "statement": "; ".join(string_list(subdecision.get("reasons"))) or subdecision.get("recommendation", "Candidate remediation path."),
                "confidence": float(subdecision.get("confidence", scenario_analysis.get("confidence", 0.5))),
                "evidence_refs": string_list(subdecision.get("evidence_refs")),
                "contradicted_by": string_list(subdecision.get("contradicted_by")),
                "source": subdecision.get("analyzer") or "scenario-analysis",
                "status": "active" if subdecision.get("risk_level") != "high" else "disputed",
            }
        )
    if not claims:
        claims.append(
            {
                "claim_id": stable_id("claim", analysis_id, "summary"),
                "claim_type": "inference",
                "statement": f"Scenario analysis suggests {scenario_analysis.get('suggested_decision_type', 'review')}.",
                "confidence": float(scenario_analysis.get("confidence", 0.5)),
                "evidence_refs": string_list(scenario_analysis.get("evidence_refs")),
                "contradicted_by": [],
                "source": "scenario-analysis",
                "status": "active",
            }
        )
    competing = [claim["claim_id"] for claim in claims if claim["claim_type"] == "hypothesis"]
    state = {
        "contract": "perennial.epistemic_state.v1",
        "epistemic_state_id": stable_id("epi", analysis_id, run_id),
        "subject_ref": scenario_analysis.get("trigger_id") or run_id or analysis_id,
        "run_id": run_id,
        "created_at": created_at or scenario_analysis.get("created_at") or timestamp(),
        "claims": claims,
        "uncertainty": {
            "missing_evidence": string_list(scenario_analysis.get("required_review_reasons")),
            "competing_hypotheses": competing,
            "confidence_floor": float(scenario_analysis.get("confidence_floor", max(0.0, float(scenario_analysis.get("confidence", 0.5)) - 0.2))),
            "confidence_ceiling": float(scenario_analysis.get("confidence_ceiling", min(1.0, float(scenario_analysis.get("confidence", 0.5)) + 0.2))),
        },
        "governance_use": {
            "usable_for_decision": True,
            "usable_for_execution": not bool(scenario_analysis.get("required_review_reasons")),
            "review_required": bool(scenario_analysis.get("required_review_reasons")),
        },
    }
    return validate("perennial/epistemic-state.schema.json", state)


def materialize_ontological_state(metadata: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    namespace = metadata.get("namespace", "default")
    service = metadata.get("service", "unknown-service")
    owner = metadata.get("owner", {})
    owner_id = owner.get("owner_id") or owner.get("service_owner") or f"owner.{service}"
    entities = [
        {
            "entity_id": f"service.{service}",
            "entity_type": "service",
            "labels": {"service": service, "namespace": namespace},
            "source_refs": string_list(metadata.get("source_refs") or f"registry://services/{service}"),
            "confidence": float(metadata.get("confidence", 0.9)),
            "status": "active",
        },
        {
            "entity_id": owner_id,
            "entity_type": "owner",
            "labels": {"team": owner.get("team", "unknown")},
            "source_refs": string_list(owner.get("source_refs") or f"registry://owners/{owner_id}"),
            "confidence": float(owner.get("confidence", 0.9)),
            "status": "active",
        },
    ]
    relationships = [
        {
            "relationship_id": stable_id("rel", owner_id, "owns", service),
            "subject_id": owner_id,
            "predicate": "owns",
            "object_id": f"service.{service}",
            "evidence_refs": string_list(owner.get("source_refs") or f"registry://owners/{owner_id}"),
            "confidence": float(owner.get("confidence", 0.9)),
            "status": "active",
        }
    ]
    for reservoir_id in string_list(metadata.get("reservoir_ids")):
        entities.append(
            {
                "entity_id": f"reservoir.{reservoir_id}",
                "entity_type": "reservoir",
                "labels": {"reservoir_id": reservoir_id},
                "source_refs": [f"reservoir://{reservoir_id}"],
                "confidence": 0.9,
                "status": "active",
            }
        )
        relationships.append(
            {
                "relationship_id": stable_id("rel", service, "stores", reservoir_id),
                "subject_id": f"service.{service}",
                "predicate": "stores",
                "object_id": f"reservoir.{reservoir_id}",
                "evidence_refs": [f"reservoir://{reservoir_id}"],
                "confidence": 0.9,
                "status": "active",
            }
        )
    for policy_ref in string_list(metadata.get("policy_refs")):
        policy_id = f"policy.{policy_ref.split('/')[-1]}"
        entities.append(
            {
                "entity_id": policy_id,
                "entity_type": "policy",
                "labels": {"policy_ref": policy_ref},
                "source_refs": [policy_ref],
                "confidence": 0.9,
                "status": "active",
            }
        )
        relationships.append(
            {
                "relationship_id": stable_id("rel", policy_id, "governs", service),
                "subject_id": policy_id,
                "predicate": "governs",
                "object_id": f"service.{service}",
                "evidence_refs": [policy_ref],
                "confidence": 0.9,
                "status": "active",
            }
        )
    state = {
        "contract": "perennial.ontological_state.v1",
        "ontological_state_id": stable_id("onto", namespace, service, metadata.get("schema_version", "perennial.ontology.v1")),
        "namespace": namespace,
        "created_at": created_at or timestamp(),
        "schema_version": metadata.get("schema_version", "perennial.ontology.v1"),
        "entities": entities,
        "relationships": relationships,
        "conflict_sets": list(metadata.get("conflict_sets", [])),
    }
    return validate("perennial/ontological-state.schema.json", state)


def materialize_governance_commit(
    *,
    run_export: dict[str, Any],
    epistemic_state: dict[str, Any],
    ontological_state: dict[str, Any],
    proof_envelope: dict[str, Any],
    action_record: dict[str, Any],
    readiness: dict[str, Any] | None = None,
    trust_ladder_ref: str | None = None,
    denied: bool | None = None,
) -> dict[str, Any]:
    session = run_export.get("session") or {}
    decision = run_export.get("decision_record") or {}
    evaluation = run_export.get("evaluation_record") or {}
    run_id = run_export.get("run_id") or session.get("run_id") or action_record["context"]["run_id"]
    action_plan = _execution_plan(decision)
    production_impact = action_record["action"]["production_impact"]
    blocking_reasons = string_list(evaluation.get("blocking_reasons"))
    gate_denied = denied if denied is not None else bool(blocking_reasons or evaluation.get("final_recommendation") == "reject")
    approval_refs = _approval_refs(run_export.get("approval_records"))
    reasons = blocking_reasons or ["operator approval present", "policy checks passed"]
    commit = {
        "contract": "perennial.governance_commit.v1",
        "governance_commit_id": stable_id("gc", run_id, decision.get("decision_id"), "denied" if gate_denied else "allowed"),
        "created_at": run_export.get("generated_at") or timestamp(),
        "commit_type": "deny_action" if gate_denied else "allow_action",
        "subject": {
            "run_id": run_id,
            "trigger_id": decision.get("trigger_id"),
            "decision_id": decision.get("decision_id"),
            "evaluation_id": evaluation.get("evaluation_id"),
            "action_record_id": action_record.get("action_record_id"),
        },
        "state_refs": {
            "epistemic_state_id": epistemic_state["epistemic_state_id"],
            "ontological_state_id": ontological_state["ontological_state_id"],
        },
        "inputs": {
            "evidence_refs": _run_export_evidence_refs(run_export),
            "scenario_analysis_ref": _artifact_ref(session, "scenario_analysis"),
            "policy_refs": action_record["governance"]["policy_refs"] or ["policy://darkharness/pilot/approval-required"],
            "remediation_safety_ref": _artifact_ref(session, "remediation_safety"),
            "trust_ladder_ref": trust_ladder_ref,
            "readiness_ref": "readiness://pilot/go" if readiness else None,
        },
        "authority": {
            "operator_required": production_impact in {"possible", "direct"},
            "operator_approval_refs": approval_refs,
            "service_owner_refs": _service_owner_refs(ontological_state),
        },
        "action": {
            "action_type": action_plan.get("action") or action_record["action"]["action_type"],
            "target_ref": action_record["action"]["target"].get("resource_ref"),
            "production_impact": production_impact,
            "rollback_ref": action_record["outcome"].get("rollback_ref"),
        },
        "proof": {
            "proof_envelope_id": proof_envelope["proof_envelope_id"],
            "merkle_root": proof_envelope["implemented_proofs"]["merkle"]["root_hash"],
            "signature_ref": _signature_ref(proof_envelope),
        },
        "outcome": {
            "gate_result": "denied" if gate_denied else "allowed",
            "reasons": reasons,
            "expires_at": None,
        },
    }
    return validate("perennial/governance-commit.schema.json", commit)


def materialize_proof_envelope(
    run_export: dict[str, Any],
    *,
    subject_refs: list[str],
    proof_envelope_id: str | None = None,
    created_at: str | None = None,
    redaction_profile: str = "darkharness-pilot-redacted",
    signing_key: str | None = None,
    signing_key_id: str | None = None,
    classical_signing_key_pem: str | None = None,
    classical_signing_key_id: str | None = None,
) -> dict[str, Any]:
    merkle = run_export.get("merkle") or {}
    snapshot = merkle.get("snapshot") or {}
    proof = merkle.get("latest_event_proof") or {}
    run_id = run_export.get("run_id") or snapshot.get("run_id")
    proof_refs = []
    if proof.get("event_id"):
        proof_refs.append(f"merkle://{run_id}/proof/{proof['event_id']}")
    implemented_proofs: dict[str, Any] = {
        "merkle": {
            "run_id": run_id,
            "root_hash": snapshot.get("root_hash"),
            "leaf_event_ids": string_list(snapshot.get("event_ids")),
            "proof_refs": proof_refs,
            "verifier": "orbital_mesh_merkle_v1",
        }
    }
    signature_payload = {
        "run_id": run_id,
        "subject_refs": list(subject_refs),
        "merkle_root": snapshot.get("root_hash"),
        "leaf_event_ids": string_list(snapshot.get("event_ids")),
        "redaction_profile": redaction_profile,
    }
    signature_status = "proposed"
    signature_key_id = "proposed-key"
    signature_value = None
    signature_algorithm = "ed25519"
    if classical_signing_key_pem:
        signature_proof = build_ed25519_signature_proof(
            signature_payload,
            key_id=classical_signing_key_id or signing_key_id or "darkharness-ed25519",
            private_key_pem=classical_signing_key_pem,
        )
        implemented_proofs["signature"] = signature_proof
        signature_status = "verified"
        signature_key_id = signature_proof["key_id"]
        signature_value = signature_proof["signature"]
        signature_algorithm = signature_proof["algorithm"]
    elif signing_key:
        signature_proof = build_hmac_signature_proof(
            signature_payload,
            key_id=signing_key_id or "darkharness-local-hmac",
            secret=signing_key,
        )
        implemented_proofs["signature"] = signature_proof
        signature_status = "verified"
        signature_key_id = signature_proof["key_id"]
        signature_value = signature_proof["signature"]
        signature_algorithm = signature_proof["algorithm"]
    envelope = {
        "contract": "perennial.proof_envelope.v1",
        "proof_envelope_id": proof_envelope_id or stable_id("proof", run_id, snapshot.get("root_hash"), subject_refs),
        "created_at": created_at or run_export.get("generated_at") or timestamp(),
        "subject_refs": list(subject_refs),
        "implemented_proofs": implemented_proofs,
        "proposed_proofs": {
            "signature": {
                "signing_profile": "darkharness-hmac-sha256-v1" if signing_key else "darkharness-classical-v1",
                "algorithm": signature_algorithm,
                "key_id": signature_key_id,
                "signature": signature_value,
                "status": signature_status,
            },
            "pqc_signature": proposed_pqc_signature_proof(),
            "kem": proposed_kem_proof(),
            "zk": proposed_zk_proof(run_id=str(run_id) if run_id is not None else None),
        },
        "disclosure": {
            "raw_sensitive_data_included": False,
            "redaction_profile": redaction_profile,
            "exported_fields": ["run_id", "subject_refs", "merkle_root", "gate_result"],
        },
    }
    return validate("perennial/proof-envelope.schema.json", envelope)


def _signature_ref(proof_envelope: dict[str, Any]) -> str | None:
    implemented = proof_envelope.get("implemented_proofs")
    proofs: dict[str, Any] = cast(dict[str, Any], implemented) if isinstance(implemented, dict) else {}
    raw_signature = proofs.get("signature")
    signature = cast(dict[str, Any], raw_signature) if isinstance(raw_signature, dict) else {}
    if not signature:
        return None
    return f"signature://{signature.get('key_id')}/{signature.get('payload_sha256')}"


def _action_class_and_status(event: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
    event_type = str(event.get("event_type", "")).lower()
    command_type = str(payload.get("command_type", "")).lower()
    outcome = str(payload.get("outcome", event.get("status", ""))).lower()
    if "deny" in event_type or "denied" in outcome or "blocked" in event_type or "reject" in event_type:
        return "deny", "denied"
    if command_type in {"approve", "approved"} or "approval" in event_type or outcome == "approved":
        return "approve", "approved"
    if "execution" in event_type or outcome == "executed":
        return "execute", "executed"
    if "rollback" in event_type:
        return "rollback", "rolled_back"
    if "export" in event_type:
        return "export", "observed"
    if "decision" in event_type or "proposal" in event_type:
        return "propose", "proposed"
    return "observe", "observed"


def _action_type(event: dict[str, Any], payload: dict[str, Any], decision: dict[str, Any]) -> str:
    action_type = (
        payload.get("action_type")
        or payload.get("command_type")
        or _execution_plan(decision).get("action")
        or event.get("event_type")
        or "observe"
    )
    return str(action_type)


def _actor(payload: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    raw_actor = payload.get("actor")
    actor: dict[str, Any] = cast(dict[str, Any], raw_actor) if isinstance(raw_actor, dict) else {}
    operator_id = payload.get("operator_id") or payload.get("issued_by") or actor.get("actor_id")
    if operator_id:
        actor_type = str(actor.get("actor_type", "human"))
        authority_source = str(actor.get("authority_source", "proxy_header"))
    else:
        actor_type = str(actor.get("actor_type", "service"))
        operator_id = event.get("integration_name") or "orbital-mesh"
        authority_source = str(actor.get("authority_source", "service_account"))
    return {
        "actor_type": actor_type,
        "actor_id": str(operator_id),
        "display_name": actor.get("display_name") or payload.get("operator_name"),
        "authority_source": authority_source,
    }


def _target(payload: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    execution_plan = _execution_plan(decision)
    raw_parameters = execution_plan.get("parameters")
    parameters: dict[str, Any] = cast(dict[str, Any], raw_parameters) if isinstance(raw_parameters, dict) else {}
    raw_target = payload.get("target")
    target: dict[str, Any] = cast(dict[str, Any], raw_target) if isinstance(raw_target, dict) else {}
    environment = str(target.get("environment") or payload.get("environment") or parameters.get("environment") or "pilot")
    service = _optional_string(target.get("service") or payload.get("service") or parameters.get("service"))
    namespace = _optional_string(target.get("namespace") or payload.get("namespace") or parameters.get("namespace"))
    resource_ref = _optional_string(target.get("resource_ref") or payload.get("resource_ref") or parameters.get("resource_ref"))
    reservoir_id = _optional_string(target.get("reservoir_id") or payload.get("reservoir_id") or parameters.get("reservoir_id"))
    return {
        "environment": environment,
        "service": service,
        "namespace": namespace,
        "resource_ref": resource_ref,
        "reservoir_id": reservoir_id,
    }


def _production_impact(payload: dict[str, Any], decision: dict[str, Any], action_type: str) -> str:
    impact = payload.get("production_impact") or _execution_plan(decision).get("production_impact")
    if impact in {"none", "possible", "direct"}:
        return str(impact)
    action = action_type.lower()
    if any(marker in action for marker in ("scale", "patch", "rollback", "restart", "execute", "write")):
        return "possible"
    return "none"


def _denial_reasons(event: dict[str, Any], payload: dict[str, Any], evaluation: dict[str, Any], status: str) -> list[str]:
    reasons = string_list(payload.get("denial_reasons") or evaluation.get("blocking_reasons"))
    if status == "denied" and not reasons:
        raw_summary = event.get("summary")
        summary = cast(dict[str, Any], raw_summary) if isinstance(raw_summary, dict) else {}
        reasons = string_list(summary.get("reason"))
    return [reason for reason in reasons if reason] or ([] if status != "denied" else ["policy denied action"])


def _risk_tier(decision: dict[str, Any], status: str) -> str:
    if status == "denied":
        return "high"
    raw_risk = decision.get("risk")
    risk: dict[str, Any] = cast(dict[str, Any], raw_risk) if isinstance(raw_risk, dict) else {}
    return {"low": "minimal", "medium": "moderate", "high": "high"}.get(str(risk.get("level")), "unknown")


def _autonomy_tier(decision: dict[str, Any]) -> str:
    autonomy = decision.get("autonomy_tier")
    if autonomy in {"no_action", "advisory", "approval_required", "autonomous", "escalated"}:
        return str(autonomy)
    return "approval_required"


def _execution_plan(decision: dict[str, Any]) -> dict[str, Any]:
    plan = decision.get("execution_plan")
    return cast(dict[str, Any], plan) if isinstance(plan, dict) else {}


def _operator_authority_refs(payload: dict[str, Any]) -> list[str]:
    refs = payload.get("operator_authority_refs")
    if refs:
        return string_list(refs)
    if payload.get("operator_id"):
        return [f"operator://{payload['operator_id']}"]
    return []


def _evidence_refs(event: dict[str, Any], payload: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    refs = string_list(payload.get("evidence_refs"))
    raw_reasoning = decision.get("reasoning")
    reasoning: dict[str, Any] = cast(dict[str, Any], raw_reasoning) if isinstance(raw_reasoning, dict) else {}
    refs.extend(string_list(reasoning.get("evidence")))
    if event.get("event_id"):
        refs.append(f"event://{event['event_id']}")
    return refs


def _run_export_evidence_refs(run_export: dict[str, Any]) -> list[str]:
    refs: list[str] = []

    def add(ref: Any) -> None:
        if ref:
            refs.append(str(ref))

    artifacts = run_export.get("evidence_artifacts")
    if isinstance(artifacts, dict):
        for key in artifacts:
            add(f"artifact://{key}")
    elif isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict):
                add(artifact.get("artifact_key") or artifact.get("uri") or artifact.get("path"))
    raw_session = run_export.get("session")
    session: dict[str, Any] = cast(dict[str, Any], raw_session) if isinstance(raw_session, dict) else {}
    for key in ("remediation_safety", "trust_ladder", "integration_readiness"):
        add(_artifact_ref(session, key))
    for ref in mesh_brain_evidence_refs(session):
        add(ref)
    decision = run_export.get("decision_record")
    if isinstance(decision, dict):
        add(_execution_plan(decision).get("rollback_plan"))
    for ref in _approval_refs(run_export.get("approval_records")):
        add(ref)
    if run_export.get("export_id"):
        add(f"run_export://{run_export['export_id']}")
    if not refs and run_export.get("run_id"):
        add(f"run://{run_export['run_id']}")
    return list(dict.fromkeys(refs))


def _approval_refs(raw_records: Any) -> list[str]:
    if not isinstance(raw_records, list):
        return []
    refs: list[str] = []
    for approval in raw_records:
        if not isinstance(approval, dict):
            continue
        raw_ref = approval.get("authority_ref") or approval.get("ref")
        if raw_ref:
            refs.append(str(raw_ref))
            continue
        approval_id = approval.get("event_id") or approval.get("approval_id")
        if approval_id:
            refs.append(f"operator-approval://{approval_id}")
    return list(dict.fromkeys(refs))


def _artifact_ref(session: dict[str, Any], key: str) -> str | None:
    raw_artifacts = session.get("artifacts")
    artifacts: dict[str, Any] = cast(dict[str, Any], raw_artifacts) if isinstance(raw_artifacts, dict) else {}
    value = artifacts.get(key)
    if value is None:
        return None
    if isinstance(value, dict):
        raw_ref = value.get("uri") or value.get("path") or f"artifact://{key}"
        return str(raw_ref)
    return f"artifact://{key}"


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _service_owner_refs(ontological_state: dict[str, Any]) -> list[str]:
    return [
        entity["entity_id"]
        for entity in ontological_state.get("entities", [])
        if entity.get("entity_type") == "owner"
    ]
