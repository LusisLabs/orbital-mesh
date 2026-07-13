"""Execute approved plans through Mesh orchestration adapters."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from shared.mesh_runtime import (
    Decision,
    EvaluationResult,
    ExecutionRecord,
    RuntimeConfig,
    build_readiness,
    log_runtime_event,
    resolve_integrations_config,
)
from shared.mesh_runtime.execution_attempts import (
    ExecutionAttemptStore,
    dispatched_without_outcome,
    has_terminal_outcome,
)
from shared.mesh_runtime.hsai_bridge import (
    HsaiAdmissionAdapter,
    build_combined_proof_packet,
    build_hsai_admission_request,
    build_hsai_admission_request_v2,
    evaluate_hsai_gate,
    executor_receipt_digest,
    mesh_policy_allows,
    repo_patch_requires_hsai,
    validate_bridge_gate,
    validate_combined_proof_packet,
)
from shared.mesh_runtime.repo_patch_authority import RepoPatchAuthorityClient, RepoPatchAuthorityError

from .adapters_common import CliExecutionResult
from .goose_adapter import GooseAdapter, GooseCliAdapter, NativeGooseAdapter
from .hermes_adapter import HermesAdapter, HermesCliAdapter, NativeHermesAdapter
from .hsai_bridge_adapter import build_hsai_admission_adapter
from .repo_patch_authority_adapter import build_repo_patch_authority_client


REPO_PATCH_REVIEW_ONLY_STATE_SLICE = "mesh.repo_patch_review_only_boundary.v1"
REPO_PATCH_AUTHORITY_ORCHESTRATION_STATE_SLICE = "mesh.repo_patch_authority_orchestration.v1"
_REPO_PATCH_REVIEW_FLAGS = {
    "repo_patch_review_only": True,
    "repo_patch_final_parameters_unchanged": True,
    "repo_patch_authority_invoked": False,
    "repo_patch_authority_credentials_forwarded": False,
    "repo_patch_review_state_slice": REPO_PATCH_REVIEW_ONLY_STATE_SLICE,
}
_NESTED_REPO_PATCH_REVIEW_FLAGS = {
    "repo_patch_review_only": True,
    "final_parameters_unchanged": True,
    "authority_invoked": False,
    "authority_credentials_forwarded": False,
}
_CREDENTIAL_FIELD_FRAGMENTS = (
    "access_token",
    "api_key",
    "authorization_header",
    "bearer_token",
    "cookie",
    "credential",
    "kubeconfig",
    "password",
    "private_key",
    "refresh_token",
    "secret",
)
_PROHIBITED_REVIEW_FIELDS = frozenset(
    {
        "authorization_proof",
        "execution_permit",
        "authority_response",
        "authority_receipt",
    }
)


class OrchestratorService:
    def __init__(
        self,
        adapter: GooseAdapter | HermesAdapter | None = None,
        hsai_admission_adapter: HsaiAdmissionAdapter | None = None,
        config: RuntimeConfig | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        repo_patch_authority_client: RepoPatchAuthorityClient | None = None,
    ):
        self.config = config or RuntimeConfig.from_env()
        self.adapter = adapter or self._build_adapter()
        self.hsai_admission_adapter = hsai_admission_adapter or build_hsai_admission_adapter()
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.attempt_store = ExecutionAttemptStore(self.config.state_directory)
        # Resolve file-backed authority material only if an approved repo-patch
        # reaches dispatch. This keeps all non-repo action behavior unchanged.
        self.repo_patch_authority_client = repo_patch_authority_client

    def _build_adapter(self) -> GooseAdapter | HermesAdapter:
        mode = (self.config.orchestration_mode or "native_hermes").lower()
        if mode == "goose":
            resolved = resolve_integrations_config(self.config)
            return GooseCliAdapter(
                command=resolved.goose_command,
                timeout_seconds=self.config.goose_command_timeout_seconds,
            )
        if mode == "hermes":
            resolved = resolve_integrations_config(self.config)
            return HermesCliAdapter(
                command=resolved.hermes_command,
                timeout_seconds=self.config.hermes_command_timeout_seconds,
            )
        if mode in {"native", "native_hermes"}:
            return NativeHermesAdapter(config=self.config)
        if mode == "native_goose":
            return NativeGooseAdapter(config=self.config)
        # auto: prefer Hermes, then Goose, then fall back to the modern native
        # Hermes adapter so offline/dev setups still work.
        readiness = build_readiness(self.config)
        if readiness.hermes.ready:
            resolved = resolve_integrations_config(self.config)
            log_runtime_event("orchestration_adapter_selected", adapter="hermes", reason="auto_ready")
            return HermesCliAdapter(
                command=resolved.hermes_command,
                timeout_seconds=self.config.hermes_command_timeout_seconds,
            )
        if readiness.goose.ready:
            resolved = resolve_integrations_config(self.config)
            log_runtime_event("orchestration_adapter_selected", adapter="goose", reason="auto_ready")
            return GooseCliAdapter(
                command=resolved.goose_command,
                timeout_seconds=self.config.goose_command_timeout_seconds,
            )
        log_runtime_event(
            "orchestration_adapter_selected",
            adapter="native_hermes",
            reason="auto_fallback",
            hermes_detail=readiness.hermes.detail,
            goose_detail=readiness.goose.detail,
        )
        return NativeHermesAdapter(config=self.config)

    def execute(self, decision: Decision, evaluation: EvaluationResult) -> ExecutionRecord:
        started_at = datetime.now(timezone.utc).isoformat()
        idempotency_key = f"{decision.decision_id}:{decision.execution_plan['action']}"
        replay_guarded = _requires_replay_guard(decision)
        repo_patch_action = repo_patch_requires_hsai(decision)
        repo_patch_review: CliExecutionResult | None = None
        hsai_gate = None
        if repo_patch_action:
            parameter_failure = _repo_patch_parameter_contract_failure(decision)
            if parameter_failure is not None:
                return self._repo_patch_review_rejected(
                    decision,
                    idempotency_key,
                    started_at,
                    CliExecutionResult(
                        status="failed",
                        external_refs={},
                        failure={"reason": parameter_failure},
                        retryable=False,
                    ),
                )
            mesh_allowed = mesh_policy_allows(evaluation)
            if not mesh_allowed or getattr(self.hsai_admission_adapter, "authority_eligible", False) is not True:
                initial_request = build_hsai_admission_request(decision, evaluation)
                initial_gate = evaluate_hsai_gate(initial_request, self.hsai_admission_adapter)
                validate_bridge_gate(
                    initial_gate,
                    expected_decision=decision,
                    expected_evaluation=evaluation,
                )
                if not mesh_allowed:
                    reason = "mesh_policy_blocked"
                elif initial_gate.get("allowed") is not True:
                    reason = "hsai_admission_blocked"
                else:
                    reason = "hsai_adapter_not_authority_eligible: authority-eligible HSAI adapter required"
                return self._repo_patch_admission_rejected(
                    decision,
                    evaluation,
                    idempotency_key,
                    started_at,
                    initial_gate,
                    reason,
                )

        execution_decision = decision
        if not evaluation.passed or evaluation.final_recommendation != "execute":
            log_runtime_event(
                "execution_rejected",
                mode=self.config.orchestration_mode,
                decision_id=decision.decision_id,
                recommendation=evaluation.final_recommendation,
                blocking_reasons=evaluation.blocking_reasons,
            )
            record = ExecutionRecord(
                execution_id=f"exe_{decision.decision_id}",
                decision_id=decision.decision_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                executor=self.config.orchestration_mode,
                status="rejected",
                idempotency_key=idempotency_key,
                applied_action={
                    "system": decision.execution_plan["system"],
                    "action": decision.execution_plan["action"],
                    "parameters": decision.execution_plan["parameters"],
                },
                external_refs={},
                failure={
                    "reason": evaluation.final_recommendation,
                    "blocking_reasons": list(evaluation.blocking_reasons),
                },
            )
            record.validate()
            return record

        result: CliExecutionResult | None = None
        attempts = 0
        retry_window_started_at = self.clock()
        while attempts <= self.config.max_transient_retries:
            attempts += 1
            prior_attempt = self.attempt_store.get(idempotency_key) if replay_guarded else None
            if has_terminal_outcome(prior_attempt):
                result = self._result_from_prior_attempt(prior_attempt or {})
                break
            if dispatched_without_outcome(prior_attempt):
                result = self._unknown_after_dispatch(prior_attempt)
                break
            if repo_patch_action and self.repo_patch_authority_client is None:
                try:
                    self.repo_patch_authority_client = build_repo_patch_authority_client(self.config)
                except (OSError, TypeError, ValueError) as exc:
                    result = CliExecutionResult(
                        status="failed",
                        external_refs=(dict(repo_patch_review.external_refs) if repo_patch_review is not None else {}),
                        failure={
                            "reason": "repo_patch_authority_configuration_rejected",
                            "detail": str(exc),
                        },
                        retryable=False,
                    )
                    break
            if repo_patch_action:
                assert self.repo_patch_authority_client is not None
                try:
                    preflight_receipt = self.repo_patch_authority_client.preflight(
                        decision,
                        evaluation,
                        idempotency_key,
                    )
                except RepoPatchAuthorityError as exc:
                    result = CliExecutionResult(
                        status="failed",
                        external_refs={},
                        failure={
                            "reason": "repo_patch_authority_preflight_rejected",
                            "detail": str(exc),
                        },
                        retryable=False,
                    )
                    break
                try:
                    final_hsai_request = build_hsai_admission_request_v2(
                        decision,
                        evaluation,
                        preflight_receipt,
                    )
                except (TypeError, ValueError):
                    fallback_request = build_hsai_admission_request(decision, evaluation)
                    fallback_gate = evaluate_hsai_gate(fallback_request, self.hsai_admission_adapter)
                    return self._repo_patch_admission_rejected(
                        decision,
                        evaluation,
                        idempotency_key,
                        started_at,
                        fallback_gate,
                        "hsai_pre_execution_request_invalid",
                    )
                final_hsai_gate = evaluate_hsai_gate(final_hsai_request, self.hsai_admission_adapter)
                validate_bridge_gate(
                    final_hsai_gate,
                    expected_decision=decision,
                    expected_evaluation=evaluation,
                )
                hsai_gate = final_hsai_gate
                if final_hsai_gate.get("allowed") is not True or final_hsai_gate.get("authority_eligible") is not True:
                    return self._repo_patch_admission_rejected(
                        decision,
                        evaluation,
                        idempotency_key,
                        started_at,
                        final_hsai_gate,
                        "hsai_admission_blocked",
                    )
                repo_patch_review = self.adapter.execute_decision(decision, idempotency_key)
                if repo_patch_review.status != "succeeded":
                    return self._repo_patch_review_rejected(
                        decision,
                        idempotency_key,
                        started_at,
                        repo_patch_review,
                    )
                review_failure = _repo_patch_review_contract_failure(repo_patch_review)
                if review_failure is not None:
                    return self._repo_patch_review_rejected(
                        decision,
                        idempotency_key,
                        started_at,
                        CliExecutionResult(
                            status="failed",
                            external_refs={},
                            failure={"reason": review_failure},
                            retryable=False,
                        ),
                    )
                if replay_guarded:
                    self.attempt_store.begin(idempotency_key, decision.decision_id, decision.execution_plan)
                    self.attempt_store.mark_dispatched(idempotency_key)
                try:
                    authority_response = self.repo_patch_authority_client.execute(
                        decision,
                        evaluation,
                        hsai_gate,
                        idempotency_key,
                        preflight_receipt,
                    )
                except RepoPatchAuthorityError:
                    result = self._unknown_after_dispatch(
                        self.attempt_store.get(idempotency_key) if replay_guarded else None
                    )
                    break
                execution_result = authority_response.get("execution_result")
                authority_contract_failure = _authority_response_contract_failure(
                    authority_response,
                    expected_authority_key_id=self.config.repo_patch_authority_key_id,
                )
                if authority_contract_failure is not None or not isinstance(execution_result, dict):
                    result = self._unknown_after_dispatch(
                        self.attempt_store.get(idempotency_key) if replay_guarded else None
                    )
                    break
                authority_refs = execution_result.get("external_refs")
                candidate = CliExecutionResult(
                    status=str(execution_result.get("status") or "failed"),
                    external_refs={
                        **dict(repo_patch_review.external_refs),
                        **(dict(authority_refs) if isinstance(authority_refs, dict) else {}),
                        "repo_patch_authority": {
                            "state_slice": REPO_PATCH_AUTHORITY_ORCHESTRATION_STATE_SLICE,
                            "schema_version": authority_response.get("schema_version"),
                            "status": authority_response.get("status"),
                            "receipt": authority_response.get("receipt"),
                            "rejection": authority_response.get("rejection"),
                            "authorization_proof": authority_response.get("authorization_proof"),
                        },
                    },
                    failure=(
                        dict(execution_result["failure"])
                        if isinstance(execution_result.get("failure"), dict)
                        else None
                    ),
                    retryable=False,
                )
            else:
                if replay_guarded:
                    self.attempt_store.begin(idempotency_key, decision.decision_id, decision.execution_plan)
                    self.attempt_store.mark_dispatched(idempotency_key)
                candidate = self.adapter.execute_decision(execution_decision, idempotency_key)
            result = candidate
            if replay_guarded:
                self.attempt_store.complete(
                    idempotency_key,
                    status=candidate.status,
                    external_refs=candidate.external_refs,
                    failure=candidate.failure,
                )
            if candidate.status == "succeeded":
                break
            if not candidate.retryable:
                break
            if attempts > self.config.max_transient_retries:
                break
            retry_after_seconds = self._retry_delay_seconds(attempts, candidate.failure)
            if self.clock() - retry_window_started_at + retry_after_seconds > self.config.max_retry_window_seconds:
                break
            if retry_after_seconds > 0:
                log_runtime_event(
                    "execution_retry_scheduled",
                    mode=self.config.orchestration_mode,
                    decision_id=decision.decision_id,
                    attempts=attempts,
                    retry_after_seconds=retry_after_seconds,
                    failure_reason=(candidate.failure or {}).get("reason"),
                )
                self.sleeper(retry_after_seconds)

        if result is None:
            raise RuntimeError("execution did not produce a result")

        external_refs = dict(result.external_refs)
        failure = result.failure
        if result.status != "succeeded" and result.retryable:
            external_refs.update(
                self.adapter.open_execution_incident(
                    decision,
                    failure["reason"] if failure else "transient_execution_failure",
                )
            )
            failure = {
                **(failure or {"reason": "transient_execution_failure"}),
                "human_review_route": "human_review",
                "attempts": attempts,
                "orchestration_mode": self.config.orchestration_mode,
            }
        elif failure:
            failure = {**failure, "attempts": attempts, "orchestration_mode": self.config.orchestration_mode}

        if hsai_gate is not None and not external_refs.get("idempotency_replayed"):
            receipt_digest = executor_receipt_digest(result.status, external_refs, failure)
            proof_packet = build_combined_proof_packet(
                hsai_gate,
                mesh_policy_approved=True,
                action_execution_result={
                    "status": "executed" if result.status == "succeeded" else "failed",
                    "executor": self.config.orchestration_mode,
                    "result_status": result.status,
                    "result_digest": receipt_digest,
                },
                executor_receipt_digest=receipt_digest,
                expected_decision=decision,
                expected_evaluation=evaluation,
            )
            external_refs.update(_hsai_external_refs(hsai_gate, proof_packet))
        if (
            replay_guarded
            and not external_refs.get("idempotency_replayed")
            and external_refs.get("idempotency_guard") != "remote_command_dispatched_without_outcome"
        ):
            self.attempt_store.complete(
                idempotency_key,
                status=result.status,
                external_refs=external_refs,
                failure=failure,
            )

        record = ExecutionRecord(
            execution_id=f"exe_{decision.decision_id}",
            decision_id=decision.decision_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            executor=self.config.orchestration_mode,
            status=result.status,
            idempotency_key=idempotency_key,
            applied_action={
                "system": decision.execution_plan["system"],
                "action": decision.execution_plan["action"],
                "parameters": decision.execution_plan["parameters"],
            },
            external_refs=external_refs,
            failure=failure,
        )
        record.validate()
        log_runtime_event(
            "execution_completed",
            mode=self.config.orchestration_mode,
            decision_id=decision.decision_id,
            status=record.status,
            attempts=(failure or {}).get("attempts", attempts),
        )
        return record

    def _repo_patch_review_rejected(
        self,
        decision: Decision,
        idempotency_key: str,
        started_at: str,
        review: CliExecutionResult,
    ) -> ExecutionRecord:
        failure = dict(review.failure or {"reason": "repo_patch_review_rejected"})
        failure["orchestration_mode"] = self.config.orchestration_mode
        record = ExecutionRecord(
            execution_id=f"exe_{decision.decision_id}",
            decision_id=decision.decision_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            executor=self.config.orchestration_mode,
            status="rejected",
            idempotency_key=idempotency_key,
            applied_action={
                "system": decision.execution_plan["system"],
                "action": decision.execution_plan["action"],
                "parameters": decision.execution_plan["parameters"],
            },
            external_refs=dict(review.external_refs),
            failure=failure,
        )
        record.validate()
        return record

    def _repo_patch_admission_rejected(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        idempotency_key: str,
        started_at: str,
        gate: dict[str, Any],
        reason: str,
    ) -> ExecutionRecord:
        mesh_allowed = mesh_policy_allows(evaluation)
        proof_packet = build_combined_proof_packet(
            gate,
            mesh_policy_approved=mesh_allowed,
            action_execution_result={
                "status": "blocked",
                "executor": self.config.orchestration_mode,
                "reason": reason,
                "hsai_reason_codes": list(gate.get("reason_codes") or []),
                "mesh_blocking_reasons": list(evaluation.blocking_reasons),
            },
            executor_receipt_digest=None,
            expected_decision=decision,
            expected_evaluation=evaluation,
        )
        failure = {
            "reason": reason,
            "blocking_reasons": list(evaluation.blocking_reasons) + list(gate.get("reason_codes") or []),
            "hsai_decision": gate["decision"]["decision"],
            "mesh_policy_approved": mesh_allowed,
        }
        record = ExecutionRecord(
            execution_id=f"exe_{decision.decision_id}",
            decision_id=decision.decision_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            executor=self.config.orchestration_mode,
            status="rejected",
            idempotency_key=idempotency_key,
            applied_action={
                "system": decision.execution_plan["system"],
                "action": decision.execution_plan["action"],
                "parameters": decision.execution_plan["parameters"],
            },
            external_refs=_hsai_external_refs(gate, proof_packet),
            failure=failure,
        )
        record.validate()
        return record

    @staticmethod
    def _result_from_prior_attempt(record: dict[str, Any]) -> CliExecutionResult:
        refs = dict(record.get("external_refs") or {})
        refs["idempotency_replayed"] = True
        return CliExecutionResult(
            status=str(record.get("status", "failed")),
            external_refs=refs,
            failure=record.get("failure") if isinstance(record.get("failure"), dict) else None,
            retryable=False,
        )

    @staticmethod
    def _unknown_after_dispatch(record: dict[str, Any] | None) -> CliExecutionResult:
        return CliExecutionResult(
            status="failed",
            external_refs={
                "idempotency_guard": "remote_command_dispatched_without_outcome",
                "idempotency_key": (record or {}).get("idempotency_key"),
            },
            failure={
                "reason": "outcome_unknown_after_dispatch",
                "detail": "remote command may already have executed; refusing to retry side-effecting action",
            },
            retryable=False,
        )

    def _retry_delay_seconds(self, attempts: int, failure: dict[str, Any] | None) -> float:
        if failure is not None and failure.get("retry_after_seconds") is not None:
            return float(failure["retry_after_seconds"])
        # Use bounded exponential backoff for transient failures that do not provide
        # an explicit retry hint so unattended runs do not hot-loop integrations.
        return float(min(2 ** max(attempts - 1, 0), 8))


def _requires_replay_guard(decision: Decision) -> bool:
    return bool(
        repo_patch_requires_hsai(decision)
        or (
            decision.execution_plan.get("system") == "systemd_service"
            and decision.execution_plan.get("action") == "restart_systemd_service"
        )
    )


def _hsai_external_refs(gate: dict[str, Any], proof_packet: dict[str, Any]) -> dict[str, object]:
    validate_bridge_gate(gate)
    validate_combined_proof_packet(gate, proof_packet)
    return {
        "hsai_admission": {
            "schema_version": "mesh.hsai_admission_bridge.v1",
            "request_digest": gate["request_digest"],
            "decision_digest": gate["decision_digest"],
            "candidate_digest": gate["candidate_digest"],
            "decision": gate["decision"]["decision"],
            "reason_codes": list(gate["reason_codes"]),
        },
        "combined_proof_packet": proof_packet,
    }


def _repo_patch_parameter_contract_failure(decision: Decision) -> str | None:
    parameters = decision.execution_plan.get("parameters")
    if not isinstance(parameters, dict):
        return "repo_patch_parameters_rejected"
    if "_mesh_hsai_admission_context" in parameters:
        return "repo_patch_pre_attached_authority_context_rejected"
    if _contains_credential_field(parameters):
        return "repo_patch_parameter_credentials_rejected"
    return None


def _repo_patch_review_contract_failure(review: CliExecutionResult) -> str | None:
    if review.status != "succeeded" or review.retryable or review.failure is not None:
        return "repo_patch_review_contract_rejected"
    refs = review.external_refs
    if any(refs.get(field) != expected for field, expected in _REPO_PATCH_REVIEW_FLAGS.items()):
        return "repo_patch_review_contract_rejected"
    review_keys = [key for key in ("goose_review", "hermes_review") if key in refs]
    if len(review_keys) != 1:
        return "repo_patch_review_contract_rejected"
    allowed_top_level = {
        *_REPO_PATCH_REVIEW_FLAGS,
        review_keys[0],
        "repo_patch_model_parameter_changes_ignored",
    }
    if not set(refs).issubset(allowed_top_level):
        return "repo_patch_review_contract_rejected"
    if "repo_patch_model_parameter_changes_ignored" in refs:
        if refs["repo_patch_model_parameter_changes_ignored"] is not True:
            return "repo_patch_review_contract_rejected"
    nested = refs.get(review_keys[0])
    if not isinstance(nested, dict):
        return "repo_patch_review_contract_rejected"
    if any(nested.get(field) != expected for field, expected in _NESTED_REPO_PATCH_REVIEW_FLAGS.items()):
        return "repo_patch_review_contract_rejected"
    if nested.get("approved") is not True:
        return "repo_patch_review_contract_rejected"
    if nested.get("next_action") != "authority_service_review_required":
        return "repo_patch_review_contract_rejected"
    if not isinstance(nested.get("mode"), str) or not str(nested["mode"]).strip():
        return "repo_patch_review_contract_rejected"
    if not isinstance(nested.get("summary"), str) or not str(nested["summary"]).strip():
        return "repo_patch_review_contract_rejected"
    risk_flags = nested.get("risk_flags")
    if not isinstance(risk_flags, list) or any(not isinstance(flag, str) for flag in risk_flags):
        return "repo_patch_review_contract_rejected"
    if "model_parameter_changes_ignored" in nested:
        if nested["model_parameter_changes_ignored"] is not True:
            return "repo_patch_review_contract_rejected"
    if _contains_prohibited_review_field(refs):
        return "repo_patch_review_authority_material_rejected"
    if _contains_credential_field(refs):
        return "repo_patch_review_credentials_rejected"
    return None


def _authority_response_contract_failure(
    response: dict[str, Any],
    *,
    expected_authority_key_id: str,
) -> str | None:
    if response.get("schema_version") != "mesh.repo_patch_authority_response.v1":
        return "repo_patch_authority_response_contract_rejected"
    status = response.get("status")
    if status not in {"completed", "rejected"}:
        return "repo_patch_authority_response_contract_rejected"
    execution_result = response.get("execution_result")
    receipt = response.get("receipt")
    proof = response.get("authorization_proof")
    if not isinstance(execution_result, dict) or not isinstance(receipt, dict) or not isinstance(proof, dict):
        return "repo_patch_authority_response_contract_rejected"
    if execution_result.get("status") not in {"succeeded", "failed", "rejected"}:
        return "repo_patch_authority_response_contract_rejected"
    if not isinstance(execution_result.get("external_refs"), dict):
        return "repo_patch_authority_response_contract_rejected"
    if execution_result.get("failure") is not None and not isinstance(execution_result.get("failure"), dict):
        return "repo_patch_authority_response_contract_rejected"
    if execution_result.get("retryable") is not False:
        return "repo_patch_authority_response_contract_rejected"
    rejection = response.get("rejection")
    if (status == "completed" and rejection is not None) or (
        status == "rejected" and not isinstance(rejection, dict)
    ):
        return "repo_patch_authority_response_contract_rejected"
    if (
        proof.get("signing_profile") != "mesh-repo-patch-authority-response-ed25519-v1"
        or proof.get("algorithm") != "ed25519"
        or proof.get("key_id") != expected_authority_key_id
        or proof.get("status") != "verified"
        or proof.get("verifier") != "orbital_mesh_ed25519_v1"
    ):
        return "repo_patch_authority_response_contract_rejected"
    if _contains_credential_field({"execution_result": execution_result, "receipt": receipt}):
        return "repo_patch_authority_response_credentials_rejected"
    return None


def _contains_prohibited_review_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _PROHIBITED_REVIEW_FIELDS
            or _contains_prohibited_review_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_prohibited_review_field(item) for item in value)
    return False


def _contains_credential_field(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in {
                "authority_credentials_forwarded",
                "repo_patch_authority_credentials_forwarded",
            } and item is False:
                continue
            if any(fragment in normalized_key for fragment in _CREDENTIAL_FIELD_FRAGMENTS):
                return True
            if _contains_credential_field(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_credential_field(item) for item in value)
    return False
