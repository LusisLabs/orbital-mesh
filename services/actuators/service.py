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

    def scale_deployment(self, parameters: dict) -> dict:
        """Scale a deployment by ``replicas_delta`` (or to an absolute ``replicas``).

        Rule-based metric actions drive this path. The delta style is preferred
        because rules operate on attributes (the current replica count isn't in
        the signal), and the actuator resolves the target count from the live
        cluster. When the absolute ``replicas`` is supplied it takes precedence —
        useful for operator overrides via the steering API.

        Safety envelope:

        * Mock mode returns a deterministic ``external_refs`` without touching
          the cluster — this keeps local tests hermetic and preserves the
          approval gate as the only place real state changes.
        * Live mode passes through context/namespace allowlists before issuing
          ``kubectl scale``. An actuator failure is returned as
          ``status: failed`` so the feedback stage can record it and the run
          moves to ``escalate`` — we never raise through the pipeline boundary.
        """
        deployment_name = parameters["deployment_name"]
        replicas_delta = parameters.get("replicas_delta", 0)
        absolute_replicas = parameters.get("replicas")
        if self.config.kubernetes_live_execution_enabled:
            return self._live_scale(parameters, deployment_name, replicas_delta, absolute_replicas)
        target = absolute_replicas if absolute_replicas is not None else f"+{replicas_delta}"
        return {
            "status": "succeeded",
            "external_refs": {
                "rollout_change_id": f"k8sscale_{deployment_name}_{target}",
                "rollout_action": "scale_deployment",
                "replicas_delta": replicas_delta,
                "replicas": absolute_replicas,
            },
        }

    def patch_resources(self, parameters: dict) -> dict:
        """Patch CPU/memory requests or limits on a deployment's container.

        Typical rule: "when memory saturation metric climbs, raise memory limit
        by one bracket". The actuator issues ``kubectl set resources`` because
        it's safer than a free-form ``kubectl patch`` (no way to accidentally
        touch fields the rule didn't intend) and carries a predictable rollback:
        re-run with the prior values.
        """
        deployment_name = parameters["deployment_name"]
        if self.config.kubernetes_live_execution_enabled:
            return self._live_patch_resources(parameters, deployment_name)
        return {
            "status": "succeeded",
            "external_refs": {
                "rollout_change_id": f"k8spatch_{deployment_name}",
                "rollout_action": "patch_resources",
                "requested_limits": parameters.get("limits"),
                "requested_requests": parameters.get("requests"),
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

    def _live_scale(
        self,
        parameters: dict,
        deployment_name: str,
        replicas_delta: int,
        absolute_replicas: int | None,
    ) -> dict:
        """Real ``kubectl scale`` path.

        When ``absolute_replicas`` is provided we use it directly. Otherwise we
        read the current replica count (``kubectl get deployment -o ...``) and
        add the delta — keeping the rule declarative ("scale up by 2") rather
        than forcing operators to know current state when they author a rule.
        """
        kube_context = parameters.get("kube_context", "")
        namespace = parameters.get("namespace", "default")
        try:
            self._validate_context_and_namespace(kube_context, namespace)
            if absolute_replicas is None:
                current_replicas = self._current_replica_count(kube_context, deployment_name, namespace)
                target_replicas = max(0, int(current_replicas) + int(replicas_delta))
            else:
                target_replicas = int(absolute_replicas)
            self._kubectl(
                kube_context,
                "scale",
                f"deployment/{deployment_name}",
                "-n",
                namespace,
                f"--replicas={target_replicas}",
            )
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
                    "rollout_action": "scale_deployment",
                    "target_replicas": target_replicas,
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def _live_patch_resources(self, parameters: dict, deployment_name: str) -> dict:
        """Real ``kubectl set resources`` path.

        We deliberately scope the operation to a single ``container`` — cluster-
        wide patches are too easy to get wrong. Rules must identify which
        container to adjust (usually via ``{attributes.k8s.container.name}``).
        """
        kube_context = parameters.get("kube_context", "")
        namespace = parameters.get("namespace", "default")
        container = parameters.get("container")
        if not container:
            return {
                "status": "failed",
                "failure": {"reason": "patch_resources_missing_container", "detail": "container is required"},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }
        limits = parameters.get("limits") or {}
        requests = parameters.get("requests") or {}
        if not limits and not requests:
            return {
                "status": "failed",
                "failure": {"reason": "patch_resources_empty", "detail": "limits or requests required"},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }
        try:
            self._validate_context_and_namespace(kube_context, namespace)
            args: list[str] = [
                "set", "resources", f"deployment/{deployment_name}", "-n", namespace,
                "--containers", str(container),
            ]
            if limits:
                args.append("--limits=" + ",".join(f"{k}={v}" for k, v in limits.items()))
            if requests:
                args.append("--requests=" + ",".join(f"{k}={v}" for k, v in requests.items()))
            self._kubectl(kube_context, *args)
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
                    "rollout_action": "patch_resources",
                    "applied_limits": limits,
                    "applied_requests": requests,
                    "container": container,
                },
            }
        except _KubectlError as exc:
            return {
                "status": "failed",
                "failure": {"reason": "kubernetes_live_execution_failed", "detail": str(exc)},
                "external_refs": {"live_execution": True, "kube_context": kube_context},
            }

    def _current_replica_count(self, kube_context: str, deployment_name: str, namespace: str) -> int:
        """Read the current deployment replica count via kubectl.

        Isolated so tests can stub it — live scale tests shouldn't have to mock
        the full kubectl path, just the lookup.
        """
        raw = self._kubectl(
            kube_context,
            "get",
            f"deployment/{deployment_name}",
            "-n",
            namespace,
            "-o",
            "jsonpath={.spec.replicas}",
        )
        try:
            return int(raw.strip() or "0")
        except ValueError as exc:
            raise _KubectlError(f"could not parse current replica count from {raw!r}") from exc

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
