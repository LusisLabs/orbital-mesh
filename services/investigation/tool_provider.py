"""Read-only diagnostic tool providers for the investigation stage.

The investigation service is deliberately deterministic, but RCA benchmarks
expect the agent to *choose* probes against a live (or snapshotted) cluster.
This module defines the seam: ``InvestigationToolProvider`` lets a backend
inject a bounded read-only tool surface into ``InvestigationService``
without coupling the runtime to any specific benchmark.

A provider answers three questions:

* What tools are available? (``available_tools``)
* What does this tool return for these args? (``invoke``)
* What did I actually call? (``call_records``) — used to populate
  ``tool_trajectory`` so scoring can credit tool coverage.

``CloudOpsInvestigationToolProvider`` wraps the existing
``CloudOpsSnapshotTools`` so hidden-mode runs can answer benchmark tool
calls from the snapshot tool cache. It keeps the read-only contract: the
underlying snapshot is immutable and probes are limited to lookup.
"""

from __future__ import annotations

from typing import Any, Protocol


class InvestigationToolProvider(Protocol):
    """Read-only tool surface injected into ``InvestigationService``.

    Implementations MUST be side-effect free with respect to the operated
    system. Calls may mutate provider-internal state (call logs) but never
    the snapshot, cluster, or external service they read from.
    """

    @property
    def name(self) -> str: ...

    def available_tools(self) -> tuple[str, ...]: ...

    def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def call_records(self) -> list[dict[str, Any]]: ...


CLOUDOPS_DIAGNOSTIC_TOOLS: tuple[str, ...] = (
    "GetResources",
    "DescribeResource",
    "GetAppYAML",
    "GetErrorLogs",
    "GetAlerts",
    "CheckServiceConnectivity",
    "GetClusterConfiguration",
    "GetRecentLogs",
)


class CloudOpsInvestigationToolProvider:
    """Wrap ``CloudOpsSnapshotTools`` as an investigation tool provider.

    The provider records every call so the benchmark runner can hand the
    list back to the scoring path as ``tool_trajectory``. Outputs are
    summarized for the investigation report; the full payload remains in
    the underlying snapshot.
    """

    name: str = "cloudopsbench"

    def __init__(self, snapshot_tools: Any) -> None:
        self._tools = snapshot_tools

    def available_tools(self) -> tuple[str, ...]:
        return CLOUDOPS_DIAGNOSTIC_TOOLS

    def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        call_args = dict(args or {})
        output = self._tools.invoke(tool_name, call_args)
        last = self._tools.calls[-1] if self._tools.calls else None
        valid = bool(last.valid) if last is not None else False
        status = str(last.status) if last is not None else "unknown"
        return {
            "tool_name": tool_name,
            "args": call_args,
            "output": output,
            "valid": valid,
            "status": status,
        }

    def call_records(self) -> list[dict[str, Any]]:
        return [call.to_dict() for call in self._tools.calls]
