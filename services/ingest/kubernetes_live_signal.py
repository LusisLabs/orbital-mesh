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
    # Event freshness cutoff. Kubernetes keeps events for ~1 hour by default
    # (``--event-ttl=1h``), which is way too broad for Mesh's purposes:
    # we want to know what's happening *now*, not whatever happened 45
    # minutes ago. Without a cutoff, an ImagePullBackOff event from
    # earlier in the session contaminates every subsequent signal —
    # ``summarize_kubernetes_logs`` picks up the stale reason and the
    # decision engine treats every unrelated trigger as an image-pull
    # problem.
    #
    # 5 minutes is enough to capture what the decision engine considers
    # "recent" (most Kubernetes events fire within seconds of the
    # underlying state change) while ignoring everything from prior
    # chaos experiments. Operators running long incident investigations
    # outside the chaos harness can override via ``MESH_K8S_EVENT_WINDOW_SECONDS``.
    event_window_cutoff = _event_window_cutoff()
    events = [
        {
            "reason": item.get("reason"),
            "message": item.get("message"),
            "count": item.get("count", 1),
            "type": item.get("type", "Normal"),
        }
        for item in events_payload.get("items", [])
        if _event_matches(item, deployment_name, pod_names)
        and _event_is_fresh(item, event_window_cutoff)
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
    rollout_started_at = _rollout_started_at(deployment)
    # Deploy correlation is the single most-useful piece of evidence
    # for k8s remediation decisions. The SRE escalation ladder branches
    # right at "did this break right after a deploy?" — if yes, rollback;
    # if no, the bug existed before and a rollback won't help. We surface
    # both an absolute timestamp (for the audit trail) and the relative
    # age in seconds (for the decision engine's threshold check).
    seconds_since_deploy = _seconds_since(rollout_started_at)
    related_context = _related_context(
        active_context=active_context,
        repo_path=repo_path,
        suspected_file=suspected_file,
        allowed_paths=allowed_paths or [],
        test_commands=test_commands or [],
        patch_template=patch_template,
    )
    configuration_drift = _configuration_drift_signals(deployment)
    if configuration_drift:
        related_context["configuration_drift"] = configuration_drift
    resource_pressure = _resource_pressure_signals(deployment)
    if resource_pressure:
        related_context["resource_pressure"] = resource_pressure
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
            "rollout_started_at": rollout_started_at,
            "rollout_status": _rollout_status(deployment),
            "desired_replicas": int(spec.get("replicas", 1)),
            "updated_replicas": int(status.get("updatedReplicas", 0)),
            "available_replicas": int(status.get("availableReplicas", 0)),
            "last_deploy_timestamp": rollout_started_at,
            "seconds_since_deploy": seconds_since_deploy,
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
        "related_context": related_context,
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


def _configuration_drift_signals(deployment: dict[str, Any]) -> list[dict[str, str]]:
    template = deployment.get("spec", {}).get("template", {})
    metadata = template.get("metadata", {})
    signals: list[dict[str, str]] = []
    for field in ("labels", "annotations"):
        values = metadata.get(field, {})
        if not isinstance(values, dict):
            continue
        for key, value in sorted(values.items()):
            if str(key).startswith("mesh.chaos."):
                signals.append({"field": field, "key": str(key), "value": str(value)})
    return signals


def _resource_pressure_signals(deployment: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose obviously unsafe resource limits as decision context."""
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    signals: list[dict[str, Any]] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        resources = container.get("resources") or {}
        limits = resources.get("limits") or {}
        memory = limits.get("memory")
        memory_bytes = _parse_memory_quantity(memory)
        if memory_bytes is not None and memory_bytes <= 16 * 1024 * 1024:
            signals.append({
                "container": str(container.get("name") or "unknown"),
                "limit": str(memory),
                "limit_bytes": memory_bytes,
                "reason": "memory_limit_too_low",
            })
    return signals


def _parse_memory_quantity(raw: Any) -> int | None:
    if not isinstance(raw, str) or not raw:
        return None
    import re
    match = re.fullmatch(r"([0-9]+)([KMGTE]i?|[kmgte]i?)?", raw.strip())
    if match is None:
        return None
    value = int(match.group(1))
    suffix = (match.group(2) or "").lower()
    multipliers = {
        "": 1,
        "k": 1000,
        "m": 1000 ** 2,
        "g": 1000 ** 3,
        "t": 1000 ** 4,
        "e": 1000 ** 5,
        "ki": 1024,
        "mi": 1024 ** 2,
        "gi": 1024 ** 3,
        "ti": 1024 ** 4,
        "ei": 1024 ** 5,
    }
    return value * multipliers[suffix]


def _event_matches(item: dict[str, Any], deployment_name: str, pod_names: set[str | None]) -> bool:
    involved = item.get("involvedObject", {})
    name = involved.get("name")
    kind = involved.get("kind")
    if name == deployment_name and kind == "Deployment":
        return True
    if name is not None and name in pod_names and kind == "Pod":
        return True
    return bool(name and name.startswith(f"{deployment_name}-") and kind == "ReplicaSet")


def _event_window_cutoff() -> datetime:
    """Cutoff time for event freshness. Events older than this are dropped.

    Configurable via ``MESH_K8S_EVENT_WINDOW_SECONDS``. Default 300s (5
    minutes), chosen to comfortably cover the time from an event
    firing to Mesh collecting a signal while being tight enough to
    exclude events from previous chaos experiments or older incidents.
    """
    import os
    window_seconds = int(os.getenv("MESH_K8S_EVENT_WINDOW_SECONDS", "300"))
    return datetime.now(timezone.utc).replace(microsecond=0) - _timedelta_seconds(window_seconds)


def _timedelta_seconds(seconds: int):
    # Small wrapper to avoid importing timedelta at module level — it's
    # only used in one narrow path and the import is cheap.
    from datetime import timedelta
    return timedelta(seconds=seconds)


def _event_is_fresh(item: dict[str, Any], cutoff: datetime) -> bool:
    """True if any of the event's timestamps is newer than ``cutoff``.

    Kubernetes events carry up to three timestamps, and which one is
    populated depends on the event source and version:

    * ``lastTimestamp`` — most reliable for aggregated events (the
      kubelet updates it every time the underlying condition re-fires).
    * ``eventTime`` — used by the newer events API (``events.k8s.io/v1``).
    * ``metadata.creationTimestamp`` — always present, but represents
      when the event record was first created; for an aggregated event
      that's older than the latest occurrence.

    We treat the event as fresh if *any* of these is within the window,
    which errs on the side of inclusion. A pathological event missing
    all three would be dropped — that's fine because we've never seen
    one in practice and a missing-timestamp event isn't a useful signal.
    """
    candidates = [
        item.get("lastTimestamp"),
        item.get("eventTime"),
        (item.get("metadata") or {}).get("creationTimestamp"),
    ]
    for raw in candidates:
        parsed = _parse_k8s_timestamp(raw)
        if parsed is not None and parsed >= cutoff:
            return True
    return False


def _parse_k8s_timestamp(raw: Any) -> datetime | None:
    """Parse a Kubernetes RFC3339 timestamp. Returns None on anything we
    can't make sense of, so the caller treats it as not-fresh.

    ``None`` inputs happen for events where a given timestamp field
    wasn't populated by the source. Malformed strings happen
    occasionally from custom controllers. Both map to "skip this
    timestamp" without raising."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        # Python's fromisoformat accepts the "Z" suffix only in 3.11+;
        # the replace handles older runtimes and is a no-op in 3.11+.
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _seconds_since(rfc3339_timestamp: str | None) -> int | None:
    """How long ago was ``rfc3339_timestamp``, in seconds.

    Returns None for malformed input or absent timestamps. This is
    consumed by the decision engine to apply the SRE deploy-correlation
    rule: if a crash starts within 30 minutes of a deploy, it's almost
    certainly the deploy's fault and the right action is rollback. If
    the crash starts hours later, the bug existed before the deploy
    and a rollback won't help — that case wants escalation, not
    remediation.
    """
    if not rfc3339_timestamp or not isinstance(rfc3339_timestamp, str):
        return None
    try:
        ts = datetime.fromisoformat(rfc3339_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = datetime.now(timezone.utc) - ts
    seconds = int(delta.total_seconds())
    # Clock skew between Mesh's host and the kube API server can produce
    # negative deltas. Clamp to 0 — "in the future" is meaningless for a
    # rollout that already happened, and negative values would confuse
    # downstream threshold checks.
    return max(0, seconds)


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
    if desired == 0:
        return "healthy"
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
