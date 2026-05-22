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
* ``ProbeRule``, ``ObservationIndex``, ``NativeProbeSelector`` — the
  shared native selector substrate used by domain rule packs.
* ``LlmProbeSelector``, ``ShadowProbeSelector`` — gated LLM and shadow
  selectors that use the same planner contract without taking default
  control.
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
from .native_selector import (
    GenericRulePack,
    LlmProbeSelector,
    NativeProbeSelector,
    ObservationIndex,
    ProbeRule,
    RootCauseCandidate,
    ShadowProbeSelector,
)
from .planner import LoopPlanner
from .registry import RawToolOutput, ToolRegistry, make_call
from .sandbox_bridge import invoke_sandbox_tool, sandbox_tool_manifest

__all__ = [
    "GenericRulePack",
    "InvestigationLoopState",
    "LoopCritic",
    "LoopDecision",
    "LoopPlanner",
    "LoopRejection",
    "LlmProbeSelector",
    "NativeProbeSelector",
    "ObservationIndex",
    "ProbeRule",
    "RawToolOutput",
    "RootCauseCandidate",
    "ShadowProbeSelector",
    "ToolCall",
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    "make_call",
    "invoke_sandbox_tool",
    "sandbox_tool_manifest",
    "run_investigation_loop",
]
