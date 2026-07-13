"""Hermes integration boundary with native and CLI-backed modes."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, TypeAlias, cast

from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter, KubernetesAdapter
from services.orchestrator.adapters_common import CliExecutionResult
from shared.mesh_runtime import Decision, RuntimeConfig
from shared.mesh_runtime.goose_credentials import model_subprocess_env


MESH_ROOT = Path(__file__).resolve().parents[2]
HSAI_EXECUTION_CONTEXT_KEY = "_mesh_hsai_admission_context"
REPO_PATCH_REVIEW_ONLY_STATE_SLICE = "mesh.repo_patch_review_only_boundary.v1"

HermesExecutionResult: TypeAlias = CliExecutionResult


class HermesAdapter:
    def execute_decision(self, decision: Decision, idempotency_key: str) -> HermesExecutionResult:
        raise NotImplementedError

    def open_execution_incident(self, decision: Decision, failure_reason: str) -> dict[str, str]:
        raise NotImplementedError

    def explain_blockers(
        self,
        decision: Decision,
        evaluation: dict[str, Any],
        blocking_reasons: list[str],
    ) -> dict[str, object]:
        raise NotImplementedError

    def chat_blockers(
        self,
        decision: Decision,
        evaluation: dict[str, Any],
        blocking_reasons: list[str],
        history: list[dict[str, str]],
        user_message: str,
    ) -> dict[str, object]:
        raise NotImplementedError


class NativeHermesAdapter(HermesAdapter):
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        from services.actuators.argocd import ArgoCDAdapter
        self.config = config or RuntimeConfig.from_env()
        self.feature_flags = FeatureFlagAdapter()
        self.incidents = IncidentAdapter()
        self.kubernetes = KubernetesAdapter(config=self.config)
        self.audit_logs = AuditLogAdapter()
        self.argocd = ArgoCDAdapter(
            url=self.config.argocd_url,
            token=self.config.argocd_token,
            ca_bundle=self.config.argocd_ca_bundle,
            timeout_seconds=self.config.argocd_timeout_seconds,
        )

    def execute_decision(self, decision: Decision, idempotency_key: str) -> HermesExecutionResult:
        if decision.execution_plan["system"] == "repo_patch_service":
            return HermesExecutionResult(
                status="succeeded",
                external_refs=_repo_patch_review_refs(
                    {
                        "mode": "native",
                        "approved": True,
                        "summary": "native repo-patch review completed without actuation",
                        "risk_flags": [],
                        "next_action": "authority_service_review_required",
                    }
                ),
            )

        audit_result = self.audit_logs.write_record(decision, idempotency_key)
        if audit_result["status"] != "succeeded":
            return HermesExecutionResult(
                status="failed",
                external_refs={},
                failure={"reason": "audit_logging_failed"},
            )

        execution_plan = decision.execution_plan
        external_refs = {"audit_log_id": audit_result["audit_log_id"]}
        external_refs["hermes_review"] = {
            "mode": "native",
            "approved": True,
            "summary": "native bounded execution path approved locally",
            "risk_flags": [],
            "next_action": "proceed",
        }
        if execution_plan["system"] == "feature_flag_service":
            result = self.feature_flags.set_rollout(execution_plan["parameters"])
        elif execution_plan["system"] == "incident_service":
            result = self.incidents.open_incident(execution_plan["parameters"])
        elif execution_plan["system"] == "kubernetes_service":
            action = execution_plan["action"]
            if action == "rollback_deployment":
                result = self.kubernetes.rollback_deployment(execution_plan["parameters"])
            elif action == "restart_pod":
                result = self.kubernetes.restart_pod(execution_plan["parameters"])
            elif action == "scale_deployment":
                result = self.kubernetes.scale_deployment(execution_plan["parameters"])
            elif action == "cordon_node":
                result = self.kubernetes.cordon_node(execution_plan["parameters"])
            elif action == "drain_node":
                result = self.kubernetes.drain_node(execution_plan["parameters"])
            else:
                result = self.kubernetes.restart_deployment(execution_plan["parameters"])
        elif execution_plan["system"] == "argocd_service":
            action = execution_plan["action"]
            if action == "sync_application":
                result = self.argocd.sync_application(execution_plan["parameters"])
            elif action == "rollback_application":
                result = self.argocd.rollback_application(execution_plan["parameters"])
            else:
                result = {"status": "failed",
                          "failure": {"reason": "unknown_argocd_action", "detail": action},
                          "external_refs": {}}
        else:
            result = {"status": "succeeded", "external_refs": {}}

        external_refs.update(result.get("external_refs", {}))
        return HermesExecutionResult(
            status=result["status"],
            external_refs=external_refs,
            failure=result.get("failure"),
            retryable=result.get("retryable", False),
        )

    def open_execution_incident(self, decision: Decision, failure_reason: str) -> dict[str, str]:
        result = self.incidents.open_incident(
            {
                "decision_id": decision.decision_id,
                "flag_key": decision.execution_plan["parameters"].get("flag_key"),
                "severity": "high",
                "reason": failure_reason,
            }
        )
        return cast(dict[str, str], result.get("external_refs", {}))

    def explain_blockers(
        self,
        decision: Decision,
        evaluation: dict[str, Any],
        blocking_reasons: list[str],
    ) -> dict[str, object]:
        recommendation = str(evaluation.get("final_recommendation", "human_review"))
        reasons = [reason for reason in blocking_reasons if isinstance(reason, str) and reason.strip()]
        summary = (
            f"Hermes local summary: decision {decision.decision_type} is held at "
            f"{recommendation} because {', '.join(reasons[:3]) or 'evaluation did not pass'}."
        )
        return {
            "mode": "native",
            "approved": False,
            "summary": summary,
            "assistant_reply": summary,
            "risk_flags": reasons[:5],
            "next_action": "operator_override_or_fix_blockers",
            "recommendation": recommendation,
            "operator_actions": ["fix_blockers_or_override"],
            "proposed_command": None,
            "proposed_payload": None,
        }

    def chat_blockers(
        self,
        decision: Decision,
        evaluation: dict[str, Any],
        blocking_reasons: list[str],
        history: list[dict[str, str]],
        user_message: str,
    ) -> dict[str, object]:
        recommendation = str(evaluation.get("final_recommendation", "human_review"))
        reasons = [reason for reason in blocking_reasons if isinstance(reason, str) and reason.strip()]
        reply = (
            f"Hermes local follow-up: {user_message.strip()} "
            f"The run remains at {recommendation} because {', '.join(reasons[:3]) or 'evaluation did not pass'}."
        ).strip()
        return {
            "mode": "native",
            "approved": False,
            "summary": reply,
            "assistant_reply": reply,
            "risk_flags": reasons[:5],
            "next_action": "operator_override_or_fix_blockers",
            "recommendation": recommendation,
            "operator_actions": ["fix_blockers_or_override"],
            "proposed_command": None,
            "proposed_payload": None,
        }


class HermesCliAdapter(HermesAdapter):
    def __init__(self, command: str | None = None, timeout_seconds: int = 30):
        self.command = command
        self.timeout_seconds = timeout_seconds

    def execute_decision(self, decision: Decision, idempotency_key: str) -> HermesExecutionResult:
        result = self._invoke(
            {
                "mode": "execute",
                "decision": _review_only_decision_payload(decision),
                "idempotency_key": idempotency_key,
            }
        )
        if result.get("error"):
            return HermesExecutionResult(
                status="failed",
                external_refs={},
                failure={"reason": result["error"]},
            )
        return HermesExecutionResult(
            status=result["status"],
            external_refs=result.get("external_refs", {}),
            failure=result.get("failure"),
            retryable=result.get("retryable", False),
        )

    def open_execution_incident(self, decision: Decision, failure_reason: str) -> dict[str, str]:
        result = self._invoke(
            {
                "mode": "incident",
                "decision": decision.to_dict(),
                "failure_reason": failure_reason,
            }
        )
        return cast(dict[str, str], result.get("external_refs", {}))

    def explain_blockers(
        self,
        decision: Decision,
        evaluation: dict[str, Any],
        blocking_reasons: list[str],
    ) -> dict[str, object]:
        result = self._invoke(
            {
                "mode": "explain",
                "decision": decision.to_dict(),
                "evaluation": evaluation,
                "blocking_reasons": blocking_reasons,
            }
        )
        if result.get("error"):
            return {
                "approved": False,
                "summary": str(result["error"]),
                "assistant_reply": str(result["error"]),
                "risk_flags": ["subprocess_error"],
                "next_action": "human_review",
                "recommendation": str(evaluation.get("final_recommendation", "human_review")),
                "operator_actions": ["fix_blockers_or_override"],
                "proposed_command": None,
                "proposed_payload": None,
            }
        return cast(dict[str, object], result)

    def chat_blockers(
        self,
        decision: Decision,
        evaluation: dict[str, Any],
        blocking_reasons: list[str],
        history: list[dict[str, str]],
        user_message: str,
    ) -> dict[str, object]:
        result = self._invoke(
            {
                "mode": "chat_blockers",
                "decision": decision.to_dict(),
                "evaluation": evaluation,
                "blocking_reasons": blocking_reasons,
                "history": history,
                "user_message": user_message,
            }
        )
        if result.get("error"):
            return {
                "approved": False,
                "summary": str(result["error"]),
                "assistant_reply": str(result["error"]),
                "risk_flags": ["subprocess_error"],
                "next_action": "human_review",
                "recommendation": str(evaluation.get("final_recommendation", "human_review")),
                "operator_actions": ["fix_blockers_or_override"],
                "proposed_command": None,
                "proposed_payload": None,
            }
        return cast(dict[str, object], result)

    def _invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                self._resolve_command(),
                input=json.dumps(payload, separators=(",", ":")),
                capture_output=True,
                text=True,
                cwd=MESH_ROOT,
                check=False,
                timeout=self.timeout_seconds,
                env=model_subprocess_env(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"error": f"hermes subprocess failed: {exc}"}

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or "hermes subprocess returned a non-zero exit code"
            return {"error": stderr}

        try:
            return cast(dict[str, Any], json.loads(completed.stdout))
        except json.JSONDecodeError as exc:
            return {"error": f"hermes subprocess returned invalid JSON: {exc}"}

    def _resolve_command(self) -> list[str]:
        if not self.command:
            raise OSError("hermes command is not configured")
        return shlex.split(self.command)


def _review_only_decision_payload(decision: Decision) -> dict[str, Any]:
    payload = cast(dict[str, Any], decision.to_dict())
    execution_plan = payload.get("execution_plan")
    if not isinstance(execution_plan, dict) or execution_plan.get("system") != "repo_patch_service":
        return payload
    parameters = execution_plan.get("parameters")
    if isinstance(parameters, dict):
        parameters.pop(HSAI_EXECUTION_CONTEXT_KEY, None)
    return payload


def _repo_patch_review_refs(review: dict[str, object]) -> dict[str, object]:
    enriched_review = {
        **review,
        "repo_patch_review_only": True,
        "final_parameters_unchanged": True,
        "authority_invoked": False,
        "authority_credentials_forwarded": False,
    }
    return {
        "hermes_review": enriched_review,
        "repo_patch_review_only": True,
        "repo_patch_final_parameters_unchanged": True,
        "repo_patch_authority_invoked": False,
        "repo_patch_authority_credentials_forwarded": False,
        "repo_patch_review_state_slice": REPO_PATCH_REVIEW_ONLY_STATE_SLICE,
    }
