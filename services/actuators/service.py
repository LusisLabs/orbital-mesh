"""Local actuator adapters used by the native orchestration integration."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from shared.mesh_runtime import Decision, RuntimeConfig


class FeatureFlagAdapter:
    def set_rollout(self, parameters: dict) -> dict:
        return {
            "status": "succeeded",
            "external_refs": {"flag_change_id": f"ffchg_{parameters['flag_key']}_{parameters['rollout_pct']}"},
        }


class IncidentAdapter:
    def open_incident(self, parameters: dict) -> dict:
        incident_scope = parameters.get("service") or parameters.get("decision_id") or parameters.get("flag_key") or "unknown"
        return {
            "status": "succeeded",
            "external_refs": {"incident_id": f"inc_{incident_scope}"},
        }


class KubernetesAdapter:
    """Live Kubernetes actuation via kubectl.

    Rollback/restart semantics (for operator and public docs):
    - ``rollback_deployment`` → ``kubectl rollout undo`` (previous Deployment revision only).
    - ``restart_deployment`` → ``kubectl rollout restart``.
    This does not restore arbitrary application state beyond the workload rollout history.
    """

    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig.from_env()

    def rollback_deployment(self, parameters: dict) -> dict:
        deployment_name = parameters["deployment_name"]
        target_revision = parameters.get("target_revision") or "previous"
        if not self.config.kubernetes_live_execution_enabled:
            return {
                "status": "succeeded",
                "external_refs": {
                    "rollout_change_id": f"k8srollback_{deployment_name}_{target_revision}",
                    "rollout_action": "rollback_deployment",
                    "live_execution": False,
                },
            }
        return self._execute_live_action("rollback_deployment", parameters)

    def restart_deployment(self, parameters: dict) -> dict:
        deployment_name = parameters["deployment_name"]
        if not self.config.kubernetes_live_execution_enabled:
            return {
                "status": "succeeded",
                "external_refs": {
                    "rollout_change_id": f"k8srestart_{deployment_name}",
                    "rollout_action": "restart_deployment",
                    "live_execution": False,
                },
            }
        return self._execute_live_action("restart_deployment", parameters)

    def _execute_live_action(self, action: str, parameters: dict) -> dict:
        deployment_name = str(parameters.get("deployment_name") or "").strip()
        namespace = str(parameters.get("namespace") or "default").strip() or "default"
        kube_context = str(parameters.get("kube_context") or "").strip() or None
        cluster_label = str(parameters.get("cluster") or "").strip() or None
        if not deployment_name:
            return self._failure("missing deployment_name", action=action, namespace=namespace, cluster_label=cluster_label)

        command_tokens = shlex.split(self.config.kubectl_command)
        executable = command_tokens[0]
        if shutil.which(executable) is None and not executable.startswith("/"):
            return self._failure(
                f"kubectl command not found: {self.config.kubectl_command}",
                action=action,
                deployment_name=deployment_name,
                namespace=namespace,
                cluster_label=cluster_label,
            )

        base_command = list(command_tokens)
        if kube_context:
            base_command.extend(["--context", kube_context])
            active_context = kube_context
        else:
            context_result = self._run_command(base_command + ["config", "current-context"])
            if context_result.returncode != 0:
                return self._failure(
                    context_result.stderr.strip() or "failed to resolve current kube context",
                    action=action,
                    deployment_name=deployment_name,
                    namespace=namespace,
                    cluster_label=cluster_label,
                )
            active_context = context_result.stdout.strip()

        if self.config.kubernetes_allowed_contexts and active_context not in self.config.kubernetes_allowed_contexts:
            return self._failure(
                f"kube context `{active_context}` is not in the allowed list",
                action=action,
                deployment_name=deployment_name,
                namespace=namespace,
                kube_context=active_context,
                cluster_label=cluster_label,
            )
        if self.config.kubernetes_allowed_namespaces and namespace not in self.config.kubernetes_allowed_namespaces:
            return self._failure(
                f"namespace `{namespace}` is not in the allowed list",
                action=action,
                deployment_name=deployment_name,
                namespace=namespace,
                kube_context=active_context,
                cluster_label=cluster_label,
            )

        before_result = self._deployment_snapshot(base_command, deployment_name, namespace)
        if before_result["error"]:
            return self._failure(
                before_result["error"],
                action=action,
                deployment_name=deployment_name,
                namespace=namespace,
                kube_context=active_context,
                cluster_label=cluster_label,
            )

        executed_commands: list[str] = []
        if action == "restart_deployment":
            action_command = base_command + ["rollout", "restart", f"deployment/{deployment_name}", "-n", namespace]
        else:
            action_command = base_command + ["rollout", "undo", f"deployment/{deployment_name}", "-n", namespace]
            target_revision = str(parameters.get("target_revision") or "").strip()
            if target_revision:
                action_command.extend(["--to-revision", target_revision])
        executed_commands.append(shlex.join(action_command))
        action_result = self._run_command(action_command)
        if action_result.returncode != 0:
            return self._failure(
                action_result.stderr.strip() or action_result.stdout.strip() or f"{action} failed",
                action=action,
                deployment_name=deployment_name,
                namespace=namespace,
                kube_context=active_context,
                cluster_label=cluster_label,
                deployment_before=before_result["snapshot"],
                executed_commands=executed_commands,
            )

        status_command = base_command + [
            "rollout",
            "status",
            f"deployment/{deployment_name}",
            "-n",
            namespace,
            f"--timeout={self.config.kubernetes_rollout_timeout_seconds}s",
        ]
        executed_commands.append(shlex.join(status_command))
        status_result = self._run_command(status_command, timeout_seconds=self.config.kubernetes_rollout_timeout_seconds + 5)

        after_result = self._deployment_snapshot(base_command, deployment_name, namespace)
        external_refs = {
            "rollout_action": action,
            "live_execution": True,
            "kube_context": active_context,
            "cluster_label": cluster_label,
            "namespace": namespace,
            "deployment_name": deployment_name,
            "kubectl_command": self.config.kubectl_command,
            "executed_commands": executed_commands,
            "deployment_before": before_result["snapshot"],
            "deployment_after": after_result["snapshot"],
            "rollout_change_id": self._change_id(action, deployment_name, after_result["snapshot"]),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        if status_result.returncode != 0:
            return {
                "status": "failed",
                "external_refs": external_refs,
                "failure": {
                    "reason": "kubernetes_rollout_incomplete",
                    "detail": status_result.stderr.strip() or status_result.stdout.strip() or "rollout status failed",
                    "human_review_route": "human_review",
                },
                "retryable": False,
            }
        return {"status": "succeeded", "external_refs": external_refs}

    def _deployment_snapshot(self, base_command: list[str], deployment_name: str, namespace: str) -> dict[str, Any]:
        command = base_command + ["get", "deployment", deployment_name, "-n", namespace, "-o", "json"]
        completed = self._run_command(command)
        if completed.returncode != 0:
            return {
                "snapshot": None,
                "error": completed.stderr.strip() or completed.stdout.strip() or "failed to fetch deployment",
            }
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return {"snapshot": None, "error": f"deployment JSON decode failed: {exc}"}
        return {"snapshot": self._summarize_deployment(payload), "error": None}

    def _summarize_deployment(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = payload.get("metadata", {})
        annotations = metadata.get("annotations", {})
        spec = payload.get("spec", {})
        status = payload.get("status", {})
        return {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "generation": metadata.get("generation"),
            "observed_generation": status.get("observedGeneration"),
            "revision": annotations.get("deployment.kubernetes.io/revision"),
            "image": _first_container_image(payload),
            "desired_replicas": spec.get("replicas"),
            "updated_replicas": status.get("updatedReplicas", 0),
            "available_replicas": status.get("availableReplicas", 0),
            "unavailable_replicas": status.get("unavailableReplicas", 0),
        }

    def _run_command(self, command: list[str], timeout_seconds: int = 15) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr=str(exc),
            )

    def _change_id(self, action: str, deployment_name: str, snapshot: dict[str, Any] | None) -> str:
        revision = "unknown"
        if snapshot and snapshot.get("revision"):
            revision = str(snapshot["revision"])
        if action == "rollback_deployment":
            return f"k8srollback_{deployment_name}_{revision}"
        return f"k8srestart_{deployment_name}_{revision}"

    def _failure(self, detail: str, **external_refs: Any) -> dict:
        return {
            "status": "failed",
            "external_refs": {"live_execution": True, **external_refs},
            "failure": {
                "reason": "kubernetes_live_execution_failed",
                "detail": detail,
                "human_review_route": "human_review",
            },
            "retryable": False,
        }


class AuditLogAdapter:
    def write_record(self, decision: Decision, idempotency_key: str) -> dict:
        return {
            "status": "succeeded",
            "audit_log_id": f"audit_{decision.decision_id}",
            "idempotency_key": idempotency_key,
        }


def _first_container_image(payload: dict[str, Any]) -> str | None:
    containers = payload.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    if not containers:
        return None
    return containers[0].get("image")
