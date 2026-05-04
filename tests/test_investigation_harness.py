"""Tests for the generic investigation harness.

These cover the harness primitives in isolation (contracts, registry,
critic, loop), then the two domain ports (CloudOps re-running through
the registry produces equivalent behavior; Reth peer-starvation drives
end-to-end on a synthetic snapshot).
"""

from __future__ import annotations

import unittest
from typing import Any

from services.investigation.harness import (
    InvestigationLoopState,
    LoopCritic,
    LoopDecision,
    RawToolOutput,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    make_call,
    run_investigation_loop,
)
from services.investigation.harness.critic import _validate_args


class HarnessRegistryTests(unittest.TestCase):
    def test_register_and_get_returns_pair(self) -> None:
        registry = ToolRegistry()
        defn = _ro_def("get_x", "demo")
        registry.register(defn, lambda args: RawToolOutput(output_summary="x"))
        entry = registry.get("demo", "get_x")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry[0].name, "get_x")

    def test_register_duplicate_raises(self) -> None:
        registry = ToolRegistry()
        defn = _ro_def("get_x", "demo")
        registry.register(defn, lambda args: RawToolOutput())
        with self.assertRaises(ValueError):
            registry.register(defn, lambda args: RawToolOutput())

    def test_list_filters_by_domain_and_mutation_class(self) -> None:
        registry = ToolRegistry()
        registry.register(_ro_def("a", "demo"), lambda args: RawToolOutput())
        registry.register(_ro_def("b", "demo"), lambda args: RawToolOutput())
        registry.register(_mut_def("dangerous", "demo"), lambda args: RawToolOutput())
        registry.register(_ro_def("a", "other"), lambda args: RawToolOutput())
        read_only_demo = {d.qualified_name for d in registry.list_definitions(domain="demo", mutation_class="read_only")}
        self.assertEqual(read_only_demo, {"demo:a", "demo:b"})

    def test_invoke_failure_returns_failed_result_not_exception(self) -> None:
        registry = ToolRegistry()
        defn = _ro_def("boom", "demo")

        def raises(_args: dict[str, Any]) -> RawToolOutput:
            raise RuntimeError("kaboom")

        registry.register(defn, raises)
        call = make_call(tool=defn, args={})
        result = registry.invoke(call)
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.valid)
        self.assertIn("kaboom", result.error or "")

    def test_invoke_unknown_tool_returns_rejected_result(self) -> None:
        registry = ToolRegistry()
        call = ToolCall(call_id="c1", tool_name="missing", domain="demo", args={}, requested_at="2026-05-04T00:00:00Z")
        result = registry.invoke(call)
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.valid)


class CriticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.read = _ro_def("get_x", "demo", args_schema={"name": {"type": "str", "required": True}})
        self.mutate = _mut_def("drop", "demo")
        self.registry.register(self.read, lambda args: RawToolOutput())
        self.registry.register(self.mutate, lambda args: RawToolOutput())
        self.critic = LoopCritic(self.registry)

    def test_rejects_mutating_calls_unless_allowed(self) -> None:
        decision = LoopDecision(action="continue", next_calls=(make_call(tool=self.mutate),))
        filtered, rejections = self.critic.review(InvestigationLoopState(trigger_id="t"), decision)
        self.assertEqual(filtered.next_calls, ())
        self.assertEqual(rejections[0].reason, "mutation_class_not_allowed")

    def test_rejects_unknown_tools(self) -> None:
        unknown = ToolCall(call_id="c", tool_name="nope", domain="demo", args={"name": "x"}, requested_at="now")
        filtered, rejections = self.critic.review(
            InvestigationLoopState(trigger_id="t"),
            LoopDecision(action="continue", next_calls=(unknown,)),
        )
        self.assertEqual(rejections[0].reason, "tool_not_registered")
        self.assertEqual(filtered.action, "stop")

    def test_rejects_duplicate_calls(self) -> None:
        state = InvestigationLoopState(trigger_id="t")
        first = make_call(tool=self.read, args={"name": "x"})
        result = self.registry.invoke(first)
        state.record(first, result)
        second = make_call(tool=self.read, args={"name": "x"})
        filtered, rejections = self.critic.review(state, LoopDecision(action="continue", next_calls=(second,)))
        self.assertEqual(rejections[0].reason, "duplicate_call")
        self.assertEqual(filtered.action, "stop")

    def test_validates_arg_types(self) -> None:
        bad = make_call(tool=self.read, args={"name": 99})
        filtered, rejections = self.critic.review(InvestigationLoopState(trigger_id="t"), LoopDecision(action="continue", next_calls=(bad,)))
        self.assertEqual(rejections[0].reason, "invalid_args")
        self.assertEqual(filtered.action, "stop")

    def test_validates_required_args(self) -> None:
        violations = _validate_args({}, {"name": {"type": "str", "required": True}})
        self.assertTrue(any("missing required arg" in v for v in violations))


