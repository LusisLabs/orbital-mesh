"""Harness contracts: tools, calls, results, loop state.

Why these are separate dataclasses (not just dicts):

* The investigation stage already has a contract layer
  (``InvestigationProbeResult`` etc.). Mirroring the shape with frozen
  dataclasses lets the loop produce dict payloads at the boundary while
  keeping internal state strongly typed.
* ``ToolDefinition`` carries metadata the critic needs to reject calls
  early (mutation class, args schema, budget cost) without invoking the
  tool. Putting this on the dataclass — not in a side table — keeps a
  single source of truth.
* ``InvestigationLoopState`` is mutable on purpose. A planner reads it,
  the loop appends call/result pairs to it, and downstream stages read
  the final snapshot. A frozen state would either force planners to
  thread an updated copy through every step or live behind a builder —
  both heavier than this design needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


MutationClass = Literal["read_only", "soft_mutation", "hard_mutation"]
LoopAction = Literal["continue", "stop"]
ToolStatus = Literal["completed", "failed", "rejected", "skipped"]
RedactionStatus = Literal["clean", "partial", "redacted"]


@dataclass(frozen=True)
class ToolDefinition:
    """Static metadata about a registered diagnostic tool.

    The harness uses ``mutation_class`` to keep the loop read-only by
    default; mutating tools must go through policy/evaluation, never
    through the investigation registry. ``budget_cost`` lets a planner
    weight expensive tools (network calls, large log scans) against
    cheaper local lookups when the budget is tight.
    """

    name: str
    domain: str
    description: str
    args_schema: dict[str, Any]
    mutation_class: MutationClass = "read_only"
    timeout_seconds: float = 5.0
    budget_cost: float = 1.0
    policy_gate: str | None = None
    citations_kind: str | None = None
    redaction_status: RedactionStatus = "clean"
    credential_policy: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.domain}:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "qualified_name": self.qualified_name,
            "description": self.description,
            "args_schema": self.args_schema,
            "mutation_class": self.mutation_class,
            "timeout_seconds": self.timeout_seconds,
            "budget_cost": self.budget_cost,
            "policy_gate": self.policy_gate,
            "citations_kind": self.citations_kind,
            "redaction_status": self.redaction_status,
            "credential_policy": dict(self.credential_policy),
        }


@dataclass(frozen=True)
class ToolCall:
    """One requested invocation of a tool. Immutable record of intent."""

    call_id: str
    tool_name: str
    domain: str
    args: dict[str, Any]
    requested_at: str
    purpose: str = ""

    @property
    def qualified_name(self) -> str:
        return f"{self.domain}:{self.tool_name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "domain": self.domain,
            "qualified_name": self.qualified_name,
            "args": self.args,
            "requested_at": self.requested_at,
            "purpose": self.purpose,
        }


@dataclass(frozen=True)
class ToolResult:
    """The outcome of a ``ToolCall``: status, summary, citations, error."""

    call_id: str
    tool_name: str
    domain: str
    status: ToolStatus
    valid: bool
    output_summary: str
    citations: list[dict[str, Any]]
    redaction_status: RedactionStatus
    started_at: str
    completed_at: str
    latency_ms: float
    error: str | None = None
    output: Any = None

    @property
    def qualified_name(self) -> str:
        return f"{self.domain}:{self.tool_name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "domain": self.domain,
            "qualified_name": self.qualified_name,
            "status": self.status,
            "valid": self.valid,
            "output_summary": self.output_summary,
            "citations": list(self.citations),
            "redaction_status": self.redaction_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class LoopRejection:
    """Why the critic refused to forward a planned call."""

    call_id: str
    qualified_name: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "qualified_name": self.qualified_name,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class InvestigationLoopState:
    """Mutable per-trigger loop state.

    Planners read this to decide the next set of calls; the loop appends
    to it after each execution; downstream stages serialize the final
    snapshot as the ``investigation_loop`` artifact.
    """

    trigger_id: str
    iteration: int = 0
    budget_remaining: float = 6.0
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    observed_text: list[str] = field(default_factory=list)
    ranked_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[LoopRejection] = field(default_factory=list)
    planner_decisions: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None

    def record(self, call: ToolCall, result: ToolResult, *, observed: str | None = None) -> None:
        self.tool_calls.append(call)
        self.tool_results.append(result)
        if observed:
            self.observed_text.append(observed)
        if result.output_summary:
            self.observed_text.append(result.output_summary)

    def call_signatures(self) -> set[tuple[str, str, str]]:
        """Set of ``(domain, name, args-hash)`` keys already invoked."""
        return {(c.domain, c.tool_name, _stable_args_signature(c.args)) for c in self.tool_calls}

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "iteration": self.iteration,
            "budget_remaining": self.budget_remaining,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "tool_results": [result.to_dict() for result in self.tool_results],
            "ranked_hypotheses": list(self.ranked_hypotheses),
            "rejections": [rejection.to_dict() for rejection in self.rejections],
            "planner_decisions": list(self.planner_decisions),
            "stop_reason": self.stop_reason,
        }


@dataclass(frozen=True)
class LoopDecision:
    """Planner output for one iteration of the harness loop."""

    action: LoopAction
    next_calls: tuple[ToolCall, ...] = ()
    reason: str = ""
    confidence: float = 0.0
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "next_calls": [call.to_dict() for call in self.next_calls],
            "reason": self.reason,
            "confidence": self.confidence,
            "debug": dict(self.debug),
        }


def _stable_args_signature(args: dict[str, Any]) -> str:
    """Return a stable hashable signature for a call's args.

    Used by the critic to detect duplicate calls (same tool, same args).
    Sorting keys keeps the signature deterministic across dict ordering.
    """
    return ",".join(f"{key}={args[key]}" for key in sorted(args)) if args else ""
