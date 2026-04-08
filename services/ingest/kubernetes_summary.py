"""Summarize Kubernetes logs and events into decision-friendly signals."""

from __future__ import annotations


def summarize_kubernetes_logs(logs: list[dict], events: list[dict], pods: list[dict]) -> dict:
    messages = [str(entry.get("message", "")) for entry in logs]
    event_text = [f"{event.get('reason', '')}: {event.get('message', '')}" for event in events]
    signatures: list[str] = []
    categories: list[str] = []

    if _contains_any(messages + event_text, ("CrashLoopBackOff", "Back-off restarting failed container")):
        signatures.append("crash_loop")
        categories.append("runtime")
    if _contains_any(messages + event_text, ("ImagePullBackOff", "ErrImagePull")):
        signatures.append("image_pull_failure")
        categories.append("supply_chain")
    if _contains_any(messages + event_text, ("OOMKilled", "Killed process out of memory")):
        signatures.append("oom_killed")
        categories.append("resources")
    if _contains_any(messages + event_text, ("Readiness probe failed", "Liveness probe failed", "Unhealthy")):
        signatures.append("probe_failure")
        categories.append("platform")
    if _contains_any(messages, ("ModuleNotFoundError", "ImportError", "SyntaxError", "panic:", "Exception in thread")):
        signatures.append("application_error")
        categories.append("application")
    if _contains_any(messages, ("connection refused", "timed out", "i/o timeout", "dial tcp")):
        signatures.append("dependency_connectivity")
        categories.append("dependency")
    if any(int(pod.get("restarts", 0)) >= 3 for pod in pods):
        signatures.append("high_restart_rate")
        categories.append("runtime")

    unique_signatures = _unique(signatures)
    unique_categories = _unique(categories)
    primary_symptom = unique_signatures[0] if unique_signatures else "unknown"
    likely_layer = _likely_layer(unique_signatures)
    return {
        "primary_symptom": primary_symptom,
        "error_signatures": unique_signatures,
        "categories": unique_categories,
        "likely_layer": likely_layer,
        "sample_lines": [line for line in messages[:3] if line],
        "event_reasons": _unique([str(event.get("reason", "")) for event in events if event.get("reason")]),
        "restart_count_total": sum(int(pod.get("restarts", 0)) for pod in pods),
    }


def _contains_any(values: list[str], needles: tuple[str, ...]) -> bool:
    lower_values = [value.lower() for value in values]
    return any(needle.lower() in value for value in lower_values for needle in needles)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _likely_layer(signatures: list[str]) -> str:
    if "image_pull_failure" in signatures:
        return "supply_chain"
    if "oom_killed" in signatures or "probe_failure" in signatures:
        return "platform"
    if "application_error" in signatures:
        return "application"
    if "dependency_connectivity" in signatures:
        return "dependency"
    if "crash_loop" in signatures:
        return "runtime"
    return "unknown"
