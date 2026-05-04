"""Generic investigation loop orchestrator.

``run_investigation_loop`` is the only piece of harness machinery that
holds policy: it caps iterations, enforces budget, runs the critic
between planner and registry, and converts a planner's "stop" decision
into a final ``stop_reason`` on the state.

Stop conditions, in order of precedence:

* Planner returns ``action="stop"``.
* Critic rejects every call in a non-empty decision.
* ``state.budget_remaining`` is exhausted.
* Iteration cap reached (defensive).
"""

from __future__ import annotations

from typing import Any

from .contracts import InvestigationLoopState
from .critic import LoopCritic
from .planner import LoopPlanner
from .registry import ToolRegistry


def run_investigation_loop(
    *,
    state: InvestigationLoopState,
    planner: LoopPlanner,
    registry: ToolRegistry,
    critic: LoopCritic,
    trigger_context: dict[str, Any] | None = None,
    max_iterations: int = 8,
) -> InvestigationLoopState:
    """Drive the loop until a stop condition fires; return the final state."""

    context = dict(trigger_context or {})
    while state.iteration < max_iterations:
        if state.budget_remaining <= 0:
            state.stop_reason = "budget_exhausted"
            break
        decision = planner.plan(state=state, trigger_context=context)
        if decision.action == "stop":
            state.stop_reason = decision.reason or "planner_requested_stop"
            break
        filtered, rejections = critic.review(state, decision)
        state.rejections.extend(rejections)
        if filtered.action == "stop":
            state.stop_reason = filtered.reason or "critic_rejected_all_calls"
            break
        if not filtered.next_calls:
            state.stop_reason = "planner_returned_no_calls"
            break
        for call in filtered.next_calls:
            entry = registry.get(call.domain, call.tool_name)
            cost = entry[0].budget_cost if entry is not None else 1.0
            result = registry.invoke(call)
            state.record(call, result)
            state.budget_remaining = max(0.0, state.budget_remaining - cost)
            if state.budget_remaining <= 0:
                break
        state.iteration += 1
    if state.stop_reason is None:
        state.stop_reason = "iteration_cap_reached"
    return state
