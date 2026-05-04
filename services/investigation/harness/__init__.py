"""Generic agent harness for the investigation stage.

The harness gives Mesh's investigation service a domain-agnostic tool
surface so the same loop machinery can drive Cloud-OpsBench RCA and Reth
node diagnostics without bespoke per-domain wiring. It is read-only by
default: the registry refuses to invoke any mutating tool, and the
critic filters out invalid or duplicate calls before they reach a tool.

Public surface:

* ``ToolDefinition``, ``ToolCall``, ``ToolResult`` — the contracts that
  describe a tool, an invocation, and its result.
* ``InvestigationLoopState``, ``LoopDecision`` — the per-loop state and
  the contract that planners return.
* ``ToolRegistry`` — domain-scoped registry of available tools.
* ``LoopCritic`` — pre-flight validator; rejects unknown tools, invalid
  args, duplicate calls, and mutating tools.
* ``LoopPlanner`` (Protocol) — the domain-specific brain the harness
  asks for the next set of calls.
"""

from __future__ import annotations

from .contracts import (
    InvestigationLoopState,
    LoopDecision,
    LoopRejection,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from .critic import LoopCritic
from .loop import run_investigation_loop
from .planner import LoopPlanner
from .registry import RawToolOutput, ToolRegistry, make_call

__all__ = [
    "InvestigationLoopState",
    "LoopCritic",
    "LoopDecision",
    "LoopPlanner",
    "LoopRejection",
    "RawToolOutput",
    "ToolCall",
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    "make_call",
    "run_investigation_loop",
]
