"""CloudOpsBench domain pack for the investigation harness.

This module is the first proof that the harness contracts generalize:

* ``register_cloudops_tools(registry, snapshot_tools)`` registers the
  eight Cloud-OpsBench diagnostic tools as ``ToolDefinition``s, all
  read-only, all backed by the snapshot tool cache.
* ``CloudOpsRulePack`` describes typed native probe-selection rules.
* ``CloudOpsLoopPlanner`` remains as a compatibility wrapper around the
  shared ``NativeProbeSelector``.

Domain logic lives in rules; registry, critic, and loop orchestration
remain shared.
"""

from __future__ import annotations

import re
from typing import Any

from shared.mesh_runtime import Trigger

from .cloudops_ontology import rank_root_causes
from .harness import (
    InvestigationLoopState,
    LoopDecision,
    LoopPlanner,
    NativeProbeSelector,
    ObservationIndex,
    ProbeRule,
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)
from .harness.native_selector import RootCauseCandidate, RootCauseRanker


_RESOURCE_LINE_RE = re.compile(
    r"^\s*([a-z][a-z0-9-]+(?:-[a-z0-9]+)*)\s+(\d+)/(\d+)\s+([A-Za-z]+)(?:\s+(\d+))?\b"
)
_HEX_SUFFIX_RE = re.compile(r"[a-f0-9]{4,}")

CLOUDOPS_DOMAIN = "cloudops"
_OUTPUT_SUMMARY_LIMIT = 4000


def _build_tool_definitions() -> list[ToolDefinition]:
    """Return the eight CloudOpsBench diagnostic tools as definitions.

    Args schema is intentionally minimal — CloudOps tools accept the
    Kubernetes-style ``resource_type`` / ``name`` / ``namespace`` triple
    plus a couple of optional flags. The critic uses this to reject
    obvious typos before the snapshot lookup runs.
    """
    common_args = {
        "resource_type": {"type": "str", "required": False},
        "name": {"type": "str", "required": False},
        "app_name": {"type": "str", "required": False},
        "namespace": {"type": "str", "required": False, "nullable": True},
    }
    descriptions = {
        "GetResources": "List Kubernetes resources of a given kind in a namespace.",
        "DescribeResource": "Describe a specific Kubernetes resource (events, status, conditions).",
        "GetAppYAML": "Read the deployment / application YAML for a workload.",
        "GetErrorLogs": "Read recent error logs from a pod or workload.",
        "GetAlerts": "Read active alerts in a namespace.",
        "CheckServiceConnectivity": "Check service-to-service connectivity (DNS, port).",
        "GetClusterConfiguration": "Read cluster-level configuration (apiserver, controller).",
        "GetRecentLogs": "Read recent (non-error-filtered) logs from a workload.",
    }
    return [
        ToolDefinition(
            name=name,
            domain=CLOUDOPS_DOMAIN,
            description=description,
            args_schema=dict(common_args),
            mutation_class="read_only",
            timeout_seconds=2.0,
            budget_cost=1.0,
            citations_kind="cloudopsbench_snapshot",
        )
        for name, description in descriptions.items()
    ]


CLOUDOPS_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(_build_tool_definitions())
CLOUDOPS_TOOL_NAMES: tuple[str, ...] = tuple(d.name for d in CLOUDOPS_TOOL_DEFINITIONS)


def register_cloudops_tools(registry: ToolRegistry, snapshot_tools: Any) -> None:
    """Register CloudOps tool definitions, backed by ``snapshot_tools``.

    Each tool's invoke function calls ``snapshot_tools.invoke(name, args)``
    and reports validity from the returned snapshot call record. The
    snapshot tool cache is read-only: every registration here carries
    ``mutation_class="read_only"`` so the critic cannot let one slip
    through to a mutating path.

    Also registers the K8sGPT-style analyzer tools (admission events,
    node dataplane, service routing) — these compose multiple snapshot
    calls into pre-canned investigation recipes whose summaries match
    the cloudops ontology, addressing the failure modes documented in
    ``cloudops_analyzers.py``.
    """
    for definition in CLOUDOPS_TOOL_DEFINITIONS:
        registry.register(definition, _make_cloudops_invoker(definition.name, snapshot_tools))
    # Imported here to avoid a circular import at module load — analyzers
    # depend on the registry types this module exports.
    from .cloudops_analyzers import register_cloudops_analyzers

    register_cloudops_analyzers(registry, snapshot_tools)


