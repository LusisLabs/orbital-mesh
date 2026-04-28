"""Goose integration boundary with native and CLI-backed modes."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from services.actuators.load_balancer import LoadBalancerAdapter
from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter, KubernetesAdapter
from services.actuators.repo_patch import RepoPatchAdapter
from services.orchestrator.adapters_common import CliExecutionResult
from shared.mesh_runtime import Decision, RuntimeConfig


MESH_ROOT = Path(__file__).resolve().parents[2]

GooseExecutionResult = CliExecutionResult


class GooseAdapter:
    def execute_decision(self, decision: Decision, idempotency_key: str) -> GooseExecutionResult:
        raise NotImplementedError

    def open_execution_incident(self, decision: Decision, failure_reason: str) -> dict[str, str]:
        raise NotImplementedError


class NativeGooseAdapter(GooseAdapter):
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        from services.actuators.argocd import ArgoCDAdapter
        from services.actuators.systemd_ssh import SystemdSshAdapter
        self.config = config
        self.feature_flags = FeatureFlagAdapter()
        self.incidents = IncidentAdapter()
        self.kubernetes = KubernetesAdapter(config=config)
        self.audit_logs = AuditLogAdapter()
        self.repo_patch = RepoPatchAdapter()
        # Bare-metal SSH adapter — constructed unconditionally because it's
        # cheap and mock-by-default. The config's ssh_execution_enabled flag
        # gates real side effects; without it the adapter returns mock
        # results. This keeps test environments hermetic.
        self.systemd_ssh = SystemdSshAdapter(config=config)
        self.load_balancer = LoadBalancerAdapter(config=config)
        cfg = config or RuntimeConfig()
        self.argocd = ArgoCDAdapter(
            url=cfg.argocd_url,
            token=cfg.argocd_token,
            ca_bundle=cfg.argocd_ca_bundle,
            timeout_seconds=cfg.argocd_timeout_seconds,
        )

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
        external_refs["goose_review"] = {
            "mode": "native",
            "approved": True,
            "summary": "native bounded execution path approved locally",
            "risk_flags": [],
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
        elif execution_plan["system"] == "systemd_service":
            # Bare-metal actuation via SSH. The adapter carries its own
            # four-part safety envelope (enable flag + host allowlist +
            # service allowlist + command allowlist); this switch only
            # routes allowed systemd verbs to their methods. Unknown
            # actions fail loudly rather than get silently dropped.
            action = execution_plan["action"]
            if action == "restart_systemd_service":
                result = self._restart_systemd_with_preflight(execution_plan["parameters"])
            elif action == "start_systemd_service":
                result = self.systemd_ssh.start_service(execution_plan["parameters"])
            elif action == "stop_systemd_service":
                result = self.systemd_ssh.stop_service(execution_plan["parameters"])
            else:
                result = {
                    "status": "failed",
                    "failure": {"reason": "unknown_systemd_action", "detail": str(action)},
                    "external_refs": {},
                }
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
        elif execution_plan["system"] == "repo_patch_service":
            result = self.repo_patch.execute_patch(execution_plan["parameters"], idempotency_key)
        else:
            result = {"status": "succeeded", "external_refs": {}}

        external_refs.update(result.get("external_refs", {}))
        return GooseExecutionResult(
            status=result["status"],
            external_refs=external_refs,
            failure=result.get("failure"),
            retryable=result.get("retryable", False),
        )

    def _restart_systemd_with_preflight(self, parameters: dict) -> dict:
        fleet_failure = _fleet_preflight_failure(parameters)
        if fleet_failure is not None:
            return fleet_failure

        lb_target_id = parameters.get("lb_target_id")
        lb_refs: dict[str, object] = {}
        if lb_target_id:
            drain = self.load_balancer.drain_target(parameters)
            if drain["status"] != "succeeded":
                return drain
            lb_refs["lb_drain"] = drain.get("external_refs", {})
            status = self.load_balancer.target_status(parameters)
            if status["status"] != "succeeded":
                return status
            lb_refs["lb_status_before_restart"] = status.get("external_refs", {})

        restart = self.systemd_ssh.restart_service(parameters)
        restart.setdefault("external_refs", {}).update(lb_refs)
        if restart["status"] != "succeeded":
            return restart

        if lb_target_id:
            restore = self.load_balancer.restore_target(parameters)
            restart["external_refs"]["lb_restore"] = restore.get("external_refs", {})
            if restore["status"] != "succeeded":
                return {
                    "status": "failed",
                    "failure": {
                        "reason": "load_balancer_restore_failed",
                        "detail": (restore.get("failure") or {}).get("detail", "restore failed"),
                    },
                    "external_refs": restart["external_refs"],
                }
        return restart

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


def _fleet_preflight_failure(parameters: dict) -> dict | None:
    min_healthy = parameters.get("fleet_min_healthy")
    healthy_count = parameters.get("fleet_healthy_count")
    if min_healthy is None or healthy_count is None:
        return None
    if int(healthy_count) < int(min_healthy):
        return {
            "status": "failed",
            "failure": {
                "reason": "fleet_capacity_below_threshold",
                "detail": f"healthy_count={healthy_count} < fleet_min_healthy={min_healthy}",
            },
            "external_refs": {
                "fleet_id": parameters.get("fleet_id"),
                "healthy_count": healthy_count,
                "fleet_min_healthy": min_healthy,
            },
        }
    return None


class GooseCliAdapter(GooseAdapter):
    def __init__(self, command: str | None = None, timeout_seconds: int = 30):
        self.command = command
        self.timeout_seconds = timeout_seconds

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
                input=json.dumps(payload, separators=(",", ":")),
                capture_output=True,
                text=True,
                cwd=MESH_ROOT,
                check=False,
                timeout=self.timeout_seconds,
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
