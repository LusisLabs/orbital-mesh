"""Goose integration boundary with native and CLI-backed modes."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter
from shared.mesh_runtime import Decision


MESH_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class GooseExecutionResult:
    status: str
    external_refs: dict[str, str]
    failure: dict | None = None
    retryable: bool = False


class GooseAdapter:
    def execute_decision(self, decision: Decision, idempotency_key: str) -> GooseExecutionResult:
        raise NotImplementedError

    def open_execution_incident(self, decision: Decision, failure_reason: str) -> dict[str, str]:
        raise NotImplementedError


class NativeGooseAdapter(GooseAdapter):
    def __init__(self) -> None:
        self.feature_flags = FeatureFlagAdapter()
        self.incidents = IncidentAdapter()
        self.audit_logs = AuditLogAdapter()

    def execute_decision(self, decision: Decision, idempotency_key: str) -> GooseExecutionResult:
        audit_result = self.audit_logs.write_record(decision, idempotency_key)
        if audit_result["status"] != "succeeded":
            return GooseExecutionResult(
                status="failed",
                external_refs={},
                failure={"reason": "audit_logging_failed"},
            )

        execution_plan = decision.execution_plan
        external_refs = {"audit_log_id": audit_result["audit_log_id"]}
        if execution_plan["system"] == "feature_flag_service":
            result = self.feature_flags.set_rollout(execution_plan["parameters"])
        elif execution_plan["system"] == "incident_service":
            result = self.incidents.open_incident(execution_plan["parameters"])
        else:
            result = {"status": "succeeded", "external_refs": {}}

        external_refs.update(result.get("external_refs", {}))
        return GooseExecutionResult(
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


class GooseCliAdapter(GooseAdapter):
    def __init__(self, command: str | None = None):
        self.command = command

    def execute_decision(self, decision: Decision, idempotency_key: str) -> GooseExecutionResult:
        result = self._invoke(
            {
                "mode": "execute",
                "decision": decision.to_dict(),
                "idempotency_key": idempotency_key,
            }
        )
        if result.get("error"):
            return GooseExecutionResult(
                status="failed",
                external_refs={},
                failure={"reason": result["error"]},
            )
        return GooseExecutionResult(
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
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                cwd=MESH_ROOT,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"error": f"goose subprocess failed: {exc}"}

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or "goose subprocess returned a non-zero exit code"
            return {"error": stderr}

        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return {"error": f"goose subprocess returned invalid JSON: {exc}"}

    def _resolve_command(self) -> list[str]:
        if not self.command:
            raise OSError("goose command is not configured")
        return shlex.split(self.command)