def _make_cloudops_invoker(tool_name: str, snapshot_tools: Any):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        output = snapshot_tools.invoke(tool_name, args)
        last = snapshot_tools.calls[-1] if getattr(snapshot_tools, "calls", None) else None
        valid = bool(last.valid) if last is not None else False
        summary = _summarize_output(output)
        citations = [{"source_type": f"cloudopsbench:{tool_name}", "source_ref": _arg_summary(args) or tool_name}]
        return RawToolOutput(
            output=output,
            output_summary=summary,
            citations=citations,
            valid=valid,
            redaction_status="clean",
            status="completed",
        )

    return invoke


class CloudOpsRulePack:
    """CloudOps native selector rules over Kubernetes-style observations."""

    domain: str = CLOUDOPS_DOMAIN
    tool_definitions: tuple[ToolDefinition, ...] = CLOUDOPS_TOOL_DEFINITIONS
    sufficient_stop_reason: str = "root_cause_candidate_found"
    exhausted_stop_reason: str = "evidence_value_exhausted"

    def __init__(self, trigger: Trigger) -> None:
        self._trigger = trigger
        self._namespace = _trigger_namespace(trigger)
        self.root_cause_ranker: RootCauseRanker | None = rank_root_causes
        self.rules: tuple[ProbeRule, ...] = (
            ProbeRule(
                name="inventory_discovery",
                tool_name="GetResources",
                when=self._needs_inventory,
                build_args=self._inventory_args,
                selection_reason=self._inventory_reason,
                priority=10,
                confidence=0.6,
            ),
            ProbeRule(
                name="describe_suspect",
                tool_name="DescribeResource",
                when=self._should_describe,
                build_args=self._describe_args,
                selection_reason=self._describe_reason,
                priority=20,
                confidence=0.65,
            ),
            ProbeRule(
                name="alert_context",
                tool_name="GetAlerts",
                when=self._has_alert_signal,
                build_args=self._alerts_args,
                selection_reason=self._alerts_reason,
                priority=30,
                confidence=0.55,
            ),
            ProbeRule(
                name="deployment_inventory",
                tool_name="GetResources",
                when=self._should_list_deployments,
                build_args=self._deployment_inventory_args,
                selection_reason=self._deployment_inventory_reason,
                priority=35,
                confidence=0.6,
            ),
            ProbeRule(
                name="image_or_config_spec",
                tool_name="GetAppYAML",
                when=self._has_image_or_config_signal,
                build_args=self._app_yaml_args,
                selection_reason=self._app_yaml_reason,
                priority=40,
                confidence=0.65,
            ),
            ProbeRule(
                name="runtime_failure_logs",
                tool_name="GetErrorLogs",
                when=self._has_runtime_failure_signal,
                build_args=self._error_logs_args,
                selection_reason=self._error_logs_reason,
                priority=50,
                confidence=0.7,
            ),
            ProbeRule(
                name="network_service_check",
                tool_name="CheckServiceConnectivity",
                when=self._has_network_or_service_signal,
                build_args=self._connectivity_args,
                selection_reason=self._connectivity_reason,
                priority=60,
                confidence=0.6,
            ),
            ProbeRule(
                name="cluster_configuration_check",
                tool_name="GetClusterConfiguration",
                when=self._has_scheduling_signal,
                build_args=self._cluster_config_args,
                selection_reason=self._cluster_config_reason,
                priority=70,
                confidence=0.6,
            ),
            ProbeRule(
                name="recent_event_logs",
                tool_name="GetRecentLogs",
                when=self._has_event_signal,
                build_args=self._recent_logs_args,
                selection_reason=self._recent_logs_reason,
                priority=80,
                confidence=0.55,
            ),
        )

    def sufficient_root_cause(self, index: ObservationIndex) -> RootCauseCandidate | None:
        top = index.top_root_cause()
        if top is None or top.confidence < 0.55 or len(top.supporting_tools) < 2:
            return None
        if top.root_cause == "crash_loop_backoff" and not index.tool_called("GetErrorLogs"):
            return None
        return top

    def _needs_inventory(self, index: ObservationIndex) -> bool:
        return not index.tool_called("GetResources")

    def _inventory_args(self, _index: ObservationIndex) -> dict[str, Any]:
        return {"resource_type": "pods", "namespace": self._namespace}

    def _inventory_reason(self, _index: ObservationIndex) -> str:
        return "inventory_discovery: inspect observed resource health before targeted probes"

    def _should_describe(self, index: ObservationIndex) -> bool:
        suspect = self._effective_suspect(index)
        if not suspect:
            return False
        return (
            _has_explicit_suspect_hint(self._trigger)
            or _has_resource_status_signal(index)
            or self._discovered_suspect(index) == suspect
        )

    def _describe_args(self, index: ObservationIndex) -> dict[str, Any]:
        return {"resource_type": "pods", "name": self._effective_suspect(index) or "", "namespace": self._namespace}

    def _describe_reason(self, index: ObservationIndex) -> str:
        suspect = self._effective_suspect(index) or "suspect"
        reason_prefix = "explicit_suspect_hint" if _has_explicit_suspect_hint(self._trigger) else "resource_status_signal"
        return f"{reason_prefix}: inspect events and conditions for {suspect}"

    def _has_alert_signal(self, index: ObservationIndex) -> bool:
        related = self._trigger.related_context or {}
        return bool(related.get("cloudopsbench_alert") or related.get("alerts") or "alert" in index.haystack)

    def _alerts_args(self, _index: ObservationIndex) -> dict[str, Any]:
        return {"namespace": self._namespace}

    def _alerts_reason(self, _index: ObservationIndex) -> str:
        return "alert_signal: inspect active alert context"

    def _should_list_deployments(self, index: ObservationIndex) -> bool:
        if not _resource_type_called(index, "pods") or _resource_type_called(index, "deployments"):
            return False
        if self._discovered_suspect(index):
            return False
        return _has_availability_signal(self._trigger, index)

    def _deployment_inventory_args(self, _index: ObservationIndex) -> dict[str, Any]:
        return {"resource_type": "deployments", "namespace": self._namespace}

    def _deployment_inventory_reason(self, _index: ObservationIndex) -> str:
        return "availability_signal: inspect deployment readiness when pods do not expose a suspect"

    def _has_image_or_config_signal(self, index: ObservationIndex) -> bool:
        return self._has_suspect(index) and index.contains_any(
            (
                "imagepullbackoff",
                "errimagepull",
                "invalid image",
                "manifest unknown",
                "createcontainerconfigerror",
                "configmap",
                "secret",
                "readiness:",
                "liveness:",
                "readiness probe failed",
                "liveness probe failed",
            )
        )

    def _app_yaml_args(self, index: ObservationIndex) -> dict[str, Any]:
        return {"app_name": _workload_name(self._effective_suspect(index) or ""), "namespace": self._namespace}

    def _app_yaml_reason(self, index: ObservationIndex) -> str:
        return f"image_or_config_signal: inspect deployment spec for {_workload_name(self._effective_suspect(index) or '') or 'suspect'}"

    def _has_runtime_failure_signal(self, index: ObservationIndex) -> bool:
        return self._has_suspect(index) and index.contains_any(
            ("crashloopbackoff", "back-off", "exception", "stacktrace", "traceback", "panic", "error", "timeout")
        )

    def _error_logs_args(self, index: ObservationIndex) -> dict[str, Any]:
        return {"resource_type": "pods", "name": self._effective_suspect(index) or "", "namespace": self._namespace}

    def _error_logs_reason(self, index: ObservationIndex) -> str:
        return f"runtime_failure_signal: inspect error logs for {self._effective_suspect(index) or 'suspect'}"

    def _has_network_or_service_signal(self, index: ObservationIndex) -> bool:
        return self._has_suspect(index) and index.contains_any(
            ("no endpoints", "targetport", "connection refused", "dns", "no such host", "name resolution")
        )

    def _connectivity_args(self, index: ObservationIndex) -> dict[str, Any]:
        return {"resource_type": "services", "name": _workload_name(self._effective_suspect(index) or ""), "namespace": self._namespace}

    def _connectivity_reason(self, index: ObservationIndex) -> str:
        return f"network_or_service_signal: verify service connectivity for {_workload_name(self._effective_suspect(index) or '') or 'suspect'}"

    def _has_scheduling_signal(self, index: ObservationIndex) -> bool:
        return self._has_suspect(index) and index.contains_any(
            ("0/", "unschedulable", "taint", "affinity", "insufficient", "node")
        )

    def _cluster_config_args(self, _index: ObservationIndex) -> dict[str, Any]:
        return {"namespace": self._namespace}

    def _cluster_config_reason(self, _index: ObservationIndex) -> str:
        return "scheduling_signal: inspect cluster and node configuration"

    def _has_event_signal(self, index: ObservationIndex) -> bool:
        return self._has_suspect(index) and index.contains_any(("warning", "failed", "event"))

    def _recent_logs_args(self, index: ObservationIndex) -> dict[str, Any]:
        return {"resource_type": "pods", "name": self._effective_suspect(index) or "", "namespace": self._namespace}

    def _recent_logs_reason(self, index: ObservationIndex) -> str:
        return f"event_signal: inspect recent logs for {self._effective_suspect(index) or 'suspect'}"

    def _has_suspect(self, index: ObservationIndex) -> bool:
        return bool(self._effective_suspect(index))

    def _effective_suspect(self, index: ObservationIndex) -> str | None:
        return (
            self._discovered_suspect(index)
            or (
                _suspect_resource_hint(self._trigger)
                if _has_probeable_trigger_or_observed_signal(self._trigger, index)
                else None
            )
            or None
        )

    def _discovered_suspect(self, index: ObservationIndex) -> str | None:
        return _discover_suspect_resource(
            index.output_for("GetResources"),
            include_restarts=_has_restart_query(self._trigger),
        )


