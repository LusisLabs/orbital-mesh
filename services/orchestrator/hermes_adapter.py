"""Hermes integration boundary with native and CLI-backed modes."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from services.actuators.repo_patch import RepoPatchAdapter
from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter, KubernetesAdapter
from services.orchestrator.adapters_common import CliExecutionResult
from shared.mesh_runtime import Decision, RuntimeConfig


MESH_ROOT = Path(__file__).resolve().parents[2]

HermesExecutionResult = CliExecutionResult


class HermesAdapter:
    def execute_decision(self, decision: Decision, idempotency_key: str) -> HermesExecutionResult:
        raise NotImplementedError

    def open_execution_incident(self, decision: Decision, failure_reason: str) -> dict[str, str]:
        raise NotImplementedError


class NativeHermesAdapter(HermesAdapter):
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.feature_flags = FeatureFlagAdapter()
        self.incidents = IncidentAdapter()
        self.kubernetes = KubernetesAdapter(config=self.config)
        self.audit_logs = AuditLogAdapter()
        self.repo_patch = RepoPatchAdapter()

    def execute_decision(self, decision: Decision, idempotency_key: str) -> HermesExecutionResult:
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
            if execution_plan["action"] == "rollback_deployment":
                result = self.kubernetes.rollback_deployment(execution_plan["parameters"])
            else:
                result = self.kubernetes.restart_deployment(execution_plan["parameters"])
        elif execution_plan["system"] == "repo_patch_service":
            result = self.repo_patch.execute_patch(execution_plan["parameters"], idempotency_key)
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
        return result.get("external_refs", {})


class HermesCliAdapter(HermesAdapter):
    def __init__(self, command: str | None = None, timeout_seconds: int = 30):
        self.command = command
        self.timeout_seconds = timeout_seconds

    def execute_decision(self, decision: Decision, idempotency_key: str) -> HermesExecutionResult:
        result = self._invoke(
            {
                "mode": "execute",
                "decision": decision.to_dict(),
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
        return result.get("external_refs", {})

    def _invoke(self, payload: dict) -> dict:
        try:
            completed = subprocess.run(
                self._resolve_command(),
                input=json.dumps(payload, separators=(",", ":")),
                capture_output=True,
                text=True,
                cwd=MESH_ROOT,
                check=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"error": f"hermes subprocess failed: {exc}"}

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or "hermes subprocess returned a non-zero exit code"
            return {"error": stderr}

        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return {"error": f"hermes subprocess returned invalid JSON: {exc}"}

    def _resolve_command(self) -> list[str]:
        if not self.command:
            raise OSError("hermes command is not configured")
        return shlex.split(self.command)
