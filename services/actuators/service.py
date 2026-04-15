"""Local actuator adapters used by the native orchestration integration."""

from __future__ import annotations

import shlex
import subprocess

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
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()

    def rollback_deployment(self, parameters: dict) -> dict:
        deployment_name = parameters["deployment_name"]
        revision = parameters.get("revision") or "previous"
        if self.config.kubernetes_live_execution_enabled:
            return self._live_rollback(parameters, deployment_name, revision)
        return {
            "status": "succeeded",
            "external_refs": {
                "rollout_change_id": f"k8srollback_{deployment_name}_{revision}",
                "rollout_action": "rollback_deployment",
            },
        }

    def restart_deployment(self, parameters: dict) -> dict:
        deployment_name = parameters["deployment_name"]
        if self.config.kubernetes_live_execution_enabled:
            return self._live_restart(parameters, deployment_name)
        return {
            "status": "succeeded",
            "external_refs": {
                "rollout_change_id": f"k8srestart_{deployment_name}",
                "rollout_action": "restart_deployment",
            },
        }

    def _live_restart(self, parameters: dict, deployment_name: str) -> dict:
        kube_context = parameters.get("kube_context", "")
        namespace = parameters.get("namespace", "default")
        try:
            self._validate_context_and_namespace(kube_context, namespace)
            self._kubectl(kube_context, "rollout", "restart", f"deployment/{deployment_name}", "-n", namespace)
            self._kubectl(
                kube_context, "rollout", "status", f"deployment/{deployment_name}", "-n", namespace,
                f"--timeout={self.config.kubernetes_rollout_timeout_seconds}s",
            )
            return {
                "status": "succeeded",
                "external_refs": {
                    "live_execution": True,
                    "kube_context": kube_context,
                    "deployment_name": deployment_name,
                    "rollout_action": "restart_deployment",
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def _live_rollback(self, parameters: dict, deployment_name: str, revision: str) -> dict:
        kube_context = parameters.get("kube_context", "")
        namespace = parameters.get("namespace", "default")
        try:
            self._validate_context_and_namespace(kube_context, namespace)
            self._kubectl(kube_context, "rollout", "undo", f"deployment/{deployment_name}", "-n", namespace)
            self._kubectl(
                kube_context, "rollout", "status", f"deployment/{deployment_name}", "-n", namespace,
                f"--timeout={self.config.kubernetes_rollout_timeout_seconds}s",
            )
            return {
                "status": "succeeded",
                "external_refs": {
                    "live_execution": True,
                    "kube_context": kube_context,
                    "deployment_name": deployment_name,
                    "rollout_action": "rollback_deployment",
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def _validate_context_and_namespace(self, kube_context: str, namespace: str) -> None:
        if self.config.kubernetes_allowed_contexts and kube_context not in self.config.kubernetes_allowed_contexts:
            raise _KubectlError(f"context '{kube_context}' is not in the allowed list")
        if self.config.kubernetes_allowed_namespaces and namespace not in self.config.kubernetes_allowed_namespaces:
            raise _KubectlError(f"namespace '{namespace}' is not in the allowed list")

    def _kubectl(self, kube_context: str, *args: str) -> str:
        cmd = shlex.split(self.config.kubectl_command)
        if kube_context:
            cmd.extend(["--context", kube_context])
        cmd.extend(args)
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=self.config.kubernetes_rollout_timeout_seconds + 10,
        )
        if completed.returncode != 0:
            raise _KubectlError(completed.stderr.strip() or f"kubectl exited {completed.returncode}")
        return completed.stdout.strip()


class _KubectlError(Exception):
    pass


class AuditLogAdapter:
    def write_record(self, decision: Decision, idempotency_key: str) -> dict:
        return {
            "status": "succeeded",
            "audit_log_id": f"audit_{decision.decision_id}",
            "idempotency_key": idempotency_key,
        }