class CloudOpsLoopPlanner:
    """Compatibility wrapper around ``NativeProbeSelector``."""

    domain: str = CLOUDOPS_DOMAIN

    def __init__(self, trigger: Trigger) -> None:
        self._selector = NativeProbeSelector(CloudOpsRulePack(trigger))

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        return self._selector.plan(state=state, trigger_context=trigger_context)


def _discover_suspect_resource(text: str | None, *, include_restarts: bool = False) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        match = _RESOURCE_LINE_RE.match(line)
        if not match:
            continue
        name, ready, desired, status, restarts = match.groups()
        unhealthy_status = status.lower() not in {"running", "completed", "succeeded"}
        below_ready = int(ready) < int(desired)
        recently_restarted = include_restarts and int(restarts or 0) > 0
        if unhealthy_status or below_ready or recently_restarted:
            return _strip_replicaset_suffix(name)
    return None


def _strip_replicaset_suffix(name: str) -> str:
    parts = name.split("-")
    while parts and len(parts) > 1 and _HEX_SUFFIX_RE.fullmatch(parts[-1]):
        parts.pop()
    return "-".join(parts) if parts else name


def _workload_name(name: str) -> str:
    """Best-effort Kubernetes workload name from a pod/ReplicaSet name."""

    parts = [part for part in str(name or "").split("-") if part]
    if len(parts) >= 3 and _looks_like_replicaset_hash(parts[-2]) and _looks_like_pod_suffix(parts[-1]):
        return "-".join(parts[:-2])
    if len(parts) >= 2 and _looks_like_replicaset_hash(parts[-1]):
        return "-".join(parts[:-1])
    return _strip_replicaset_suffix(name)


