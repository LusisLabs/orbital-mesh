"""Local actuator adapters used by the native orchestration integration."""

from __future__ import annotations

import shlex
import subprocess
from typing import Any, TypedDict

from shared.mesh_runtime import Decision, RuntimeConfig


class ActuatorResult(TypedDict, total=False):
    """Return shape shared by every actuator adapter.

    ``status`` is always present; ``external_refs`` is populated on success;
    ``failure`` is populated when status=='failed'.
    """

    status: str
    external_refs: dict[str, Any]
    failure: dict[str, Any]
    audit_log_id: str
    idempotency_key: str


class KubernetesParameters(TypedDict, total=False):
    deployment_name: str
    namespace: str
    kube_context: str
    revision: str
    pod_name: str
    replicas: int
    node_name: str
    grace_period_seconds: int


class FeatureFlagAdapter:
    def set_rollout(self, parameters: dict[str, Any]) -> ActuatorResult:
        return {
            "status": "succeeded",
            "external_refs": {"flag_change_id": f"ffchg_{parameters['flag_key']}_{parameters['rollout_pct']}"},
        }


class IncidentAdapter:
    def open_incident(self, parameters: dict[str, Any]) -> ActuatorResult:
        incident_scope = parameters.get("service") or parameters.get("decision_id") or parameters.get("flag_key") or "unknown"
        return {
            "status": "succeeded",
            "external_refs": {"incident_id": f"inc_{incident_scope}"},
        }


class KubernetesAdapter:
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()

    def rollback_deployment(self, parameters: KubernetesParameters) -> ActuatorResult:
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

    def restart_deployment(self, parameters: KubernetesParameters) -> ActuatorResult:
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

    def restart_pod(self, parameters: KubernetesParameters) -> ActuatorResult:
        """Delete a single pod, relying on its owning controller to recreate it."""
        pod_name = parameters.get("pod_name")
        if not pod_name:
            return {
                "status": "failed",
                "failure": {"reason": "missing_parameter", "detail": "pod_name is required"},
                "external_refs": {},
            }
        namespace = parameters.get("namespace", "default")
        kube_context = parameters.get("kube_context", "")
        if not self.config.kubernetes_live_execution_enabled:
            return {
                "status": "succeeded",
                "external_refs": {
                    "rollout_change_id": f"k8sdeletepod_{namespace}_{pod_name}",
                    "rollout_action": "restart_pod",
                },
            }
        try:
            self._validate_context_and_namespace(kube_context, namespace)
            self._kubectl(kube_context, "delete", "pod", pod_name, "-n", namespace)
            return {
                "status": "succeeded",
                "external_refs": {
                    "live_execution": True,
                    "kube_context": kube_context,
                    "pod_name": pod_name,
                    "rollout_action": "restart_pod",
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def scale_deployment(self, parameters: KubernetesParameters) -> ActuatorResult:
        deployment_name = parameters.get("deployment_name")
        replicas = parameters.get("replicas")
        if not deployment_name or replicas is None:
            return {
                "status": "failed",
                "failure": {"reason": "missing_parameter",
                            "detail": "deployment_name and replicas are required"},
                "external_refs": {},
            }
        if not isinstance(replicas, int) or replicas < 0:
            return {
                "status": "failed",
                "failure": {"reason": "invalid_parameter",
                            "detail": f"replicas must be a non-negative integer, got {replicas!r}"},
                "external_refs": {},
            }
        namespace = parameters.get("namespace", "default")
        kube_context = parameters.get("kube_context", "")
        if not self.config.kubernetes_live_execution_enabled:
            return {
                "status": "succeeded",
                "external_refs": {
                    "rollout_change_id": f"k8sscale_{namespace}_{deployment_name}_{replicas}",
                    "rollout_action": "scale_deployment",
                    "replicas": replicas,
                },
            }
        try:
            self._validate_context_and_namespace(kube_context, namespace)
            self._kubectl(
                kube_context, "scale", f"deployment/{deployment_name}",
                f"--replicas={replicas}", "-n", namespace,
            )
            return {
                "status": "succeeded",
                "external_refs": {
                    "live_execution": True,
                    "kube_context": kube_context,
                    "deployment_name": deployment_name,
                    "rollout_action": "scale_deployment",
                    "replicas": replicas,
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def cordon_node(self, parameters: KubernetesParameters) -> ActuatorResult:
        node_name = parameters.get("node_name")
        if not node_name:
            return {
                "status": "failed",
                "failure": {"reason": "missing_parameter", "detail": "node_name is required"},
                "external_refs": {},
            }
        kube_context = parameters.get("kube_context", "")
        if not self.config.kubernetes_live_execution_enabled:
            return {
                "status": "succeeded",
                "external_refs": {
                    "rollout_change_id": f"k8scordon_{node_name}",
                    "rollout_action": "cordon_node",
                },
            }
        try:
            self._validate_context_only(kube_context)
            self._kubectl(kube_context, "cordon", node_name)
            return {
                "status": "succeeded",
                "external_refs": {
                    "live_execution": True,
                    "kube_context": kube_context,
                    "node_name": node_name,
                    "rollout_action": "cordon_node",
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def drain_node(self, parameters: KubernetesParameters) -> ActuatorResult:
        """Cordon + drain a node.  Destructive — only reachable via approval tier."""
        node_name = parameters.get("node_name")
        if not node_name:
            return {
                "status": "failed",
                "failure": {"reason": "missing_parameter", "detail": "node_name is required"},
                "external_refs": {},
            }
        kube_context = parameters.get("kube_context", "")
        grace = int(parameters.get("grace_period_seconds", 60))
        if not self.config.kubernetes_live_execution_enabled:
            return {
                "status": "succeeded",
                "external_refs": {
                    "rollout_change_id": f"k8sdrain_{node_name}",
                    "rollout_action": "drain_node",
                },
            }
        try:
            self._validate_context_only(kube_context)
            self._kubectl(
                kube_context, "drain", node_name,
                "--ignore-daemonsets",
                "--delete-emptydir-data",
                f"--grace-period={grace}",
                f"--timeout={self.config.kubernetes_rollout_timeout_seconds}s",
            )
            return {
                "status": "succeeded",
                "external_refs": {
                    "live_execution": True,
                    "kube_context": kube_context,
                    "node_name": node_name,
                    "rollout_action": "drain_node",
                    "grace_period_seconds": grace,
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def _live_restart(self, parameters: KubernetesParameters, deployment_name: str) -> ActuatorResult:
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

    def _live_rollback(self, parameters: KubernetesParameters, deployment_name: str, revision: str) -> ActuatorResult:
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

    def _validate_context_only(self, kube_context: str) -> None:
        """Context-scope validation for cluster-level operations (cordon/drain)."""
        if self.config.kubernetes_allowed_contexts and kube_context not in self.config.kubernetes_allowed_contexts:
            raise _KubectlError(f"context '{kube_context}' is not in the allowed list")

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
    def write_record(self, decision: Decision, idempotency_key: str) -> ActuatorResult:
        return {
            "status": "succeeded",
            "audit_log_id": f"audit_{decision.decision_id}",
            "idempotency_key": idempotency_key,
        }
