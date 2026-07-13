from __future__ import annotations

import hashlib
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

from .contracts import Decision, EvaluationResult
from .schema_validation import SchemaValidationError, validate_payload

HSAI_ADMISSION_REQUEST_VERSION = "mesh.hsai_admission_request.v1"
HSAI_ADMISSION_REQUEST_V2_VERSION = "mesh.hsai_admission_request.v2"
HSAI_ADMISSION_DECISION_VERSION = "mesh.hsai_admission_decision.v1"
COMBINED_PROOF_PACKET_VERSION = "mesh.combined_proof_packet.v1"
COMBINED_PROOF_PACKET_VERIFICATION_VERSION = "mesh.combined_proof_packet_verification.v1"
HSAI_EXECUTION_CONTEXT_VERSION = "mesh.hsai_execution_context.v1"
HSAI_EXECUTION_CONTEXT_KEY = "_mesh_hsai_admission_context"
HSAI_FORMAL_BACKEND_RUN_OUTPUT_VERSION = "hsai-gateway-formal-backend-run-output-v1"
HSAI_FORMAL_BACKEND_RUN_ARTIFACT_VERSION = "hsai-gateway-formal-backend-run-artifact:v1"
HSAI_FORMAL_BACKEND_RUN_STATE_SLICE = "phase-276-hsai-gateway-formal-backend-run-inert-artifact-metadata"

DEFAULT_EXPLICIT_NONCLAIMS = (
    "does_not_claim_global_correctness",
    "does_not_claim_security_review_complete",
    "does_not_claim_production_certification",
    "does_not_claim_accepted_hsai_evidence",
    "does_not_claim_formal_proof",
)
DEFAULT_REQUESTED_CLAIMS = (
    "patch_applies_cleanly",
    "tests_passed",
    "no_protected_paths_modified",
)
DEFAULT_PROTECTED_REPO_PATHS = (".git", ".github", "AGENTS.md")
HSAI_FORMAL_BACKEND_REQUIRED_NONCLAIMS = (
    "not attestation evidence",
    "not proof",
    "not live provider evidence",
    "not accepted Evidence Ledger mutation",
    "not benchmark evidence",
    "not SOTA status",
    "not breakthrough status",
    "not production readiness",
    "not semantic correctness",
    "not authority to execute an action",
    "not formal proof evidence",
    "no formal backend was run",
    "metadata adapter only",
    "not full security",
    "not Level2+ evidence",
    "not score-axis population",
    "not proof of HSAI",
    "not source proof",
    "correspondence metadata only",
    "backend adapter metadata only",
    "not backend checked",
    "not proof artifact evidence",
    "candidate metadata only",
    "backend run artifact metadata only",
    "backend not run",
    "no proof artifact retained",
    "no checker transcript retained",
    "not accepted evidence",
)
HSAI_FORMAL_BACKEND_DECLARED_FILES = (
    "gateway-formal-backend-run/manifest.json",
    "gateway-formal-backend-run/adapter-request.json",
    "gateway-formal-backend-run/adapter-report.json",
    "gateway-formal-backend-run/run-summary.json",
    "gateway-formal-backend-run/correspondence-certificate-digest.json",
    "gateway-formal-backend-run/correspondence-output-manifest-digest.json",
    "gateway-formal-backend-run/source-digests.json",
    "gateway-formal-backend-run/toolchain-lock.json",
    "gateway-formal-backend-run/model-assumptions.json",
    "gateway-formal-backend-run/unsupported-rust-features.json",
    "gateway-formal-backend-run/proof-obligations.json",
    "gateway-formal-backend-run/redaction-report.json",
    "gateway-formal-backend-run/nonclaims.md",
)