def _looks_like_replicaset_hash(value: str) -> bool:
    return len(value) >= 8 and value.isalnum() and any(ch.isdigit() for ch in value)


def _looks_like_pod_suffix(value: str) -> bool:
    return 4 <= len(value) <= 6 and value.isalnum() and any(ch.isdigit() for ch in value)


def _suspect_resource_hint(trigger: Trigger) -> str:
    related = trigger.related_context or {}
    for key in ("cloudopsbench_fault_object", "fault_object", "deployment_name", "suspect_resource"):
        value = related.get(key)
        if isinstance(value, str) and value:
            return value.rsplit("/", 1)[-1]
    return trigger.service or ""


def _has_probeable_trigger_or_observed_signal(trigger: Trigger, index: ObservationIndex) -> bool:
    return _has_explicit_suspect_hint(trigger) or _has_resource_status_signal(index)


def _has_explicit_suspect_hint(trigger: Trigger) -> bool:
    related = trigger.related_context or {}
    return any(
        isinstance(related.get(key), str) and related.get(key)
        for key in ("cloudopsbench_fault_object", "fault_object", "deployment_name", "suspect_resource")
    )


def _has_restart_query(trigger: Trigger) -> bool:
    endpoint = str(getattr(trigger, "endpoint", "") or "").lower()
    related = trigger.related_context or {}
    query = str(related.get("cloudopsbench_query") or related.get("query") or "").lower()
    return "restart" in endpoint or "restart" in query


