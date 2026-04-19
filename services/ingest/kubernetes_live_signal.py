"""Collect live Kubernetes deployment state into the mesh signal contract."""

from __future__ import annotations

import json
import re
import shutil
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any


def collect_kubernetes_signal(
    *,
    deployment_name: str,
    namespace: str = "default",
    kube_context: str | None = None,
    environment: str = "local",
    cluster_label: str | None = None,
    service: str | None = None,
    kubectl_command: str = "kubectl",
    tail_lines: int = 20,
    max_log_pods: int = 3,
    repo_path: str | None = None,
    suspected_file: str | None = None,
    allowed_paths: list[str] | None = None,
    test_commands: list[str] | None = None,
    patch_template: dict[str, str] | None = None,
) -> dict[str, Any]:
    kubectl_base = shlex.split(kubectl_command)
    if not kubectl_base:
        raise RuntimeError("kubectl command is empty; set MESH_KUBECTL_COMMAND or pass --kubectl-command")
    executable = kubectl_base[0]
    if shutil.which(executable) is None and not executable.startswith("/"):
        raise RuntimeError(f"kubectl command not found: {kubectl_command}")
    if kube_context:
        kubectl_base.extend(["--context", kube_context])
        active_context = kube_context
    else:
        active_context = _run_text(kubectl_base + ["config", "current-context"]).strip()

    deployment = _run_json(kubectl_base + ["get", "deployment", deployment_name, "-n", namespace, "-o", "json"])
    label_selector = _selector(deployment.get("spec", {}).get("selector", {}).get("matchLabels", {}))
    pods_payload = _run_json(kubectl_base + ["get", "pods", "-n", namespace, "-l", label_selector, "-o", "json"])
    events_payload = _run_json(kubectl_base + ["get", "events", "-n", namespace, "-o", "json"])

    pod_items = pods_payload.get("items", [])
    pod_names = {pod.get("metadata", {}).get("name") for pod in pod_items}
    events = [
        {
            "reason": item.get("reason"),
            "message": item.get("message"),
            "count": item.get("count", 1),
            "type": item.get("type", "Normal"),
        }
        for item in events_payload.get("items", [])
        if _event_matches(item, deployment_name, pod_names)
    ]

    pods = [_summarize_pod(item) for item in pod_items]
    log_entries = []
    failing_pods = [pod for pod in pods if not pod["ready"] or pod["restarts"] > 0]
    for pod in sorted(failing_pods, key=lambda item: (-item["restarts"], item["name"]))[:max_log_pods]:
        if pod["container"] is None:
            continue
        logs = _run_text(
            kubectl_base + ["logs", pod["name"], "-n", namespace, "-c", pod["container"], "--tail", str(tail_lines)],
            allow_failure=True,
        ).strip()
        if not logs:
            continue
        for line in logs.splitlines():
            log_entries.append(
                {
                    "pod": pod["name"],
                    "container": pod["container"],
                    "stream": "stderr" if _is_errorish(line) else "stdout",
                    "message": line,
                }
            )

    revision = deployment.get("metadata", {}).get("annotations", {}).get("deployment.kubernetes.io/revision")
    status = deployment.get("status", {})
    spec = deployment.get("spec", {})
    signal = {
        "signal_type": "kubernetes_deployment_issue",
        "signal_id": f"sig_k8s_{_slugify(namespace)}_{_slugify(deployment_name)}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "cluster": cluster_label or active_context,
        "namespace": namespace,
        "service": service or deployment_name,
        "deployment": {
            "name": deployment_name,
            "revision": str(revision or "unknown"),
            "image": _first_container_image(deployment) or "unknown",
            "rollout_started_at": _rollout_started_at(deployment),
            "rollout_status": _rollout_status(deployment),
            "desired_replicas": int(spec.get("replicas", 1)),
            "updated_replicas": int(status.get("updatedReplicas", 0)),
            "available_replicas": int(status.get("availableReplicas", 0)),
        },
        "pods": [
            {
                "name": pod["name"],
                "phase": pod["phase"],
                "ready": pod["ready"],
                "restarts": pod["restarts"],
                "container_status": pod["container_status"],
                "last_state_reason": pod["last_state_reason"],
            }
            for pod in pods
        ],
        "events": events,
        "logs": log_entries,
        "related_context": _related_context(
            active_context=active_context,
            repo_path=repo_path,
            suspected_file=suspected_file,
            allowed_paths=allowed_paths or [],
            test_commands=test_commands or [],
            patch_template=patch_template,
        ),
        "post_action_observations": {},
    }
    return signal


