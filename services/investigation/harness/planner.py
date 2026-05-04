"""Planner Protocol — the brain the harness loop asks for next calls.

A planner is the only domain-specific thing in the harness: it inspects
``InvestigationLoopState`` (and any domain-shaped trigger context) and
returns a ``LoopDecision`` describing which tools to invoke next, or
that the loop should stop. Everything else — registry, critic, loop
orchestration, artifact emission — is shared.

Planners must be pure with respect to ``state``: read it, do not
mutate it. The loop owns mutation through ``state.record``. Planners
are free to maintain their own scratch state (e.g. a discovered
suspect resource) as private attributes between calls.
"""

from __future__ import annotations

from typing import Any, Protocol

from .contracts import InvestigationLoopState, LoopDecision


class LoopPlanner(Protocol):
    """Picks the next tool calls for one harness iteration."""

    @property
    def domain(self) -> str: ...

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision: ...