def _has_availability_signal(trigger: Trigger, index: ObservationIndex) -> bool:
    endpoint = str(getattr(trigger, "endpoint", "") or "").lower()
    related = trigger.related_context or {}
    query = str(related.get("cloudopsbench_query") or related.get("query") or "").lower()
    haystack = index.haystack
    return any(
        signal in f"{endpoint}\n{query}\n{haystack}"
        for signal in ("availability", "unreachability", "service unavailable", "503 server error")
    )


def _resource_type_called(index: ObservationIndex, resource_type: str) -> bool:
    expected = _singular_resource_type(resource_type)
    for call in index.state.tool_calls:
        if call.tool_name != "GetResources":
            continue
        called = _singular_resource_type(str(call.args.get("resource_type") or ""))
        if called == expected:
            return True
    return False


def _singular_resource_type(value: str) -> str:
    return value[:-1] if value.endswith("s") else value


def _has_resource_status_signal(index: ObservationIndex) -> bool:
    return index.contains_any(
        (
            "0/",
            "imagepullbackoff",
            "errimagepull",
            "crashloopbackoff",
            "createcontainerconfigerror",
            "pending",
            "unschedulable",
            "no endpoints",
            "failed",
            "warning",
        )
    )


def _trigger_namespace(trigger: Trigger) -> str | None:
    related = trigger.related_context or {}
    namespace = related.get("cloudopsbench_namespace") or related.get("namespace")
    return str(namespace) if namespace else None


def _summarize_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:_OUTPUT_SUMMARY_LIMIT]
    if isinstance(value, dict):
        if "error" in value and len(value) == 1:
            return f"error: {value['error']}"
        return _flatten_json(value)[:_OUTPUT_SUMMARY_LIMIT]
    if isinstance(value, list):
        return _flatten_json(value)[:_OUTPUT_SUMMARY_LIMIT]
    return str(value)[:_OUTPUT_SUMMARY_LIMIT]


def _flatten_json(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key}={_flatten_json(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_json(item) for item in value)
    return str(value)


def _arg_summary(args: dict[str, Any]) -> str:
    if not args:
        return ""
    return ",".join(f"{key}={value}" for key, value in args.items() if value)


def is_cloudops_planner(planner: LoopPlanner) -> bool:
    return getattr(planner, "domain", "") == CLOUDOPS_DOMAIN