def _related_context(
    *,
    active_context: str,
    repo_path: str | None,
    suspected_file: str | None,
    allowed_paths: list[str],
    test_commands: list[str],
    patch_template: dict[str, str] | None,
) -> dict[str, Any]:
    related_context: dict[str, Any] = {
        "active_incidents": 0,
        "similar_prior_cases": 0,
        "rollbacks_last_24h": 0,
        "cluster_access_available": True,
        "audit_logging_available": True,
        "kube_context": active_context,
        "code_remediation_candidate": False,
    }
    patch_fields_present = all(
        [
            repo_path,
            suspected_file,
            allowed_paths,
            test_commands,
            isinstance(patch_template, dict),
            patch_template.get("target_file") if isinstance(patch_template, dict) else None,
            patch_template.get("find") if isinstance(patch_template, dict) else None,
            patch_template.get("replace") if isinstance(patch_template, dict) else None,
        ]
    )
    if patch_fields_present:
        related_context.update(
            {
                "code_remediation_candidate": True,
                "repo_path": repo_path,
                "suspected_file": suspected_file,
                "allowed_paths": list(allowed_paths),
                "test_commands": list(test_commands),
                "patch_template": {
                    "target_file": patch_template["target_file"],
                    "find": patch_template["find"],
                    "replace": patch_template["replace"],
                },
            }
        )
    return related_context


def _selector(match_labels: dict[str, str]) -> str:
    if not match_labels:
        raise ValueError("deployment selector.matchLabels is empty")
    return ",".join(f"{key}={value}" for key, value in sorted(match_labels.items()))


def _event_matches(item: dict[str, Any], deployment_name: str, pod_names: set[str | None]) -> bool:
    involved = item.get("involvedObject", {})
    name = involved.get("name")
    kind = involved.get("kind")
    if name == deployment_name and kind == "Deployment":
        return True
    if name in pod_names and kind == "Pod":
        return True
    return bool(name and name.startswith(f"{deployment_name}-") and kind in {"ReplicaSet", "Pod"})


def _summarize_pod(item: dict[str, Any]) -> dict[str, Any]:
    status = item.get("status", {})
    container_statuses = status.get("containerStatuses", [])
    primary = container_statuses[0] if container_statuses else {}
    state = primary.get("state", {})
    waiting = state.get("waiting", {})
    terminated = primary.get("lastState", {}).get("terminated", {})
    return {
        "name": item.get("metadata", {}).get("name"),
        "phase": status.get("phase"),
        "ready": bool(primary.get("ready", False)),
        "restarts": int(primary.get("restartCount", 0)),
        "container": primary.get("name"),
        "container_status": waiting.get("reason") or status.get("phase"),
        "last_state_reason": terminated.get("reason"),
    }


def _first_container_image(payload: dict[str, Any]) -> str | None:
    containers = payload.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    if not containers:
        return None
    return containers[0].get("image")


def _rollout_started_at(payload: dict[str, Any]) -> str:
    conditions = payload.get("status", {}).get("conditions", [])
    for condition in reversed(conditions):
        if condition.get("type") == "Progressing" and condition.get("lastUpdateTime"):
            return condition["lastUpdateTime"]
    return payload.get("metadata", {}).get("creationTimestamp") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rollout_status(payload: dict[str, Any]) -> str:
    spec = payload.get("spec", {})
    status = payload.get("status", {})
    desired = int(spec.get("replicas", 1))
    available = int(status.get("availableReplicas", 0))
    updated = int(status.get("updatedReplicas", 0))
    for condition in status.get("conditions", []):
        if condition.get("type") == "Progressing" and condition.get("reason") == "ProgressDeadlineExceeded":
            return "failed"
    if desired > 0 and available >= desired and updated >= desired:
        return "healthy"
    if available == 0 and updated < desired:
        return "failed" if _has_image_pull_signal(payload) else "degraded"
    return "degraded"


def _has_image_pull_signal(payload: dict[str, Any]) -> bool:
    image = (_first_container_image(payload) or "").lower()
    return image.endswith(":does-not-exist")


def _run_json(command: list[str]) -> dict[str, Any]:
    completed = _run_completed(command)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command returned invalid JSON: {shlex.join(command)}: {exc}") from exc


def _run_text(command: list[str], allow_failure: bool = False) -> str:
    completed = _run_completed(command, allow_failure=allow_failure)
    return completed.stdout


def _run_completed(command: list[str], allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{shlex.join(command)} failed: {exc}") from exc
    if completed.returncode != 0 and not allow_failure:
        message = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise RuntimeError(f"{shlex.join(command)} failed: {message}")
    return completed


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _is_errorish(line: str) -> bool:
    lowered = line.lower()
    return any(token in lowered for token in ("error", "exception", "traceback", "panic", "module not found"))