class HarnessLoopTests(unittest.TestCase):
    def test_loop_drives_planner_and_records_calls_until_stop(self) -> None:
        registry = ToolRegistry()
        defs = [_ro_def(f"step_{i}", "demo") for i in range(3)]
        for defn in defs:
            registry.register(defn, _make_static_invoker(f"output_{defn.name}"))
        critic = LoopCritic(registry)

        class StepwisePlanner:
            domain = "demo"

            def plan(self, *, state: InvestigationLoopState, trigger_context: dict[str, Any]) -> LoopDecision:
                next_index = len(state.tool_calls)
                if next_index >= len(defs):
                    return LoopDecision(action="stop", reason="done", confidence=0.9)
                return LoopDecision(
                    action="continue",
                    next_calls=(make_call(tool=defs[next_index]),),
                    reason="next_step",
                    confidence=0.5,
                )

        state = InvestigationLoopState(trigger_id="t", budget_remaining=5.0)
        run_investigation_loop(
            state=state,
            planner=StepwisePlanner(),
            registry=registry,
            critic=critic,
            max_iterations=10,
        )
        self.assertEqual([c.tool_name for c in state.tool_calls], ["step_0", "step_1", "step_2"])
        self.assertEqual(state.stop_reason, "done")

    def test_loop_stops_on_budget_exhaustion(self) -> None:
        registry = ToolRegistry()
        defn = _ro_def("expensive", "demo", budget_cost=2.0)
        registry.register(defn, _make_static_invoker("ok"))
        critic = LoopCritic(registry)

        class GreedyPlanner:
            domain = "demo"
            calls = 0

            def plan(self, *, state: InvestigationLoopState, trigger_context: dict[str, Any]) -> LoopDecision:
                self.calls += 1
                # Need to vary args because critic deduplicates by signature
                return LoopDecision(
                    action="continue",
                    next_calls=(make_call(tool=defn, args={"i": str(self.calls)}),),
                    reason="more",
                    confidence=0.5,
                )

        state = InvestigationLoopState(trigger_id="t", budget_remaining=3.0)
        run_investigation_loop(
            state=state,
            planner=GreedyPlanner(),
            registry=registry,
            critic=critic,
            max_iterations=20,
        )
        # Two calls cost 4.0; budget is 3.0 → stops after second call
        self.assertEqual(len(state.tool_calls), 2)
        self.assertEqual(state.stop_reason, "budget_exhausted")


class RethPeerStarvationPortTests(unittest.TestCase):
    def test_planner_branches_on_peer_count_and_stops_after_logs(self) -> None:
        from services.investigation.reth_tools import register_reth_tools, RethLoopPlanner

        signal = {
            "execution": {"peer_count": 0, "min_peer_count": 1, "syncing": True, "block_lag": 7},
            "consensus": {"engine_api_reachable": False, "client_kind": "lighthouse", "client_healthy": False},
            "logs": {"error_signatures": ["consensus_disconnected"], "recent_errors": ["engine_api timeout"]},
            "rpc": {"http_reachable": True},
        }
        registry = ToolRegistry()
        register_reth_tools(registry, signal)
        critic = LoopCritic(registry)
        state = InvestigationLoopState(trigger_id="trg_reth", budget_remaining=4.0)

        run_investigation_loop(
            state=state,
            planner=RethLoopPlanner(peer_floor=1),
            registry=registry,
            critic=critic,
            max_iterations=6,
        )

        names = [call.tool_name for call in state.tool_calls]
        self.assertEqual(names, ["read_peer_sync", "read_consensus_status", "read_recent_logs"])
        self.assertTrue(state.stop_reason and state.stop_reason.startswith("reth_peer_starvation"))
        # The consensus probe carries engine_api_reachable=False — observable
        # in the loop's observed_text for downstream hypothesis ranking.
        joined = "\n".join(state.observed_text).lower()
        self.assertIn("engine_api_reachable=false", joined)


def _ro_def(name: str, domain: str, *, args_schema: dict[str, Any] | None = None, budget_cost: float = 1.0) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=domain,
        description=f"read-only {name}",
        args_schema=dict(args_schema or {}),
        mutation_class="read_only",
        budget_cost=budget_cost,
    )


def _mut_def(name: str, domain: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=domain,
        description=f"mutating {name}",
        args_schema={},
        mutation_class="hard_mutation",
    )


def _make_static_invoker(value: str):
    def invoke(_args: dict[str, Any]) -> RawToolOutput:
        return RawToolOutput(output=value, output_summary=value, valid=True)

    return invoke


if __name__ == "__main__":
    unittest.main()
