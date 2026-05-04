"""Domain-scoped registry for investigation tools.

The registry is intentionally small: it holds ``(definition, fn)`` pairs
keyed by ``(domain, name)`` and exposes ``register``, ``get``, ``list``,
and ``invoke``. Listing supports filtering by domain and by mutation
class so the loop can produce only read-only candidates without ever
seeing mutating tools.

``invoke`` records timing, normalizes errors, and produces a
``ToolResult`` from the tool's raw return — the underlying tool function
returns a small ``RawToolOutput`` that lets the registry capture both
the output and any tool-supplied citations/redaction state without
forcing every tool to know the harness contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .contracts import (
    RedactionStatus,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolStatus,
)


@dataclass(frozen=True)
class RawToolOutput:
    """Lightweight return shape for tool implementations.

    A tool's function returns this; the registry converts it into a
    ``ToolResult`` so per-tool code stays focused on data, not contract
    plumbing. ``valid=False`` means the tool ran but produced no useful
    data (e.g. snapshot cache miss); ``status="failed"`` is reserved
    for exceptions.
    """

    output: Any = None
    output_summary: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    valid: bool = True
    redaction_status: RedactionStatus = "clean"
    status: ToolStatus = "completed"
    error: str | None = None


ToolFn = Callable[[dict[str, Any]], RawToolOutput]


class ToolRegistry:
    """Domain-scoped registry of ``ToolDefinition``s.

    Domain + name is the qualified key (``cloudops:GetResources``). The
    same canonical ``name`` may exist in multiple domains; that's fine
    because the loop always passes a domain when it invokes.
    """

    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], tuple[ToolDefinition, ToolFn]] = {}

    def register(self, definition: ToolDefinition, fn: ToolFn) -> None:
        key = (definition.domain, definition.name)
        if key in self._tools:
            raise ValueError(f"tool {definition.qualified_name} already registered")
        self._tools[key] = (definition, fn)

    def get(self, domain: str, name: str) -> tuple[ToolDefinition, ToolFn] | None:
        return self._tools.get((domain, name))

    def has(self, domain: str, name: str) -> bool:
        return (domain, name) in self._tools

    def list_definitions(
        self,
        *,
        domain: str | None = None,
        mutation_class: str | None = None,
    ) -> list[ToolDefinition]:
        results: list[ToolDefinition] = []
        for (entry_domain, _), (definition, _) in self._tools.items():
            if domain is not None and entry_domain != domain:
                continue
            if mutation_class is not None and definition.mutation_class != mutation_class:
                continue
            results.append(definition)
        return results

    def domains(self) -> tuple[str, ...]:
        return tuple(sorted({domain for domain, _ in self._tools}))

    def invoke(self, call: ToolCall) -> ToolResult:
        """Execute a planned call and return a fully-formed ``ToolResult``.

        The registry never throws for missing tools or runtime errors —
        all failure modes turn into a ``ToolResult`` so the loop and the
        downstream artifact format are uniform.
        """
        started_at = _iso_now()
        start = time.monotonic()
        entry = self.get(call.domain, call.tool_name)
        if entry is None:
            return _failure_result(
                call,
                started_at=started_at,
                latency_ms=0.0,
                status="rejected",
                error=f"tool {call.qualified_name} not registered",
            )
        _, fn = entry
        try:
            raw = fn(call.args)
            if not isinstance(raw, RawToolOutput):
                raise TypeError(
                    f"tool {call.qualified_name} returned {type(raw).__name__}, expected RawToolOutput"
                )
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                domain=call.domain,
                status=raw.status,
                valid=raw.valid,
                output_summary=raw.output_summary,
                citations=list(raw.citations),
                redaction_status=raw.redaction_status,
                started_at=started_at,
                completed_at=_iso_now(),
                latency_ms=round((time.monotonic() - start) * 1000.0, 3),
                error=raw.error,
                output=raw.output,
            )
        except Exception as exc:
            return _failure_result(
                call,
                started_at=started_at,
                latency_ms=round((time.monotonic() - start) * 1000.0, 3),
                status="failed",
                error=str(exc),
            )


def make_call(
    *,
    tool: ToolDefinition,
    args: dict[str, Any] | None = None,
    purpose: str = "",
) -> ToolCall:
    """Convenience constructor for planners that only know a definition."""
    return ToolCall(
        call_id=f"call_{uuid4().hex[:10]}",
        tool_name=tool.name,
        domain=tool.domain,
        args=dict(args or {}),
        requested_at=_iso_now(),
        purpose=purpose,
    )


def _failure_result(
    call: ToolCall,
    *,
    started_at: str,
    latency_ms: float,
    status: ToolStatus,
    error: str,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        domain=call.domain,
        status=status,
        valid=False,
        output_summary="",
        citations=[],
        redaction_status="clean",
        started_at=started_at,
        completed_at=_iso_now(),
        latency_ms=latency_ms,
        error=error,
    )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