class HsaiAdmissionAdapter(Protocol):
    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return a mesh.hsai_admission_decision.v1 payload."""


def repo_patch_requires_hsai(decision: Decision) -> bool:
    return bool(
        decision.execution_plan.get("system") == "repo_patch_service"
        and decision.execution_plan.get("action") == "investigate_and_patch"
    )


def build_hsai_admission_request(
    decision: Decision,
    evaluation: EvaluationResult,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    parameters = _dict(decision.execution_plan.get("parameters"))
    actor_ref = _dict(parameters.get("actor_ref"))
    evidence_packet = _evidence_packet(decision, evaluation)
    evidence_digest = sha256_digest(evidence_packet)
    explicit_nonclaims = (
        _string_list(parameters.get("explicit_nonclaims"))
        if "explicit_nonclaims" in parameters
        else list(DEFAULT_EXPLICIT_NONCLAIMS)
    )
    requested_claims = (
        _string_list(parameters.get("requested_claims"))
        if "requested_claims" in parameters
        else list(DEFAULT_REQUESTED_CLAIMS)
    )
    mesh_policy_id = _mesh_policy_id(decision, evaluation, parameters)

    request = {
        "schema_version": HSAI_ADMISSION_REQUEST_VERSION,
        "mesh_run_id": expected_mesh_run_id(decision),
        "mesh_action_id": expected_mesh_action_id(decision),
        "action_kind": "repo_patch",
        "actor_ref": {
            "actor_id": str(actor_ref.get("actor_id") or parameters.get("actor_id") or "mesh.orchestrator"),
            "team_id": str(actor_ref.get("team_id") or parameters.get("team_id") or "mesh.default"),
        },
        "mesh_policy_id": mesh_policy_id,
        "action_proposal_digest": sha256_digest(
            {
                "decision_id": decision.decision_id,
                "execution_plan": decision.execution_plan,
                "risk": decision.risk,
            }
        ),
        "candidate_payload_digest": sha256_digest(decision_payload_without_hsai_context(decision)),
        "evidence_packet_digest": evidence_digest,
        "attestation_refs": [
            {
                "kind": "mesh_runtime_proof_packet",
                "digest": evidence_digest,
            }
        ],
        "requested_claims": requested_claims,
        "explicit_nonclaims": explicit_nonclaims,
        "created_at": created_at or _now(),
    }
    validate_payload("hsai-admission-request.schema.json", request)
    return request


def build_hsai_admission_request_v2(
    decision: Decision,
    evaluation: EvaluationResult,
    preflight_receipt: dict[str, Any],
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    parameters = _dict(decision.execution_plan.get("parameters"))
    candidate_payload = _normalized_repo_patch_candidate(
        decision,
        evaluation,
        preflight_receipt,
    )
    candidate_digest = sha256_digest(candidate_payload)
    stage_results = _dict(evaluation.stage_results)
    pre_execution_evidence = {
        "schema_version": "mesh.repo_patch_pre_execution_evidence.v1",
        "decision_id": decision.decision_id,
        "evaluation_id": evaluation.evaluation_id,
        "evaluation_passed": evaluation.passed,
        "final_recommendation": evaluation.final_recommendation,
        "blocking_reasons": list(evaluation.blocking_reasons),
        "stage_results": stage_results,
        "stage_results_digest": sha256_digest(stage_results),
        "preflight_receipt": preflight_receipt,
    }
    evidence_digest = sha256_digest(pre_execution_evidence)
    actor_ref = candidate_payload["execution_plan"]["parameters"]["actor_ref"]
    explicit_nonclaims = (
        _string_list(parameters.get("explicit_nonclaims"))
        if "explicit_nonclaims" in parameters
        else list(DEFAULT_EXPLICIT_NONCLAIMS)
    )
    requested_claims = (
        _string_list(parameters.get("requested_claims"))
        if "requested_claims" in parameters
        else list(DEFAULT_REQUESTED_CLAIMS)
    )
    action_proposal = {
        "decision_id": candidate_payload["decision_id"],
        "execution_plan": candidate_payload["execution_plan"],
        "risk": candidate_payload["risk"],
    }
    request = {
        "schema_version": HSAI_ADMISSION_REQUEST_V2_VERSION,
        "mesh_run_id": candidate_payload["execution_plan"]["parameters"]["mesh_run_id"],
        "mesh_action_id": decision.decision_id,
        "action_kind": "repo_patch",
        "actor_ref": actor_ref,
        "mesh_policy_id": candidate_payload["execution_plan"]["parameters"]["mesh_policy_id"],
        "action_proposal_digest": sha256_digest(action_proposal),
        "candidate_payload_digest": candidate_digest,
        "evidence_packet_digest": evidence_digest,
        "attestation_refs": [
            {
                "kind": "mesh_repo_patch_preflight_receipt",
                "digest": evidence_digest,
            }
        ],
        "requested_claims": requested_claims,
        "explicit_nonclaims": explicit_nonclaims,
        "created_at": created_at or _now(),
        "candidate_payload": candidate_payload,
        "pre_execution_evidence": pre_execution_evidence,
    }
    validate_payload("hsai-admission-request-v2.schema.json", request)
    return request


def _normalized_repo_patch_candidate(
    decision: Decision,
    evaluation: EvaluationResult,
    preflight_receipt: dict[str, Any],
) -> dict[str, Any]:
    parameters = _dict(decision.execution_plan.get("parameters"))
    if decision.execution_plan.get("system") != "repo_patch_service" or decision.execution_plan.get(
        "action"
    ) != "investigate_and_patch":
        raise ValueError("HSAI v2 candidate is not the bounded repo-patch action")
    declared_action_id = parameters.get("mesh_action_id")
    if declared_action_id is not None and str(declared_action_id) != decision.decision_id:
        raise ValueError("HSAI v2 candidate mesh action id must equal the decision id")
    actor = _dict(parameters.get("actor_ref"))
    actor_ref = {
        "actor_id": str(actor.get("actor_id") or parameters.get("actor_id") or "mesh.orchestrator"),
        "team_id": str(actor.get("team_id") or parameters.get("team_id") or "mesh.default"),
    }
    patch_template = _dict(parameters.get("patch_template"))
    test_commands = parameters.get("test_commands")
    if not isinstance(test_commands, list) or not test_commands:
        raise ValueError("HSAI v2 candidate requires verification commands")
    declared_command_vectors: list[list[str]] = []
    for command in test_commands:
        if not isinstance(command, str):
            raise ValueError("HSAI v2 candidate verification command must be a string")
        argv = shlex.split(command)
        if not argv or any(not argument for argument in argv):
            raise ValueError("HSAI v2 candidate verification command is empty")
        declared_command_vectors.append(argv)
    raw_test_results = preflight_receipt.get("test_results")
    if not isinstance(raw_test_results, list) or len(raw_test_results) != len(declared_command_vectors):
        raise ValueError("HSAI v2 preflight commands do not match the declared verification commands")
    command_vectors: list[list[str]] = []
    for declared_argv, raw_result in zip(declared_command_vectors, raw_test_results, strict=True):
        if not isinstance(raw_result, dict):
            raise ValueError("HSAI v2 preflight test result must be an object")
        executed_argv = raw_result.get("argv")
        if (
            not isinstance(executed_argv, list)
            or not executed_argv
            or any(not isinstance(argument, str) or not argument for argument in executed_argv)
        ):
            raise ValueError("HSAI v2 preflight test argv is invalid")
        if not Path(executed_argv[0]).is_absolute() or executed_argv[1:] != declared_argv[1:]:
            raise ValueError("HSAI v2 preflight argv is not bound to the declared verification command")
        command_vectors.append(list(executed_argv))
    mesh_policy_id = _mesh_policy_id(decision, evaluation, parameters)
    return {
        "decision_id": decision.decision_id,
        "trigger_id": decision.trigger_id,
        "decision_type": decision.decision_type,
        "autonomy_tier": decision.autonomy_tier,
        "summary": decision.summary,
        "reasoning": decision.reasoning,
        "expected_outcome": decision.expected_outcome,
        "risk": decision.risk,
        "confidence": decision.confidence,
        "execution_plan": {
            "system": "repo_patch_service",
            "action": "investigate_and_patch",
            "parameters": {
                "repo_path": str(parameters.get("repo_path") or ""),
                "allowed_paths": _string_list(parameters.get("allowed_paths")),
                "protected_paths": (
                    _string_list(parameters.get("protected_paths"))
                    if "protected_paths" in parameters
                    else list(DEFAULT_PROTECTED_REPO_PATHS)
                ),
                "patch_template": {
                    "target_file": str(patch_template.get("target_file") or ""),
                    "find": str(patch_template.get("find") or ""),
                    "replace": str(patch_template.get("replace") or ""),
                },
                "test_commands": command_vectors,
                "mesh_run_id": expected_mesh_run_id(decision),
                "mesh_action_id": decision.decision_id,
                "mesh_policy_id": mesh_policy_id,
                "actor_ref": actor_ref,
            },
            "rollback_plan": str(decision.execution_plan.get("rollback_plan") or ""),
        },
    }


def evaluate_hsai_gate(
    request: dict[str, Any],
    adapter: HsaiAdmissionAdapter,
) -> dict[str, Any]:
    try:
        raw_decision = adapter.admit(request)
    except Exception as exc:  # fail closed across subprocess/service boundaries
        raw_decision = _error_decision(request, f"hsai_unavailable:{type(exc).__name__}:{exc}")

    try:
        validate_hsai_decision(request, raw_decision)
        decision = raw_decision
    except (SchemaValidationError, ValueError) as exc:
        decision = _error_decision(request, f"hsai_malformed_or_mismatched:{exc}")
        validate_hsai_decision(request, decision)

    gate = {
        "allowed": decision["decision"] == "allow",
        "authority_eligible": getattr(adapter, "authority_eligible", False) is True,
        "request": request,
        "decision": decision,
        "request_digest": sha256_digest(request),
        "decision_digest": decision["decision_digest"],
        "candidate_digest": decision["candidate_digest"],
        "reason_codes": list(decision.get("reason_codes") or []),
    }
    validate_bridge_gate(gate)
    return gate


def validate_hsai_decision(request: dict[str, Any], decision: dict[str, Any]) -> None:
    _validate_hsai_request_payload(request)
    validate_payload("hsai-admission-decision.schema.json", decision)
    expected_request_digest = sha256_digest(request)
    _require_digest("hsai request digest", decision["request_digest"])
    _require_digest("hsai candidate digest", decision["candidate_digest"])
    _require_digest("hsai decision digest", decision["decision_digest"])
    for field in ("action_proposal_digest", "candidate_payload_digest", "evidence_packet_digest"):
        _require_digest(f"hsai request {field}", request[field])
    if decision["request_digest"] != expected_request_digest:
        raise ValueError("hsai request digest mismatch")
    if decision["mesh_run_id"] != request["mesh_run_id"]:
        raise ValueError("hsai mesh run id mismatch")
    if decision["mesh_action_id"] != request["mesh_action_id"]:
        raise ValueError("hsai mesh action id mismatch")
    if decision["action_kind"] != request["action_kind"]:
        raise ValueError("hsai action kind mismatch")
    if decision["candidate_digest"] != request["candidate_payload_digest"]:
        raise ValueError("hsai candidate digest mismatch")
    if decision["admission_policy_id"] != request["mesh_policy_id"]:
        raise ValueError("hsai policy id mismatch")
    if decision["decision"] == "allow" and not request["explicit_nonclaims"]:
        raise ValueError("hsai request missing explicit nonclaims")
    missing_nonclaims = sorted(set(request["explicit_nonclaims"]) - set(decision["enforced_nonclaims"]))
    if missing_nonclaims:
        raise ValueError(f"hsai enforced nonclaims missing: {missing_nonclaims}")
    expected_decision_digest = decision_digest(decision)
    if decision["decision_digest"] != expected_decision_digest:
        raise ValueError("hsai decision digest mismatch")


def validate_bridge_gate(
    gate: dict[str, Any],
    *,
    expected_decision: Decision | None = None,
    expected_evaluation: EvaluationResult | None = None,
    require_mesh_policy_approved: bool | None = None,
) -> None:
    request = _dict(gate.get("request"))
    decision = _dict(gate.get("decision"))
    validate_hsai_decision(request, decision)
    if gate.get("request_digest") != sha256_digest(request):
        raise ValueError("bridge gate request digest mismatch")
    if gate.get("decision_digest") != decision["decision_digest"]:
        raise ValueError("bridge gate decision digest mismatch")
    if gate.get("candidate_digest") != request["candidate_payload_digest"]:
        raise ValueError("bridge gate candidate digest mismatch")
    for field in (
        "mesh_run_id",
        "mesh_action_id",
        "mesh_policy_id",
        "action_proposal_digest",
        "candidate_payload_digest",
        "evidence_packet_digest",
    ):
        if not str(request.get(field) or "").strip():
            raise ValueError(f"bridge gate missing {field}")
    if request.get("action_kind") != "repo_patch":
        raise ValueError("bridge gate action kind mismatch")
    if expected_decision is not None:
        if request.get("schema_version") == HSAI_ADMISSION_REQUEST_V2_VERSION:
            candidate_payload = _dict(request.get("candidate_payload"))
            if request["candidate_payload_digest"] != sha256_digest(candidate_payload):
                raise ValueError("bridge gate v2 candidate payload digest mismatch")
            evidence = _dict(request.get("pre_execution_evidence"))
            if request["evidence_packet_digest"] != sha256_digest(evidence):
                raise ValueError("bridge gate v2 evidence packet digest mismatch")
            expected_candidate_digest = request["candidate_payload_digest"]
        else:
            expected_candidate_digest = sha256_digest(
                decision_payload_without_hsai_context(expected_decision)
            )
        if request["mesh_run_id"] != expected_mesh_run_id(expected_decision):
            raise ValueError("bridge gate mesh run id mismatch")
        if request["mesh_action_id"] != expected_mesh_action_id(expected_decision):
            raise ValueError("bridge gate mesh action id mismatch")
        if request["candidate_payload_digest"] != expected_candidate_digest:
            raise ValueError("bridge gate current candidate digest mismatch")
        proposal_candidate = (
            _dict(request.get("candidate_payload"))
            if request.get("schema_version") == HSAI_ADMISSION_REQUEST_V2_VERSION
            else expected_decision.to_dict()
        )
        expected_proposal_digest = sha256_digest(
            {
                "decision_id": proposal_candidate["decision_id"],
                "execution_plan": proposal_candidate["execution_plan"],
                "risk": proposal_candidate["risk"],
            }
        )
        if request["action_proposal_digest"] != expected_proposal_digest:
            raise ValueError("bridge gate action proposal digest mismatch")
    if expected_evaluation is not None:
        if expected_decision is not None:
            expected_policy_id = _mesh_policy_id(
                expected_decision,
                expected_evaluation,
                _dict(expected_decision.execution_plan.get("parameters")),
            )
            if request["mesh_policy_id"] != expected_policy_id:
                raise ValueError("bridge gate mesh policy id mismatch")
            if request.get("schema_version") == HSAI_ADMISSION_REQUEST_V2_VERSION:
                expected_candidate = _normalized_repo_patch_candidate(
                    expected_decision,
                    expected_evaluation,
                    _dict(request.get("pre_execution_evidence")).get("preflight_receipt", {}),
                )
                if request.get("candidate_payload") != expected_candidate:
                    raise ValueError("bridge gate v2 current candidate payload mismatch")
                evidence = _dict(request.get("pre_execution_evidence"))
                if evidence.get("decision_id") != expected_decision.decision_id:
                    raise ValueError("bridge gate v2 evidence decision mismatch")
                if evidence.get("evaluation_id") != expected_evaluation.evaluation_id:
                    raise ValueError("bridge gate v2 evaluation id mismatch")
                if evidence.get("evaluation_passed") is not expected_evaluation.passed:
                    raise ValueError("bridge gate v2 evaluation verdict mismatch")
                if evidence.get("final_recommendation") != expected_evaluation.final_recommendation:
                    raise ValueError("bridge gate v2 recommendation mismatch")
                if evidence.get("blocking_reasons") != list(expected_evaluation.blocking_reasons):
                    raise ValueError("bridge gate v2 blocking reasons mismatch")
                if evidence.get("stage_results") != expected_evaluation.stage_results:
                    raise ValueError("bridge gate v2 stage results mismatch")
                if evidence.get("stage_results_digest") != sha256_digest(
                    expected_evaluation.stage_results
                ):
                    raise ValueError("bridge gate v2 stage results digest mismatch")
        mesh_allowed = mesh_policy_allows(expected_evaluation)
        if require_mesh_policy_approved is True and not mesh_allowed:
            raise ValueError("bridge gate Mesh policy is not approved")
    if decision["decision"] == "allow" and gate.get("allowed") is not True:
        raise ValueError("bridge gate allow flag mismatch")
    if decision["decision"] != "allow" and gate.get("allowed") is True:
        raise ValueError("bridge gate deny/error flag mismatch")


def mesh_policy_allows(evaluation: EvaluationResult) -> bool:
    return bool(evaluation.passed and evaluation.final_recommendation == "execute")


def _validate_hsai_request_payload(request: dict[str, Any]) -> None:
    schema_version = request.get("schema_version")
    if schema_version == HSAI_ADMISSION_REQUEST_VERSION:
        validate_payload("hsai-admission-request.schema.json", request)
        return
    if schema_version == HSAI_ADMISSION_REQUEST_V2_VERSION:
        validate_payload("hsai-admission-request-v2.schema.json", request)
        return
    raise ValueError("unsupported HSAI admission request schema version")


def build_combined_proof_packet(
    gate: dict[str, Any],
    *,
    mesh_policy_approved: bool,
    action_execution_result: dict[str, Any],
    executor_receipt_digest: str | None = None,
    created_at: str | None = None,
    expected_decision: Decision | None = None,
    expected_evaluation: EvaluationResult | None = None,
) -> dict[str, Any]:
    validate_bridge_gate(
        gate,
        expected_decision=expected_decision,
        expected_evaluation=expected_evaluation,
        require_mesh_policy_approved=True if mesh_policy_approved else None,
    )
    request = gate["request"]
    decision = gate["decision"]
    packet = {
        "schema_version": COMBINED_PROOF_PACKET_VERSION,
        "mesh_run_id": request["mesh_run_id"],
        "mesh_action_id": request["mesh_action_id"],
        "mesh_policy_id": request["mesh_policy_id"],
        "hsai_request_digest": gate["request_digest"],
        "hsai_decision_digest": gate["decision_digest"],
        "hsai_candidate_digest": gate["candidate_digest"],
        "hsai_decision": decision["decision"],
        "nonclaims": list(decision["enforced_nonclaims"]),
        "action_execution_result": action_execution_result,
        "executor_receipt_digest": executor_receipt_digest,
        "audit_export_metadata": {
            "exportable": True,
            "format": "mesh_proof_export.v1",
            "included_in_execution_external_refs": True,
            "mesh_policy_approved": mesh_policy_approved,
            "canonical_digest": "json.sha256.sorted_keys.compact.v1",
            "hsai_request_schema_version": request["schema_version"],
            "hsai_decision_schema_version": decision["schema_version"],
            "replay_protected": True,
            "state_slice": "mesh.hsai_admission_bridge.v1",
            "formal_evidence_metadata": decision["formal_evidence_metadata"],
        },
        "created_at": created_at or _now(),
    }
    validate_combined_proof_packet(gate, packet)
    return packet


def validate_combined_proof_packet(gate: dict[str, Any], packet: dict[str, Any]) -> None:
    validate_bridge_gate(gate)
    validate_payload("combined-proof-packet.schema.json", packet)
    request = gate["request"]
    for packet_field, request_field in (
        ("mesh_run_id", "mesh_run_id"),
        ("mesh_action_id", "mesh_action_id"),
        ("mesh_policy_id", "mesh_policy_id"),
    ):
        if packet[packet_field] != request[request_field]:
            raise ValueError(f"combined proof packet {packet_field} mismatch")
    if packet["hsai_request_digest"] != gate["request_digest"]:
        raise ValueError("combined proof packet request digest mismatch")
    if packet["hsai_decision_digest"] != gate["decision_digest"]:
        raise ValueError("combined proof packet decision digest mismatch")
    if packet["hsai_candidate_digest"] != gate["candidate_digest"]:
        raise ValueError("combined proof packet candidate digest mismatch")
    if packet["hsai_decision"] != gate["decision"]["decision"]:
        raise ValueError("combined proof packet HSAI decision mismatch")
    if packet["nonclaims"] != list(gate["decision"]["enforced_nonclaims"]):
        raise ValueError("combined proof packet nonclaims mismatch")
    audit = _dict(packet.get("audit_export_metadata"))
    if audit.get("exportable") is not True:
        raise ValueError("combined proof packet must be exportable")
    if audit.get("format") != "mesh_proof_export.v1":
        raise ValueError("combined proof packet export format mismatch")
    if audit.get("included_in_execution_external_refs") is not True:
        raise ValueError("combined proof packet missing execution export assertion")
    if audit.get("state_slice") != "mesh.hsai_admission_bridge.v1":
        raise ValueError("combined proof packet state slice mismatch")
    if audit.get("hsai_request_schema_version") != request["schema_version"]:
        raise ValueError("combined proof packet request schema version mismatch")
    if audit.get("hsai_decision_schema_version") != gate["decision"]["schema_version"]:
        raise ValueError("combined proof packet decision schema version mismatch")
    if audit.get("canonical_digest") != "json.sha256.sorted_keys.compact.v1":
        raise ValueError("combined proof packet canonical digest assertion mismatch")
    if audit.get("replay_protected") is not True:
        raise ValueError("combined proof packet replay protection assertion missing")
    if audit.get("formal_evidence_metadata") != gate["decision"]["formal_evidence_metadata"]:
        raise ValueError("combined proof packet formal metadata mismatch")
    status = str(_dict(packet.get("action_execution_result")).get("status") or "")
    if status == "blocked" and packet.get("executor_receipt_digest") is not None:
        raise ValueError("blocked combined proof packet cannot include executor receipt")
    if status in {"executed", "failed"} and not packet.get("executor_receipt_digest"):
        raise ValueError("executed combined proof packet requires executor receipt")
    if "accepted_claims" in packet or "accepted_claims" in _dict(packet.get("action_execution_result")):
        raise ValueError("combined proof packet cannot promote accepted claims")


def verify_combined_proof_packet_payload(
    *,
    packet: dict[str, Any],
    request: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    try:
        validate_hsai_decision(request, decision)
        gate = _gate_from_verified_contracts(request, decision)
        validate_combined_proof_packet(gate, packet)
        _validate_combined_proof_claim_adequacy(request, decision, packet)
    except (SchemaValidationError, ValueError) as exc:
        issues.append(str(exc))
    return {
        "schema_version": COMBINED_PROOF_PACKET_VERIFICATION_VERSION,
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "mesh_run_id": packet.get("mesh_run_id"),
        "mesh_action_id": packet.get("mesh_action_id"),
        "mesh_policy_id": packet.get("mesh_policy_id"),
        "hsai_request_digest": packet.get("hsai_request_digest"),
        "hsai_decision_digest": packet.get("hsai_decision_digest"),
        "hsai_candidate_digest": packet.get("hsai_candidate_digest"),
        "hsai_decision": packet.get("hsai_decision"),
    }


def _gate_from_verified_contracts(request: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed": decision["decision"] == "allow",
        "request": request,
        "decision": decision,
        "request_digest": sha256_digest(request),
        "decision_digest": decision["decision_digest"],
        "candidate_digest": decision["candidate_digest"],
        "reason_codes": list(decision.get("reason_codes") or []),
    }


def _validate_combined_proof_claim_adequacy(
    request: dict[str, Any],
    decision: dict[str, Any],
    packet: dict[str, Any],
) -> None:
    accepted_claims = set(_string_list(decision.get("accepted_claims")))
    requested_claims = set(_string_list(request.get("requested_claims")))
    if decision["decision"] == "allow":
        if not packet.get("nonclaims"):
            raise ValueError("allowed combined proof packet must preserve nonclaims")
        if not accepted_claims:
            raise ValueError("allowed HSAI decision must preserve accepted claims")
        if not accepted_claims.issubset(requested_claims):
            raise ValueError("allowed HSAI decision accepted claims exceed requested claims")
    else:
        if accepted_claims:
            raise ValueError("non-allow HSAI decision cannot preserve accepted claims")
        action_result = _dict(packet.get("action_execution_result"))
        if action_result.get("status") != "blocked":
            raise ValueError("non-allow combined proof packet must be blocked")
        missing_reason_codes = sorted(
            set(_string_list(decision.get("reason_codes"))) - set(_string_list(action_result.get("hsai_reason_codes")))
        )
        if missing_reason_codes:
            raise ValueError(f"non-allow combined proof packet missing HSAI reason codes: {missing_reason_codes}")
    formal_metadata = _dict(_dict(packet.get("audit_export_metadata")).get("formal_evidence_metadata"))
    if not str(formal_metadata.get("nonclaim") or "").strip():
        raise ValueError("combined proof packet formal metadata must preserve nonclaim boundary")


def attach_hsai_execution_context(
    decision: Decision,
    gate: dict[str, Any],
    execution_permit: dict[str, Any] | None = None,
) -> Decision:
    validate_bridge_gate(gate, expected_decision=decision)
    payload = decision_payload_without_hsai_context(decision)
    plan = dict(payload["execution_plan"])
    parameters = dict(plan.get("parameters") or {})
    context = {
        "schema_version": HSAI_EXECUTION_CONTEXT_VERSION,
        "request": gate["request"],
        "decision": gate["decision"],
        "request_digest": gate["request_digest"],
        "decision_digest": gate["decision_digest"],
        "candidate_digest": gate["candidate_digest"],
    }
    if execution_permit is not None:
        validate_payload("repo-patch-execution-permit.schema.json", execution_permit)
        context["execution_permit"] = execution_permit
    parameters[HSAI_EXECUTION_CONTEXT_KEY] = context
    plan["parameters"] = parameters
    payload["execution_plan"] = plan
    return Decision.from_dict(payload)


def validate_hsai_execution_context(decision: Decision) -> dict[str, Any]:
    parameters = _dict(decision.execution_plan.get("parameters"))
    context = _dict(parameters.get(HSAI_EXECUTION_CONTEXT_KEY))
    if context.get("schema_version") != HSAI_EXECUTION_CONTEXT_VERSION:
        raise ValueError("missing or unsupported HSAI execution context")
    request = _dict(context.get("request"))
    admission_decision = _dict(context.get("decision"))
    validate_hsai_decision(request, admission_decision)
    if request["mesh_run_id"] != expected_mesh_run_id(decision):
        raise ValueError("HSAI execution context mesh run id mismatch")
    if request["mesh_action_id"] != expected_mesh_action_id(decision):
        raise ValueError("HSAI execution context mesh action id mismatch")
    if context.get("request_digest") != sha256_digest(request):
        raise ValueError("HSAI execution context request digest mismatch")
    if context.get("decision_digest") != admission_decision["decision_digest"]:
        raise ValueError("HSAI execution context decision digest mismatch")
    if context.get("candidate_digest") != request["candidate_payload_digest"]:
        raise ValueError("HSAI execution context candidate digest mismatch")
    if request.get("schema_version") == HSAI_ADMISSION_REQUEST_V2_VERSION:
        validate_bridge_gate(
            _gate_from_verified_contracts(request, admission_decision),
            expected_decision=decision,
        )
    elif request["candidate_payload_digest"] != sha256_digest(decision_payload_without_hsai_context(decision)):
        raise ValueError("HSAI execution context decision payload mismatch")
    if admission_decision["decision"] != "allow":
        raise ValueError("HSAI execution context is not allow")
    return context


def repo_patch_admission_failure(decision: Decision) -> dict[str, Any] | None:
    try:
        validate_hsai_execution_context(decision)
    except ValueError as exc:
        return {
            "status": "failed",
            "external_refs": {},
            "failure": {"reason": "hsai_admission_context_invalid", "detail": str(exc)},
            "retryable": False,
        }
    return None


def local_hsai_allow_decision(
    request: dict[str, Any],
    *,
    created_at: str | None = None,
    formal_backend_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    gate_result = "pass"
    admission = "allow"
    if not request.get("explicit_nonclaims"):
        admission = "deny"
        gate_result = "fail"
        reasons.append("missing_explicit_nonclaims")

    decision = {
        "schema_version": HSAI_ADMISSION_DECISION_VERSION,
        "decision_id": f"hsai_decision_{request['mesh_action_id']}",
        "mesh_run_id": request["mesh_run_id"],
        "mesh_action_id": request["mesh_action_id"],
        "action_kind": request["action_kind"],
        "request_digest": sha256_digest(request),
        "candidate_digest": request["candidate_payload_digest"],
        "decision": admission,
        "admission_policy_id": request["mesh_policy_id"],
        "gate_results": [
            {
                "gate": "candidate_evidence",
                "result": gate_result,
                "metadata_digest": request["evidence_packet_digest"],
            },
            {
                "gate": "nonclaim_enforcement",
                "result": gate_result,
                "metadata_digest": sha256_digest(request.get("explicit_nonclaims") or []),
            },
        ],
        "accepted_claims": list(request["requested_claims"]) if admission == "allow" else [],
        "enforced_nonclaims": list(request.get("explicit_nonclaims") or []),
        "formal_evidence_metadata": formal_backend_metadata or {
            "backend": "hsai-local-adapter",
            "phase_range": "265-277",
            "backend_run_id": "local_metadata_only",
            "metadata_digest": sha256_digest(
                {
                    "phase_range": "265-277",
                    "request_digest": sha256_digest(request),
                    "nonclaims": request.get("explicit_nonclaims") or [],
                }
            ),
            "nonclaim": "local metadata only; not formal proof, accepted evidence, or production certification",
        },
        "reason_codes": reasons,
        "created_at": created_at or _now(),
    }
    decision["decision_digest"] = decision_digest(decision)
    validate_payload("hsai-admission-decision.schema.json", decision)
    return decision


def load_hsai_formal_backend_run_metadata(bundle_root: str | Path) -> dict[str, Any]:
    root = Path(bundle_root)
    if not str(root).strip():
        raise ValueError("HSAI formal backend bundle root is empty")
    if not root.exists():
        raise ValueError("HSAI formal backend bundle root does not exist")
    if root.is_symlink():
        raise ValueError("HSAI formal backend bundle root cannot be a symlink")
    if not root.is_dir():
        raise ValueError("HSAI formal backend bundle root must be a directory")

    bundle_dir = root / "gateway-formal-backend-run"
    if bundle_dir.is_symlink():
        raise ValueError("HSAI formal backend bundle directory cannot be a symlink")
    if not bundle_dir.is_dir():
        raise ValueError("HSAI formal backend bundle directory is missing")

    declared_paths = {Path(path) for path in HSAI_FORMAL_BACKEND_DECLARED_FILES}
    declared_names = {path.name for path in declared_paths}
    declared_names.update(f"{path.name}.sha256" for path in declared_paths)
    actual_names = {path.name for path in bundle_dir.iterdir()}
    extra_names = sorted(actual_names - declared_names)
    if extra_names:
        raise ValueError(f"HSAI formal backend bundle has undeclared files: {extra_names}")

    file_digests: dict[str, str] = {}
    for logical_path in HSAI_FORMAL_BACKEND_DECLARED_FILES:
        path = root / logical_path
        sidecar_path = root / f"{logical_path}.sha256"
        _validate_declared_file(path, logical_path)
        _validate_declared_file(sidecar_path, f"{logical_path}.sha256")
        digest_hex = _sha256_file_hex(path)
        expected_digest = sidecar_path.read_text(encoding="utf-8").strip()
        if expected_digest != digest_hex:
            raise ValueError(f"HSAI formal backend sidecar digest mismatch: {logical_path}")
        file_digests[logical_path] = f"sha256:{digest_hex}"

    manifest = _read_json_object(root / "gateway-formal-backend-run/manifest.json")
    run_summary = _read_json_object(root / "gateway-formal-backend-run/run-summary.json")
    redaction_report = _read_json_object(root / "gateway-formal-backend-run/redaction-report.json")
    _validate_formal_backend_manifest(manifest)
    _validate_formal_backend_run_summary(run_summary)
    _validate_formal_backend_redaction(redaction_report)

    run_nonclaims = set(_string_list(run_summary.get("nonclaims")))
    missing_nonclaims = sorted(set(HSAI_FORMAL_BACKEND_REQUIRED_NONCLAIMS) - run_nonclaims)
    if missing_nonclaims:
        raise ValueError(f"HSAI formal backend metadata missing nonclaims: {missing_nonclaims}")

    manifest_declared = set(_string_list(manifest.get("declared_files")))
    if manifest_declared != set(HSAI_FORMAL_BACKEND_DECLARED_FILES):
        raise ValueError("HSAI formal backend manifest declared files mismatch")
    manifest_digest_keys = set(_dict(manifest.get("declared_file_digests")).keys())
    expected_digest_keys = set(HSAI_FORMAL_BACKEND_DECLARED_FILES) - {"gateway-formal-backend-run/manifest.json"}
    if manifest_digest_keys != expected_digest_keys:
        raise ValueError("HSAI formal backend manifest declared file digest keys mismatch")

    return {
        "backend": "hsai-formal-backend-run-bundle",
        "phase_range": "265-279",
        "backend_run_id": str(run_summary["run_id"]),
        "metadata_digest": sha256_digest(
            {
                "manifest": manifest,
                "run_summary": run_summary,
                "declared_file_sidecars": file_digests,
            }
        ),
        "bundle_root": str(root),
        "bundle_manifest_schema_version": manifest["schema_version"],
        "run_summary_schema_version": run_summary["schema_version"],
        "state_slice": run_summary["state_slice"],
        "execution_mode": run_summary["execution_mode"],
        "exit_status": run_summary["exit_status"],
        "checker_status": run_summary["checker_status"],
        "backend_kind": run_summary["backend_kind"],
        "tool_name": run_summary["tool_name"],
        "tool_version": run_summary["tool_version"],
        "adapter_request_digest": run_summary["adapter_request_digest"],
        "adapter_report_digest": run_summary["adapter_report_digest"],
        "correspondence_certificate_digest": run_summary["correspondence_certificate_digest"],
        "output_manifest_digest": run_summary["output_manifest_digest"],
        "run_summary_file_digest": file_digests["gateway-formal-backend-run/run-summary.json"],
        "manifest_file_digest": file_digests["gateway-formal-backend-run/manifest.json"],
        "claim_boundary": run_summary["claim_boundary"],
        "nonclaims": sorted(run_nonclaims),
        "nonclaim": "HSAI formal backend run bundle metadata only; not formal proof, accepted evidence, Level2+ evidence, production certification, or authority to execute.",
    }


def sha256_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def decision_digest(decision: dict[str, Any]) -> str:
    payload = dict(decision)
    payload.pop("decision_digest", None)
    return sha256_digest(payload)


def executor_receipt_digest(status: str, external_refs: dict[str, Any], failure: dict[str, Any] | None) -> str:
    return sha256_digest({"status": status, "external_refs": external_refs, "failure": failure})


def decision_payload_without_hsai_context(decision: Decision) -> dict[str, Any]:
    payload = cast(dict[str, Any], decision.to_dict())
    parameters = _dict(payload["execution_plan"].get("parameters"))
    if HSAI_EXECUTION_CONTEXT_KEY in parameters:
        parameters = dict(parameters)
        parameters.pop(HSAI_EXECUTION_CONTEXT_KEY, None)
        payload["execution_plan"] = dict(payload["execution_plan"])
        payload["execution_plan"]["parameters"] = parameters
    return payload


def _error_decision(request: dict[str, Any], reason: str) -> dict[str, Any]:
    decision = {
        "schema_version": HSAI_ADMISSION_DECISION_VERSION,
        "decision_id": f"hsai_error_{request.get('mesh_action_id', 'unknown')}",
        "mesh_run_id": str(request.get("mesh_run_id") or ""),
        "mesh_action_id": str(request.get("mesh_action_id") or ""),
        "action_kind": str(request.get("action_kind") or ""),
        "request_digest": sha256_digest(request),
        "candidate_digest": str(request.get("candidate_payload_digest") or ""),
        "decision": "error",
        "admission_policy_id": str(request.get("mesh_policy_id") or ""),
        "gate_results": [{"gate": "bridge_adapter", "result": "error", "metadata_digest": sha256_digest(reason)}],
        "accepted_claims": [],
        "enforced_nonclaims": list(request.get("explicit_nonclaims") or []),
        "formal_evidence_metadata": {
            "backend": "hsai-bridge-adapter",
            "phase_range": "265-277",
            "backend_run_id": "unavailable_or_invalid",
            "metadata_digest": sha256_digest(reason),
            "nonclaim": "error metadata only; not formal proof, accepted evidence, or production certification",
        },
        "reason_codes": [reason],
        "created_at": _now(),
    }
    decision["decision_digest"] = decision_digest(decision)
    return decision


def _evidence_packet(decision: Decision, evaluation: EvaluationResult) -> dict[str, Any]:
    return {
        "schema_version": "mesh.repo_patch_evidence_packet.v1",
        "decision_id": decision.decision_id,
        "decision_reasoning": decision.reasoning,
        "evaluation_id": evaluation.evaluation_id,
        "evaluation_stage_results": evaluation.stage_results,
        "blocking_reasons": evaluation.blocking_reasons,
    }


def _mesh_policy_id(decision: Decision, evaluation: EvaluationResult, parameters: dict[str, Any]) -> str:
    explicit = parameters.get("mesh_policy_id")
    if explicit:
        return str(explicit)
    policy_validation = _dict(evaluation.stage_results.get("policy_validation"))
    policy_id = policy_validation.get("policy_id") or policy_validation.get("policy_ref")
    if policy_id:
        return str(policy_id)
    return f"mesh_policy://{decision.autonomy_tier}/{evaluation.evaluation_id}"


def expected_mesh_run_id(decision: Decision) -> str:
    parameters = _dict(decision.execution_plan.get("parameters"))
    return str(parameters.get("mesh_run_id") or parameters.get("run_id") or f"run_{decision.trigger_id}")


def expected_mesh_action_id(decision: Decision) -> str:
    parameters = _dict(decision.execution_plan.get("parameters"))
    return str(parameters.get("mesh_action_id") or decision.decision_id)


def _validate_declared_file(path: Path, logical_path: str) -> None:
    if not path.exists():
        raise ValueError(f"HSAI formal backend declared file missing: {logical_path}")
    if path.is_symlink():
        raise ValueError(f"HSAI formal backend declared file cannot be a symlink: {logical_path}")
    if not path.is_file():
        raise ValueError(f"HSAI formal backend declared path must be a file: {logical_path}")


def _sha256_file_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"HSAI formal backend JSON file must contain an object: {path.name}")
    return payload


def _validate_formal_backend_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != HSAI_FORMAL_BACKEND_RUN_OUTPUT_VERSION:
        raise ValueError("HSAI formal backend manifest schema version mismatch")
    if manifest.get("state_slice") != HSAI_FORMAL_BACKEND_RUN_STATE_SLICE:
        raise ValueError("HSAI formal backend manifest state slice mismatch")
    for field in ("creates_accepted_evidence", "creates_level2_evidence", "populates_score_axes", "grants_authority"):
        if manifest.get(field) is not False:
            raise ValueError(f"HSAI formal backend manifest escalates {field}")


def _validate_formal_backend_run_summary(run_summary: dict[str, Any]) -> None:
    if run_summary.get("schema_version") != HSAI_FORMAL_BACKEND_RUN_ARTIFACT_VERSION:
        raise ValueError("HSAI formal backend run-summary schema version mismatch")
    if run_summary.get("state_slice") != HSAI_FORMAL_BACKEND_RUN_STATE_SLICE:
        raise ValueError("HSAI formal backend run-summary state slice mismatch")
    if not str(run_summary.get("run_id") or "").strip():
        raise ValueError("HSAI formal backend run-summary missing run id")
    if run_summary.get("execution_mode") != "NotRun":
        raise ValueError("HSAI formal backend run-summary execution mode must be NotRun")
    if run_summary.get("exit_status") != "NotRun":
        raise ValueError("HSAI formal backend run-summary exit status must be NotRun")
    if run_summary.get("checker_status") != "NotRun":
        raise ValueError("HSAI formal backend run-summary checker status must be NotRun")
    for field in (
        "creates_accepted_evidence",
        "creates_level2_evidence",
        "populates_score_axes",
        "grants_authority",
        "semantic_correctness_claimed",
        "production_readiness_claimed",
        "sota_claimed",
        "full_security_claimed",
    ):
        if run_summary.get(field) is not False:
            raise ValueError(f"HSAI formal backend run-summary escalates {field}")
    if run_summary.get("candidate_proof_artifact_ref") is not None:
        raise ValueError("HSAI formal backend run-summary includes proof artifact reference")
    if run_summary.get("candidate_checker_transcript_ref") is not None:
        raise ValueError("HSAI formal backend run-summary includes checker transcript reference")
    if run_summary.get("candidate_tool_log_summary_digest") is not None:
        raise ValueError("HSAI formal backend run-summary includes tool log digest")
    for text in _string_list(run_summary.get("claim_text")):
        lowered = text.lower()
        if any(forbidden in lowered for forbidden in ("production ready", "sota", "breakthrough", "full security")):
            raise ValueError("HSAI formal backend run-summary contains forbidden public claim text")


def _validate_formal_backend_redaction(redaction_report: dict[str, Any]) -> None:
    for field, value in redaction_report.items():
        if value is not False:
            raise ValueError(f"HSAI formal backend redaction report retained {field}")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    return sorted(str(item) for item in value) if isinstance(value, list) else []


def _require_digest(label: str, value: Any) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{label} is not a canonical sha256 digest")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
