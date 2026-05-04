"""CloudOpsBench domain pack for the investigation harness.

This module is the first proof that the harness contracts generalize:

* ``register_cloudops_tools(registry, snapshot_tools)`` registers the
  eight Cloud-OpsBench diagnostic tools as ``ToolDefinition``s, all
  read-only, all backed by the snapshot tool cache.
* ``CloudOpsLoopPlanner`` is the planner that decides which tool to
  call next. It mirrors the prior bespoke loop in ``service.py``: start
  with ``GetResources``, observe the inventory, pick the unhealthy pod,
  follow up with ``DescribeResource`` / ``GetAppYAML`` / ``GetErrorLogs``
  on it, optionally ``GetAlerts`` if the trigger carries alert metadata.

Behavior is intended to match the prior bespoke loop bit-for-bit so the
benchmark numbers don't move in this phase. The point of the rewrite is
the shape: domain logic now lives in a planner that the harness drives.
"""

from __future__ import annotations

import re
from typing import Any

from shared.mesh_runtime import Trigger

from .harness import (
    InvestigationLoopState,
    LoopDecision,
    LoopPlanner,
    RawToolOutput,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    make_call,
)


_RESOURCE_LINE_RE = re.compile(
    r"^\s*([a-z][a-z0-9-]+(?:-[a-f0-9]+)?)\s+(\d+)/(\d+)\s+([A-Za-z]+)\b"
)
_HEX_SUFFIX_RE = re.compile(r"[a-f0-9]{4,}")

CLOUDOPS_DOMAIN = "cloudops"


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
    """
    for definition in CLOUDOPS_TOOL_DEFINITIONS:
        registry.register(definition, _make_cloudops_invoker(definition.name, snapshot_tools))


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


class CloudOpsLoopPlanner:
    """Planner that mirrors the prior bespoke CloudOps loop.

    Sequence (one planned call per iteration):

    1. ``GetResources`` (always, with the trigger namespace).
    2. After observing 1's output, pick the unhealthy resource name.
       Use the trigger hint if the inventory looks healthy.
    3. ``DescribeResource`` on the suspect.
    4. ``GetAppYAML`` for the suspect.
    5. ``GetErrorLogs`` for the suspect.
    6. ``GetAlerts`` if the trigger carries alert metadata.
    7. Stop.
    """

    domain: str = CLOUDOPS_DOMAIN

    def __init__(self, trigger: Trigger) -> None:
        self._trigger = trigger
        self._suspect: str | None = None
        self._namespace = _trigger_namespace(trigger)

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        called_tool_names = [call.tool_name for call in state.tool_calls]
        if "GetResources" not in called_tool_names:
            return _continue_with(_call("GetResources", {"resource_type": "pods", "namespace": self._namespace}))
        if self._suspect is None:
            self._suspect = (
                _discover_suspect_resource(_inventory_text(state))
                or _suspect_resource_hint(self._trigger)
                or None
            )
        suspect = self._suspect
        for next_tool, args in self._follow_up_plan(suspect):
            if next_tool not in called_tool_names:
                return _continue_with(_call(next_tool, args))
        if self._has_alert_metadata() and "GetAlerts" not in called_tool_names:
            return _continue_with(_call("GetAlerts", {"namespace": self._namespace}))
        return LoopDecision(action="stop", reason="cloudops_plan_complete", confidence=0.5)

    def _follow_up_plan(self, suspect: str | None) -> list[tuple[str, dict[str, Any]]]:
        if not suspect:
            return []
        return [
            ("DescribeResource", {"resource_type": "pods", "name": suspect, "namespace": self._namespace}),
            ("GetAppYAML", {"resource_type": "deployment", "name": suspect, "namespace": self._namespace}),
            ("GetErrorLogs", {"resource_type": "pods", "name": suspect, "namespace": self._namespace}),
        ]

    def _has_alert_metadata(self) -> bool:
        related = self._trigger.related_context or {}
        return bool(related.get("cloudopsbench_alert") or related.get("alerts"))


def _continue_with(call: ToolCall) -> LoopDecision:
    return LoopDecision(action="continue", next_calls=(call,), reason="cloudops_next_step", confidence=0.6)


def _call(name: str, args: dict[str, Any]) -> ToolCall:
    definition = next((d for d in CLOUDOPS_TOOL_DEFINITIONS if d.name == name), None)
    if definition is None:
        raise KeyError(f"cloudops tool {name} not in registry definitions")
    return make_call(tool=definition, args=args, purpose=f"cloudops:{name}")


def _inventory_text(state: InvestigationLoopState) -> str | None:
    for call, result in zip(state.tool_calls, state.tool_results):
        if call.tool_name == "GetResources":
            return result.output_summary
    return None


def _discover_suspect_resource(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        match = _RESOURCE_LINE_RE.match(line)
        if not match:
            continue
        name, ready, desired, status = match.groups()
        unhealthy_status = status.lower() not in {"running", "completed", "succeeded"}
        below_ready = int(ready) < int(desired)
        if unhealthy_status or below_ready:
            return _strip_replicaset_suffix(name)
    return None


def _strip_replicaset_suffix(name: str) -> str:
    parts = name.split("-")
    while parts and len(parts) > 1 and _HEX_SUFFIX_RE.fullmatch(parts[-1]):
        parts.pop()
    return "-".join(parts) if parts else name


def _suspect_resource_hint(trigger: Trigger) -> str:
    related = trigger.related_context or {}
    for key in ("cloudopsbench_fault_object", "fault_object", "deployment_name", "suspect_resource"):
        value = related.get(key)
        if isinstance(value, str) and value:
            return value.rsplit("/", 1)[-1]
    return trigger.service or ""


def _trigger_namespace(trigger: Trigger) -> str | None:
    related = trigger.related_context or {}
    namespace = related.get("cloudopsbench_namespace") or related.get("namespace")
    return str(namespace) if namespace else None


def _summarize_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, dict):
        if "error" in value and len(value) == 1:
            return f"error: {value['error']}"
        return _flatten_json(value)[:1000]
    if isinstance(value, list):
        return _flatten_json(value)[:1000]
    return str(value)[:1000]


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
