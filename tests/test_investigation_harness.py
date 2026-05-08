"""Tests for the generic investigation harness.

These cover the harness primitives in isolation (contracts, registry,
critic, loop), then the two domain ports (CloudOps re-running through
the registry produces equivalent behavior; Reth peer-starvation drives
end-to-end on a synthetic snapshot).
"""

from __future__ import annotations

import unittest
from typing import Any

from shared.mesh_runtime import Trigger
from services.investigation.harness import (
    InvestigationLoopState,
    LoopCritic,
    LoopDecision,
    LlmProbeSelector,
    RawToolOutput,
    ShadowProbeSelector,
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

    def test_loop_stops_when_critic_rejects_duplicate_call(self) -> None:
        registry = ToolRegistry()
        defn = _ro_def("same", "demo")
        registry.register(defn, _make_static_invoker("ok"))
        critic = LoopCritic(registry)

        class DuplicatePlanner:
            domain = "demo"

            def plan(self, *, state: InvestigationLoopState, trigger_context: dict[str, Any]) -> LoopDecision:
                return LoopDecision(
                    action="continue",
                    next_calls=(make_call(tool=defn, args={"name": "fixed"}),),
                    reason="duplicate_probe",
                    confidence=0.5,
                )

        state = InvestigationLoopState(trigger_id="t", budget_remaining=5.0)
        run_investigation_loop(
            state=state,
            planner=DuplicatePlanner(),
            registry=registry,
            critic=critic,
            max_iterations=4,
        )

        self.assertEqual(len(state.tool_calls), 1)
        self.assertEqual(state.stop_reason, "critic_rejected_all_calls")
        self.assertEqual(state.rejections[0].reason, "duplicate_call")
        self.assertEqual(state.planner_decisions[-1]["rejections"][0]["reason"], "duplicate_call")
        self.assertEqual(state.planner_decisions[-1]["planned_calls"][0]["tool_name"], "same")


class CloudOpsNativeSelectorTests(unittest.TestCase):
    def test_selector_follows_observed_crashloop_signal_and_records_reasons(self) -> None:
        from services.investigation.tools.cloudops import CloudOpsLoopPlanner, register as register_cloudops_tools

        snapshot = _CloudOpsSnapshot(
            {
                "GetResources": "checkoutservice-7c9f-abc12 0/1 CrashLoopBackOff",
                "DescribeResource": "Warning BackOff back-off restarting failed container",
                "GetErrorLogs": "Traceback RuntimeError: checkout exception",
            }
        )
        registry = ToolRegistry()
        register_cloudops_tools(registry, snapshot)
        state = InvestigationLoopState(trigger_id="trg_cloudops", budget_remaining=6.0)

        run_investigation_loop(
            state=state,
            planner=CloudOpsLoopPlanner(_cloudops_trigger()),
            registry=registry,
            critic=LoopCritic(registry),
            max_iterations=6,
        )

        self.assertEqual([call.tool_name for call in state.tool_calls], ["GetResources", "DescribeResource", "GetErrorLogs"])
        self.assertIn("inventory_discovery", state.tool_calls[0].purpose)
        self.assertIn("resource_status_signal", state.tool_calls[1].purpose)
        self.assertIn("runtime_failure_signal", state.tool_calls[2].purpose)
        self.assertEqual(state.stop_reason, "root_cause_candidate_found")

    def test_selector_stops_when_evidence_value_is_exhausted(self) -> None:
        from services.investigation.tools.cloudops import CloudOpsLoopPlanner, register as register_cloudops_tools

        snapshot = _CloudOpsSnapshot({"GetResources": "frontend 1/1 Running"})
        registry = ToolRegistry()
        register_cloudops_tools(registry, snapshot)
        state = InvestigationLoopState(trigger_id="trg_cloudops", budget_remaining=6.0)

        run_investigation_loop(
            state=state,
            planner=CloudOpsLoopPlanner(_cloudops_trigger()),
            registry=registry,
            critic=LoopCritic(registry),
            max_iterations=6,
        )

        self.assertEqual([call.tool_name for call in state.tool_calls], ["GetResources"])
        self.assertEqual(state.stop_reason, "evidence_value_exhausted")

    def test_selector_stops_on_sufficient_rca_confidence(self) -> None:
        from services.investigation.tools.cloudops import CloudOpsLoopPlanner, register as register_cloudops_tools

        snapshot = _CloudOpsSnapshot(
            {
                "GetResources": "frontend 0/1 ImagePullBackOff",
                "DescribeResource": "Reason: ErrImagePull manifest unknown",
                "GetAppYAML": "image: frontend:missing",
            }
        )
        registry = ToolRegistry()
        register_cloudops_tools(registry, snapshot)
        state = InvestigationLoopState(trigger_id="trg_cloudops", budget_remaining=6.0)

        run_investigation_loop(
            state=state,
            planner=CloudOpsLoopPlanner(_cloudops_trigger()),
            registry=registry,
            critic=LoopCritic(registry),
            max_iterations=6,
        )

        self.assertEqual([call.tool_name for call in state.tool_calls], ["GetResources", "DescribeResource"])
        self.assertEqual(state.stop_reason, "root_cause_candidate_found")
        self.assertEqual(state.planner_decisions[-1]["debug"]["top_root_cause"]["root_cause"], "incorrect_image_reference")

    def test_llm_selector_is_gated_and_shadowed_behind_native_selector(self) -> None:
        from services.investigation.tools.cloudops import CloudOpsLoopPlanner, CloudOpsRulePack

        rule_pack = CloudOpsRulePack(_cloudops_trigger())
        disabled = LlmProbeSelector(rule_pack)
        disabled_decision = disabled.plan(state=InvestigationLoopState(trigger_id="trg"), trigger_context={})
        self.assertEqual(disabled_decision.action, "stop")
        self.assertEqual(disabled_decision.reason, "llm_selector_disabled")

        llm = LlmProbeSelector(
            rule_pack,
            enabled=True,
            decision_provider=lambda _context: {
                "action": "continue",
                "tool_name": "DescribeResource",
                "args": {"resource_type": "pods", "name": "shadow", "namespace": "default"},
                "reason": "shadow_llm_probe",
                "confidence": 0.42,
            },
        )
        shadowed = ShadowProbeSelector(primary=CloudOpsLoopPlanner(_cloudops_trigger()), shadow=llm)
        decision = shadowed.plan(state=InvestigationLoopState(trigger_id="trg"), trigger_context={})

        self.assertEqual(decision.next_calls[0].tool_name, "GetResources")
        self.assertEqual(decision.debug["shadow_decision"]["next_calls"][0]["tool_name"], "DescribeResource")
        self.assertEqual(decision.debug["shadow_decision"]["reason"], "shadow_llm_probe")


class RethPeerStarvationPortTests(unittest.TestCase):
    def test_planner_branches_on_peer_count_and_stops_after_logs(self) -> None:
        from services.investigation.tools.reth import register as register_reth_tools, RethLoopPlanner

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
        self.assertEqual(state.stop_reason, "evidence_value_exhausted")
        self.assertEqual(
            [call.purpose for call in state.tool_calls],
            ["reth_first_peer_check", "reth_peers_below_floor", "reth_corroborate_logs"],
        )
        # The consensus probe carries engine_api_reachable=False — observable
        # in the loop's observed_text for downstream hypothesis ranking.
        joined = "\n".join(state.observed_text).lower()
        self.assertIn("engine_api_reachable=false", joined)


class LlmProbeSelectorCrossDomainTests(unittest.TestCase):
    """LlmProbeSelector now sees every read-only tool the registry
    holds — its domain isn't a fence, it's a default. The LLM can pick
    a CloudOps snapshot tool, a Prometheus query, or a GitHub diff in
    the same loop. The critic + per-tool runtime checks remain the
    safety floor.
    """

    def _cloudops_pack_with_extras(self) -> tuple[Any, list[ToolDefinition]]:
        from services.investigation.tools.cloudops import TOOL_DEFINITIONS as CLOUDOPS_TOOL_DEFINITIONS, CloudOpsRulePack

        rule_pack = CloudOpsRulePack(_cloudops_trigger())
        prometheus_def = ToolDefinition(
            name="query_metrics_instant",
            domain="prometheus",
            description="Prometheus instant query",
            args_schema={"query": {"type": "str", "required": True}},
            mutation_class="read_only",
        )
        github_def = ToolDefinition(
            name="github_pr_diff",
            domain="github",
            description="GitHub PR diff",
            args_schema={"repo": {"type": "str", "required": True}, "pr_number": {"type": "int", "required": True}},
            mutation_class="read_only",
        )
        cross_domain_defs = list(CLOUDOPS_TOOL_DEFINITIONS) + [prometheus_def, github_def]
        return rule_pack, cross_domain_defs

    def test_llm_can_pick_cross_domain_tool_via_qualified_name(self) -> None:
        rule_pack, definitions = self._cloudops_pack_with_extras()
        selector = LlmProbeSelector(
            rule_pack,
            tool_definitions=definitions,
            decision_provider=lambda _ctx: {
                "action": "continue",
                "tool_name": "prometheus:query_metrics_instant",
                "args": {"query": 'up{service="frontend"}'},
                "reason": "check_freshness",
                "confidence": 0.75,
            },
            enabled=True,
        )
        decision = selector.plan(state=InvestigationLoopState(trigger_id="t"), trigger_context={})

        self.assertEqual(decision.action, "continue")
        self.assertEqual(decision.next_calls[0].domain, "prometheus")
        self.assertEqual(decision.next_calls[0].tool_name, "query_metrics_instant")

    def test_llm_can_pick_cross_domain_via_separate_domain_field(self) -> None:
        rule_pack, definitions = self._cloudops_pack_with_extras()
        selector = LlmProbeSelector(
            rule_pack,
            tool_definitions=definitions,
            decision_provider=lambda _ctx: {
                "action": "continue",
                "domain": "github",
                "tool_name": "github_pr_diff",
                "args": {"repo": "owner/repo", "pr_number": 42},
                "reason": "investigate_recent_change",
                "confidence": 0.8,
            },
            enabled=True,
        )
        decision = selector.plan(state=InvestigationLoopState(trigger_id="t"), trigger_context={})

        self.assertEqual(decision.next_calls[0].domain, "github")
        self.assertEqual(decision.next_calls[0].tool_name, "github_pr_diff")

    def test_llm_unqualified_tool_falls_back_to_rule_pack_domain(self) -> None:
        # Backward compat: a model that emits a bare ``tool_name``
        # (no domain, no colon) still lands on the planner's own
        # domain. This is the legacy single-domain prompt shape.
        rule_pack, definitions = self._cloudops_pack_with_extras()
        selector = LlmProbeSelector(
            rule_pack,
            tool_definitions=definitions,
            decision_provider=lambda _ctx: {
                "action": "continue",
                "tool_name": "DescribeResource",
                "args": {"resource_type": "pods", "name": "frontend", "namespace": "default"},
                "reason": "legacy_single_domain",
                "confidence": 0.6,
            },
            enabled=True,
        )
        decision = selector.plan(state=InvestigationLoopState(trigger_id="t"), trigger_context={})

        self.assertEqual(decision.next_calls[0].domain, "cloudops")
        self.assertEqual(decision.next_calls[0].tool_name, "DescribeResource")

    def test_llm_unknown_tool_stops_with_invalid_tool_reason(self) -> None:
        rule_pack, definitions = self._cloudops_pack_with_extras()
        selector = LlmProbeSelector(
            rule_pack,
            tool_definitions=definitions,
            decision_provider=lambda _ctx: {
                "action": "continue",
                "tool_name": "imaginary:nonexistent_tool",
                "args": {},
                "reason": "hallucinated",
                "confidence": 0.5,
            },
            enabled=True,
        )
        decision = selector.plan(state=InvestigationLoopState(trigger_id="t"), trigger_context={})

        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.reason, "llm_selector_invalid_tool")
        self.assertEqual(decision.debug["resolved_qualified"], "imaginary:nonexistent_tool")

    def test_llm_only_sees_read_only_tools(self) -> None:
        # Critical safety property: even if a domain pack accidentally
        # registered a mutating tool, the LLM selector's view of
        # ``available_tools`` excludes it. The critic is the second
        # defense; this is the first.
        rule_pack, definitions = self._cloudops_pack_with_extras()
        mutating_def = ToolDefinition(
            name="dangerous",
            domain="cloudops",
            description="should never appear in LLM context",
            args_schema={},
            mutation_class="hard_mutation",
        )
        selector = LlmProbeSelector(
            rule_pack,
            tool_definitions=list(definitions) + [mutating_def],
            decision_provider=lambda _ctx: {"action": "stop", "reason": "no", "confidence": 0.0},
            enabled=True,
        )
        # The LLM never sees the mutating tool.
        self.assertNotIn("cloudops:dangerous", selector._tool_definitions)


class AutoWireHarnessTests(unittest.TestCase):
    """Mesh's agentic surface fires on every production trigger, not
    just CloudOpsBench scenarios. ``_auto_wire_investigation_harness``
    has three paths — these tests pin which path fires for which
    trigger and confirm the production-default safety floor: when no
    LLM is configured, non-CloudOps triggers fall through to the
    legacy deterministic path.
    """

    def _config(self, **overrides: Any) -> Any:
        from shared.mesh_runtime.config import RuntimeConfig

        defaults = {
            "state_directory": "/tmp",
            "evaluation_mode": "native",
            "orchestration_mode": "native",
        }
        defaults.update(overrides)
        return RuntimeConfig(**defaults)

    def _trigger(self, trigger_type: str, **overrides: Any) -> Trigger:
        defaults = {
            "trigger_id": f"trg_{trigger_type}",
            "trigger_type": trigger_type,
            "triggered_at": "2026-05-08T00:00:00Z",
            "environment": "prod",
            "service": "frontend",
            "endpoint": "/",
            "flag_key": None,
            "current_rollout_pct": None,
            "comparison_window": None,
            "segment": {},
            "metrics": {},
            "related_context": {},
        }
        defaults.update(overrides)
        return Trigger(**defaults)

    def _root_with_kubectl_stub(self) -> ToolRegistry:
        # Simulate a deployment where kubectl auto-registered at root.
        root = ToolRegistry()
        root.register(
            ToolDefinition(
                name="kubectl_get",
                domain="kubectl",
                description="stub",
                args_schema={},
                mutation_class="read_only",
            ),
            lambda _a: RawToolOutput(output_summary="ok", valid=True),
        )
        return root

    def test_cloudopsbench_path_fires_for_snapshot_signal(self) -> None:
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config()
        trigger = self._trigger("otel_metric_regression")
        raw_signal = {"cloudopsbench_snapshot": {"some_key": "x"}}
        registry, planner = _auto_wire_investigation_harness(
            raw_signal, trigger, cfg, root_registry=self._root_with_kubectl_stub()
        )
        self.assertIsNotNone(registry)
        self.assertIsNotNone(planner)
        # Path 1 builds CloudOps planner (deterministic, no LLM configured)
        self.assertEqual(planner.domain, "cloudops")

    def test_reth_path_fires_for_reth_node_degraded_trigger(self) -> None:
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config()
        trigger = self._trigger("reth_node_degraded")
        raw_signal = {
            "execution": {"peer_count": 0, "min_peer_count": 1, "syncing": True},
            "consensus": {"engine_api_reachable": False, "client_kind": "lighthouse"},
            "logs": {"error_signatures": ["consensus_disconnected"]},
            "rpc": {"http_reachable": True},
        }
        registry, planner = _auto_wire_investigation_harness(
            raw_signal, trigger, cfg, root_registry=self._root_with_kubectl_stub()
        )
        self.assertIsNotNone(registry)
        self.assertIsNotNone(planner)
        # Path 2: Reth domain pack registered (deterministic without LLM)
        self.assertEqual(planner.domain, "reth")
        # Root tools are overlaid alongside Reth tools
        self.assertIsNotNone(registry.get("kubectl", "kubectl_get"))
        self.assertIsNotNone(registry.get("reth", "read_peer_sync"))

    def test_generic_path_with_llm_observer_fires_for_otel_regression(self) -> None:
        # Production path: LLM observer configured + non-CloudOps,
        # non-Reth trigger → harness should auto-wire with the
        # generic rule pack, giving the LLM the full read-only
        # tool surface.
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config(
            observer_enabled=True,
            observer_provider="openai",
            observer_api_key="sk-test",
            observer_model="gpt-4-turbo",
            observer_base_url="https://api.openai.com/v1",
        )
        trigger = self._trigger("otel_metric_regression")
        registry, planner = _auto_wire_investigation_harness(
            {}, trigger, cfg, root_registry=self._root_with_kubectl_stub()
        )

        self.assertIsNotNone(registry)
        self.assertIsNotNone(planner)
        self.assertEqual(planner.domain, "generic")
        # The LLM planner can see every read-only tool in the merged registry
        self.assertIn("kubectl:kubectl_get", planner._tool_definitions)

    def test_generic_path_with_llm_observer_fires_for_feature_flag_regression(self) -> None:
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config(
            observer_enabled=True,
            observer_provider="anthropic",
            observer_api_key="sk-ant-test",
            observer_model="claude-haiku-4-5-20251001",
        )
        trigger = self._trigger("feature_flag_performance_regression", flag_key="search_v2", current_rollout_pct=50)
        registry, planner = _auto_wire_investigation_harness(
            {}, trigger, cfg, root_registry=self._root_with_kubectl_stub()
        )
        self.assertIsNotNone(planner)
        self.assertEqual(planner.domain, "generic")

    def test_generic_path_with_llm_observer_fires_for_kubernetes_unhealthy(self) -> None:
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config(
            observer_enabled=True,
            observer_provider="openai",
            observer_api_key="sk-test",
            observer_model="gpt-4",
        )
        trigger = self._trigger("kubernetes_deployment_unhealthy")
        _registry, planner = _auto_wire_investigation_harness(
            {}, trigger, cfg, root_registry=self._root_with_kubectl_stub()
        )
        self.assertIsNotNone(planner)
        self.assertEqual(planner.domain, "generic")

    def test_generic_path_with_llm_observer_fires_for_webhook_alert(self) -> None:
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config(
            observer_enabled=True,
            observer_provider="openai",
            observer_api_key="sk-test",
            observer_model="gpt-4",
        )
        trigger = self._trigger("webhook_alert_firing")
        _registry, planner = _auto_wire_investigation_harness(
            {}, trigger, cfg, root_registry=self._root_with_kubectl_stub()
        )
        self.assertIsNotNone(planner)
        self.assertEqual(planner.domain, "generic")

    def test_generic_path_disabled_when_no_llm(self) -> None:
        # Safety floor: without an LLM observer configured, non-domain
        # triggers fall through to the legacy deterministic path. We
        # never spin up a harness with no chooser — that would just
        # return ``stop`` on the first iteration and waste a probe budget.
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config()  # no observer_enabled
        trigger = self._trigger("otel_metric_regression")
        registry, planner = _auto_wire_investigation_harness(
            {}, trigger, cfg, root_registry=self._root_with_kubectl_stub()
        )
        self.assertIsNone(registry)
        self.assertIsNone(planner)

    def test_generic_path_disabled_when_root_has_no_tools(self) -> None:
        # If a deployment doesn't configure any diagnostic packs
        # (no kubectl, no Prometheus, no GitHub, no anything), the
        # LLM has nothing to call — return None so the legacy path
        # remains the safety floor.
        from services.runtime import _auto_wire_investigation_harness

        cfg = self._config(
            observer_enabled=True,
            observer_provider="openai",
            observer_api_key="sk-test",
            observer_model="gpt-4",
        )
        empty_root = ToolRegistry()
        trigger = self._trigger("otel_metric_regression")
        registry, planner = _auto_wire_investigation_harness(
            {}, trigger, cfg, root_registry=empty_root
        )
        self.assertIsNone(registry)
        self.assertIsNone(planner)


class GenericRulePackTests(unittest.TestCase):
    def test_generic_pack_has_no_rules_and_no_domain_tools(self) -> None:
        from services.investigation.harness import GenericRulePack

        pack = GenericRulePack()
        self.assertEqual(pack.domain, "generic")
        self.assertEqual(tuple(pack.rules), ())
        self.assertEqual(tuple(pack.tool_definitions), ())

    def test_generic_pack_stops_when_ranker_emits_high_confidence_candidate(self) -> None:
        from services.investigation.harness import GenericRulePack
        from services.investigation.harness.native_selector import ObservationIndex

        pack = GenericRulePack()
        index = ObservationIndex.from_state(
            state=InvestigationLoopState(
                trigger_id="t",
                observed_text=["frontend 0/1 ImagePullBackOff", "Reason: ErrImagePull manifest unknown"],
            ),
            trigger_context={},
            root_cause_ranker=pack.root_cause_ranker,
        )
        candidate = pack.sufficient_root_cause(index)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.root_cause, "incorrect_image_reference")

    def test_generic_pack_does_not_stop_on_weak_signal(self) -> None:
        from services.investigation.harness import GenericRulePack
        from services.investigation.harness.native_selector import ObservationIndex

        pack = GenericRulePack()
        index = ObservationIndex.from_state(
            state=InvestigationLoopState(
                trigger_id="t",
                observed_text=["nothing useful here"],
            ),
            trigger_context={},
            root_cause_ranker=pack.root_cause_ranker,
        )
        self.assertIsNone(pack.sufficient_root_cause(index))


class _CloudOpsSnapshotCall:
    def __init__(self, *, valid: bool) -> None:
        self.valid = valid


class _CloudOpsSnapshot:
    def __init__(self, outputs: dict[str, Any]) -> None:
        self.outputs = outputs
        self.calls: list[_CloudOpsSnapshotCall] = []

    def invoke(self, tool_name: str, args: dict[str, Any]) -> Any:
        valid = tool_name in self.outputs
        self.calls.append(_CloudOpsSnapshotCall(valid=valid))
        return self.outputs.get(tool_name, {"error": f"missing {tool_name}"})


def _cloudops_trigger() -> Trigger:
    return Trigger(
        trigger_id="trg_cloudops",
        trigger_type="cloudopsbench_case",
        triggered_at="2026-05-04T00:00:00Z",
        environment="test",
        service="frontend",
        endpoint="/",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=None,
        segment={},
        metrics={},
        related_context={"namespace": "default"},
    )


def _shlex_quote(s: str) -> str:
    """Quote helper used by the subprocess-driven pack tests below."""
    import shlex as _shlex
    return _shlex.quote(s)


class PrometheusToolPackTests(unittest.TestCase):
    """Prometheus pack — first domain that talks to a live external API.
    The harness contract should not change vs in-process domains: same
    registry, same critic, same loop. These tests pin that with a stub.
    """

    def test_instant_query_produces_valid_tool_result(self) -> None:
        from services.investigation.tools.prometheus import (
            InstantPlanner as PrometheusInstantPlanner,
            register as register_prometheus_tools,
        )

        class StubClient:
            def instant_query(self, _query: str) -> float | None:
                return 0.42

            def range_query(self, *_args: Any, **_kwargs: Any) -> list[tuple[float, float]]:
                return []

        registry = ToolRegistry()
        register_prometheus_tools(registry, StubClient())
        critic = LoopCritic(registry)
        state = InvestigationLoopState(trigger_id="trg_p", budget_remaining=2.0)

        run_investigation_loop(
            state=state,
            planner=PrometheusInstantPlanner(query='up{service="frontend"}'),
            registry=registry,
            critic=critic,
            max_iterations=3,
        )

        self.assertEqual([c.tool_name for c in state.tool_calls], ["query_metrics_instant"])
        self.assertTrue(state.tool_results[0].valid)
        self.assertIn("0.42", state.tool_results[0].output_summary)

    def test_instant_query_with_no_data_marks_result_invalid(self) -> None:
        from services.investigation.tools.prometheus import (
            InstantPlanner as PrometheusInstantPlanner,
            register as register_prometheus_tools,
        )

        class EmptyClient:
            def instant_query(self, _query: str) -> float | None:
                return None

            def range_query(self, *_args: Any, **_kwargs: Any) -> list[tuple[float, float]]:
                return []

        registry = ToolRegistry()
        register_prometheus_tools(registry, EmptyClient())
        critic = LoopCritic(registry)
        state = InvestigationLoopState(trigger_id="trg_p", budget_remaining=2.0)
        run_investigation_loop(
            state=state,
            planner=PrometheusInstantPlanner(query="up"),
            registry=registry,
            critic=critic,
        )
        self.assertFalse(state.tool_results[0].valid)
        self.assertIn("no_data", state.tool_results[0].output_summary)


class AwsToolPackTests(unittest.TestCase):
    """AWS pack is read-only by enforcement, not just classification.
    Mutation verbs must be blocked at the implementation layer too —
    critic is the first defense, this is the second.
    """

    def test_read_only_verb_check_accepts_snake_and_camel(self) -> None:
        from services.investigation.tools.aws import _is_read_only_operation

        for ok in ("describe_instances", "get_role", "list_buckets", "ListBuckets", "DescribeInstances", "GetRole", "search_resources"):
            self.assertTrue(_is_read_only_operation(ok), ok)
        for not_ok in ("delete_instance", "put_object", "create_role", "DeleteBucket", "TerminateInstances"):
            self.assertFalse(_is_read_only_operation(not_ok), not_ok)

    def test_redaction_drops_secret_keys_recursively(self) -> None:
        # Policy: any key whose name contains secret/password/token/
        # credential/private gets its value blanket-redacted, even if
        # the value is a dict. Conservative-by-default — over-redaction
        # is a safer error than leaking a single nested secret.
        from services.investigation.tools.aws import _redact_aws_response

        payload = {
            "Region": "us-east-1",
            "Credentials": {"AccessKeyId": "AKIA", "Other": "fine"},
            "Items": [{"PrivateKey": "rsa", "Name": "ok"}],
            "Token": "abc",
        }
        redacted = _redact_aws_response(payload)
        self.assertEqual(redacted["Region"], "us-east-1")
        self.assertEqual(redacted["Credentials"], "[redacted]")
        self.assertEqual(redacted["Token"], "[redacted]")
        self.assertEqual(redacted["Items"][0]["PrivateKey"], "[redacted]")
        self.assertEqual(redacted["Items"][0]["Name"], "ok")

    def test_invocation_with_mutating_verb_is_rejected(self) -> None:
        from services.investigation.tools.aws import TOOL_DEFINITIONS as AWS_TOOL_DEFINITIONS, register as register_aws_tools

        registry = ToolRegistry()
        register_aws_tools(registry)
        defn = AWS_TOOL_DEFINITIONS[0]
        call = make_call(tool=defn, args={"service": "s3", "operation": "delete_bucket"})
        result = registry.invoke(call)

        self.assertEqual(result.status, "failed")
        self.assertFalse(result.valid)
        self.assertIn("not classified read-only", result.error or "")


class KubectlToolPackTests(unittest.TestCase):
    """Live kubectl pack runs subprocess. Tests use a fake kubectl
    script so we can pin argv construction + read-only enforcement +
    failure handling without a real cluster.
    """

    def _make_fake_kubectl(self, tmp_path: str, *, exit_code: int = 0, stdout: str = "") -> str:
        import os
        import stat

        path = os.path.join(tmp_path, "fake-kubectl")
        argv_log = os.path.join(tmp_path, "argv.log")
        script = (
            "#!/bin/bash\n"
            f"echo \"$@\" >> {_shlex_quote(argv_log)}\n"
            f"echo {_shlex_quote(stdout)}\n"
            f"exit {exit_code}\n"
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def _read_argv_log(self, tmp_path: str) -> list[list[str]]:
        import os

        argv_log = os.path.join(tmp_path, "argv.log")
        if not os.path.exists(argv_log):
            return []
        with open(argv_log, encoding="utf-8") as fh:
            return [line.strip().split() for line in fh if line.strip()]

    def test_kubectl_get_builds_correct_argv(self) -> None:
        import tempfile

        from services.investigation.tools.kubectl import TOOL_DEFINITIONS as KUBECTL_TOOL_DEFINITIONS, register as register_kubectl_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_kubectl(tmp, stdout="frontend 1/1 Running")
            registry = ToolRegistry()
            register_kubectl_tools(registry, kubectl_path=fake, default_context="ctx-prod")
            defn = next(d for d in KUBECTL_TOOL_DEFINITIONS if d.name == "kubectl_get")
            call = make_call(
                tool=defn,
                args={"resource_type": "pods", "namespace": "boutique", "label_selector": "app=frontend"},
            )
            result = registry.invoke(call)

            self.assertEqual(result.status, "completed")
            argvs = self._read_argv_log(tmp)
            self.assertEqual(
                argvs[0],
                ["--context", "ctx-prod", "get", "pods", "-n", "boutique", "-l", "app=frontend"],
            )

    def test_kubectl_describe_requires_name(self) -> None:
        import tempfile

        from services.investigation.tools.kubectl import TOOL_DEFINITIONS as KUBECTL_TOOL_DEFINITIONS, register as register_kubectl_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_kubectl(tmp, stdout="ok")
            registry = ToolRegistry()
            register_kubectl_tools(registry, kubectl_path=fake)
            defn = next(d for d in KUBECTL_TOOL_DEFINITIONS if d.name == "kubectl_describe")
            call = make_call(tool=defn, args={"resource_type": "pods"})
            result = registry.invoke(call)
            self.assertEqual(result.status, "failed")
            self.assertEqual(self._read_argv_log(tmp), [])

    def test_kubectl_logs_uses_default_tail_when_unspecified(self) -> None:
        import tempfile

        from services.investigation.tools.kubectl import TOOL_DEFINITIONS as KUBECTL_TOOL_DEFINITIONS, register as register_kubectl_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_kubectl(tmp, stdout="log line")
            registry = ToolRegistry()
            register_kubectl_tools(registry, kubectl_path=fake)
            defn = next(d for d in KUBECTL_TOOL_DEFINITIONS if d.name == "kubectl_logs")
            call = make_call(tool=defn, args={"name": "pod-x", "namespace": "boutique"})
            registry.invoke(call)
            argvs = self._read_argv_log(tmp)
            self.assertIn("--tail", argvs[0])
            tail_idx = argvs[0].index("--tail")
            self.assertEqual(argvs[0][tail_idx + 1], "200")

    def test_kubectl_missing_binary_returns_clean_failure(self) -> None:
        from services.investigation.tools.kubectl import TOOL_DEFINITIONS as KUBECTL_TOOL_DEFINITIONS, register as register_kubectl_tools

        registry = ToolRegistry()
        register_kubectl_tools(registry, kubectl_path="")
        defn = next(d for d in KUBECTL_TOOL_DEFINITIONS if d.name == "kubectl_get")
        call = make_call(tool=defn, args={"resource_type": "pods"})
        result = registry.invoke(call)
        self.assertEqual(result.status, "failed")
        self.assertIn("kubectl binary not found", result.error or "")


class GithubToolPackTests(unittest.TestCase):
    """GitHub pack proxies through ``gh api -X GET``. Tests use a fake
    gh script to verify argv shape + read-only verb + URL building.
    """

    def _make_fake_gh(self, tmp_path: str, *, exit_code: int = 0, stdout: str = "[]") -> str:
        import os
        import stat

        path = os.path.join(tmp_path, "fake-gh")
        argv_log = os.path.join(tmp_path, "argv.log")
        script = (
            "#!/bin/bash\n"
            f"echo \"$@\" >> {_shlex_quote(argv_log)}\n"
            f"echo {_shlex_quote(stdout)}\n"
            f"exit {exit_code}\n"
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def _read_argv_log(self, tmp_path: str) -> list[list[str]]:
        import os

        argv_log = os.path.join(tmp_path, "argv.log")
        if not os.path.exists(argv_log):
            return []
        with open(argv_log, encoding="utf-8") as fh:
            return [line.strip().split() for line in fh if line.strip()]

    def test_recent_commits_builds_get_argv(self) -> None:
        import tempfile

        from services.investigation.tools.github import TOOL_DEFINITIONS as GITHUB_TOOL_DEFINITIONS, register as register_github_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_gh(tmp, stdout='[{"sha":"abc"}]')
            registry = ToolRegistry()
            register_github_tools(registry, gh_path=fake)
            defn = next(d for d in GITHUB_TOOL_DEFINITIONS if d.name == "github_recent_commits")
            call = make_call(
                tool=defn,
                args={"repo": "hydrogenbond007/mesh", "branch": "master", "limit": 5},
            )
            result = registry.invoke(call)

            self.assertEqual(result.status, "completed")
            argvs = self._read_argv_log(tmp)
            self.assertIn("api", argvs[0])
            self.assertIn("GET", argvs[0])
            full_url = argvs[0][-1]
            self.assertIn("repos/hydrogenbond007/mesh/commits", full_url)
            self.assertIn("per_page=5", full_url)
            self.assertIn("sha=master", full_url)

    def test_pr_diff_uses_diff_accept_header(self) -> None:
        import tempfile

        from services.investigation.tools.github import TOOL_DEFINITIONS as GITHUB_TOOL_DEFINITIONS, register as register_github_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_gh(tmp, stdout="diff --git a/x b/x\n")
            registry = ToolRegistry()
            register_github_tools(registry, gh_path=fake)
            defn = next(d for d in GITHUB_TOOL_DEFINITIONS if d.name == "github_pr_diff")
            call = make_call(tool=defn, args={"repo": "owner/repo", "pr_number": 42})
            registry.invoke(call)
            argvs = self._read_argv_log(tmp)
            joined = " ".join(argvs[0])
            self.assertIn("Accept:", joined)
            self.assertIn("application/vnd.github.diff", joined)
            self.assertIn("repos/owner/repo/pulls/42", joined)

    def test_search_code_repo_qualifier_added_to_query(self) -> None:
        import tempfile

        from services.investigation.tools.github import TOOL_DEFINITIONS as GITHUB_TOOL_DEFINITIONS, register as register_github_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_gh(tmp, stdout='{"total_count":0,"items":[]}')
            registry = ToolRegistry()
            register_github_tools(registry, gh_path=fake)
            defn = next(d for d in GITHUB_TOOL_DEFINITIONS if d.name == "github_search_code")
            call = make_call(tool=defn, args={"repo": "owner/repo", "query": "TODO investigate"})
            registry.invoke(call)
            argvs = self._read_argv_log(tmp)
            url = argvs[0][-1]
            self.assertIn("repo%3Aowner%2Frepo", url)
            self.assertIn("TODO", url)

    def test_invalid_repo_returns_failure(self) -> None:
        from services.investigation.tools.github import TOOL_DEFINITIONS as GITHUB_TOOL_DEFINITIONS, register as register_github_tools

        registry = ToolRegistry()
        register_github_tools(registry, gh_path="/no/such/binary")
        defn = next(d for d in GITHUB_TOOL_DEFINITIONS if d.name == "github_recent_commits")
        call = make_call(tool=defn, args={"repo": "owneronly"})
        result = registry.invoke(call)
        self.assertEqual(result.status, "failed")


class LokiJaegerToolPackTests(unittest.TestCase):
    """Loki + Jaeger packs talk pure HTTP. We spin up a stub HTTP
    server on localhost so the tests verify URL building + parsing
    without external dependencies.
    """

    def setUp(self) -> None:
        import http.server
        import threading

        self._captured_paths: list[str] = []
        self._response_body = b'{"data":[]}'

        captured = self._captured_paths
        outer = self

        class StubHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self_inner: Any) -> None:  # noqa: N802
                captured.append(self_inner.path)
                self_inner.send_response(200)
                self_inner.send_header("Content-Type", "application/json")
                self_inner.end_headers()
                self_inner.wfile.write(outer._response_body)  # type: ignore[attr-defined]

            def log_message(self, *args: Any, **kwargs: Any) -> None:
                return

        self._server = http.server.HTTPServer(("127.0.0.1", 0), StubHandler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.base_url = f"http://127.0.0.1:{self._port}"

    def tearDown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1.0)

    def test_loki_query_range_uses_nanosecond_timestamps(self) -> None:
        from services.investigation.tools.loki import TOOL_DEFINITIONS as LOKI_TOOL_DEFINITIONS, register as register_loki_tools

        registry = ToolRegistry()
        register_loki_tools(registry, base_url=self.base_url)
        defn = next(d for d in LOKI_TOOL_DEFINITIONS if d.name == "query_range")
        call = make_call(tool=defn, args={"query": '{app="frontend"} |= "ERROR"', "limit": 50})
        result = registry.invoke(call)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(self._captured_paths), 1)
        path = self._captured_paths[0]
        self.assertIn("/loki/api/v1/query_range", path)
        import urllib.parse as _up
        query = _up.parse_qs(path.split("?", 1)[1])
        self.assertGreater(int(query["start"][0]), 10**15)
        self.assertGreater(int(query["end"][0]), 10**15)

    def test_jaeger_get_traces_passes_microsecond_window(self) -> None:
        from services.investigation.tools.jaeger import TOOL_DEFINITIONS as JAEGER_TOOL_DEFINITIONS, register as register_jaeger_tools

        registry = ToolRegistry()
        register_jaeger_tools(registry, base_url=self.base_url)
        defn = next(d for d in JAEGER_TOOL_DEFINITIONS if d.name == "get_traces")
        call = make_call(tool=defn, args={"service": "frontend", "lookback_seconds": 600, "limit": 5})
        registry.invoke(call)

        path = self._captured_paths[0]
        self.assertIn("/api/traces", path)
        import urllib.parse as _up
        query = _up.parse_qs(path.split("?", 1)[1])
        self.assertEqual(query["service"], ["frontend"])
        self.assertEqual(query["limit"], ["5"])
        self.assertGreater(int(query["start"][0]), 10**12)

    def test_loki_invalid_query_short_circuits(self) -> None:
        from services.investigation.tools.loki import TOOL_DEFINITIONS as LOKI_TOOL_DEFINITIONS, register as register_loki_tools

        registry = ToolRegistry()
        register_loki_tools(registry, base_url=self.base_url)
        defn = next(d for d in LOKI_TOOL_DEFINITIONS if d.name == "query_range")
        call = make_call(tool=defn, args={"query": ""})
        result = registry.invoke(call)
        self.assertEqual(result.status, "failed")
        self.assertEqual(self._captured_paths, [])


class PostgresToolPackTests(unittest.TestCase):
    """PG pack uses subprocess psql with hard-coded read-only verbs.
    Tests verify identifier validation + DML rejection without a real DB.
    """

    def _make_fake_psql(self, tmp_path: str, *, exit_code: int = 0, stdout: str = "ok") -> str:
        import os
        import stat

        path = os.path.join(tmp_path, "fake-psql")
        argv_log = os.path.join(tmp_path, "argv.log")
        script = (
            "#!/bin/bash\n"
            f"echo \"$@\" >> {_shlex_quote(argv_log)}\n"
            f"echo {_shlex_quote(stdout)}\n"
            f"exit {exit_code}\n"
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def _read_argv_log(self, tmp_path: str) -> list[list[str]]:
        import os

        argv_log = os.path.join(tmp_path, "argv.log")
        if not os.path.exists(argv_log):
            return []
        with open(argv_log, encoding="utf-8") as fh:
            return [line.strip().split() for line in fh if line.strip()]

    def test_describe_table_passes_backslash_d_to_psql(self) -> None:
        import tempfile

        from services.investigation.tools.postgres import TOOL_DEFINITIONS as PG_TOOL_DEFINITIONS, register as register_pg_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_psql(tmp, stdout="Column | Type")
            registry = ToolRegistry()
            register_pg_tools(registry, dsn="postgres://x@y/z", psql_path=fake)
            defn = next(d for d in PG_TOOL_DEFINITIONS if d.name == "pg_describe_table")
            call = make_call(tool=defn, args={"table_name": "public.users"})
            result = registry.invoke(call)

            self.assertEqual(result.status, "completed")
            argvs = self._read_argv_log(tmp)
            joined = " ".join(argvs[0])
            self.assertIn("public.users", joined)

    def test_describe_table_rejects_injection_attempt(self) -> None:
        from services.investigation.tools.postgres import TOOL_DEFINITIONS as PG_TOOL_DEFINITIONS, register as register_pg_tools

        registry = ToolRegistry()
        register_pg_tools(registry, dsn="postgres://x@y/z", psql_path="/no/binary")
        defn = next(d for d in PG_TOOL_DEFINITIONS if d.name == "pg_describe_table")

        for malicious in ("users; DROP TABLE foo", "x' OR '1'='1", "users--", "users\nSELECT 1"):
            call = make_call(tool=defn, args={"table_name": malicious})
            result = registry.invoke(call)
            self.assertEqual(result.status, "failed", malicious)

    def test_explain_rejects_dml_verbs(self) -> None:
        from services.investigation.tools.postgres import TOOL_DEFINITIONS as PG_TOOL_DEFINITIONS, register as register_pg_tools

        registry = ToolRegistry()
        register_pg_tools(registry, dsn="postgres://x@y/z", psql_path="/no/binary")
        defn = next(d for d in PG_TOOL_DEFINITIONS if d.name == "pg_explain_query")

        for write in ("INSERT INTO foo VALUES (1)", "UPDATE foo SET x=1", "DELETE FROM foo", "DROP TABLE foo", "TRUNCATE foo"):
            call = make_call(tool=defn, args={"query": write})
            result = registry.invoke(call)
            self.assertEqual(result.status, "failed", write)

    def test_explain_accepts_select(self) -> None:
        import tempfile

        from services.investigation.tools.postgres import TOOL_DEFINITIONS as PG_TOOL_DEFINITIONS, register as register_pg_tools

        with tempfile.TemporaryDirectory() as tmp:
            fake = self._make_fake_psql(tmp, stdout="Seq Scan on foo")
            registry = ToolRegistry()
            register_pg_tools(registry, dsn="postgres://x@y/z", psql_path=fake)
            defn = next(d for d in PG_TOOL_DEFINITIONS if d.name == "pg_explain_query")
            call = make_call(tool=defn, args={"query": "SELECT * FROM foo WHERE id = 1"})
            result = registry.invoke(call)

            self.assertEqual(result.status, "completed")
            argvs = self._read_argv_log(tmp)
            self.assertIn("EXPLAIN", " ".join(argvs[0]))


class MCPBridgeTests(unittest.TestCase):
    """The MCP bridge turns an opaque MCP client into registered
    ToolDefinitions. Tests use a stub client (no transport) — that
    same shape any real MCP lib (official SDK, FastMCP, stdio) gets
    adapted into.
    """

    def _make_stub_client(
        self,
        tools: list[Any],
        responses: dict[str, Any] | None = None,
        raise_on_list: bool = False,
        raise_on_call: bool = False,
    ) -> Any:
        from services.investigation.tools.mcp import MCPToolMeta

        class StubMCPClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any]]] = []

            def list_tools(self) -> list[MCPToolMeta]:
                if raise_on_list:
                    raise RuntimeError("stub list_tools failure")
                return list(tools)

            def call_tool(self, name: str, args: dict[str, Any]) -> Any:
                self.calls.append((name, args))
                if raise_on_call:
                    raise RuntimeError("stub call_tool failure")
                return (responses or {}).get(name, {"ok": True, "tool": name})

        return StubMCPClient()

    def test_advertised_tools_become_registered_tool_definitions(self) -> None:
        from services.investigation.tools.mcp import MCPToolMeta, register as register_mcp_tools

        tools = [
            MCPToolMeta(
                name="get_metrics",
                description="Prometheus query",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            ),
            MCPToolMeta(
                name="get_traces",
                description="Jaeger traces",
                input_schema={"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]},
            ),
        ]
        client = self._make_stub_client(tools, responses={"get_metrics": [1, 2, 3]})
        registry = ToolRegistry()

        registered = register_mcp_tools(registry, client=client, server_id="sregym")

        self.assertEqual(set(registered), {"mcp:sregym__get_metrics", "mcp:sregym__get_traces"})
        defn, _ = registry.get("mcp", "sregym__get_metrics")
        self.assertEqual(defn.args_schema["query"], {"type": "str", "required": True})

    def test_invocation_routes_through_client_and_records_result(self) -> None:
        from services.investigation.tools.mcp import MCPToolMeta, register as register_mcp_tools

        tools = [
            MCPToolMeta(
                name="get_logs",
                description="Loki query",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ]
        client = self._make_stub_client(tools, responses={"get_logs": ["log line 1", "log line 2"]})
        registry = ToolRegistry()
        register_mcp_tools(registry, client=client, server_id="loki")

        defn, _ = registry.get("mcp", "loki__get_logs")
        call = make_call(tool=defn, args={"query": '{app="frontend"}'})
        result = registry.invoke(call)

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.valid)
        self.assertEqual(client.calls, [("get_logs", {"query": '{app="frontend"}'})])
        self.assertIn("log line 1", result.output_summary)

    def test_allowlist_filters_advertised_tools(self) -> None:
        from services.investigation.tools.mcp import MCPToolMeta, register as register_mcp_tools

        tools = [
            MCPToolMeta(name=f"tool_{i}", description="x", input_schema={"type": "object", "properties": {}})
            for i in range(5)
        ]
        client = self._make_stub_client(tools)
        registry = ToolRegistry()

        registered = register_mcp_tools(registry, client=client, server_id="x", allow_tools=["tool_0", "tool_2"])

        self.assertEqual(set(registered), {"mcp:x__tool_0", "mcp:x__tool_2"})

    def test_mutating_advertised_tools_blocked_by_default(self) -> None:
        # Critical safety property: an MCP server can advertise anything,
        # but the bridge must default to read-only. Operators must
        # explicitly opt in mutating tools.
        from services.investigation.tools.mcp import MCPToolMeta, register as register_mcp_tools

        tools = [
            MCPToolMeta(name="read_thing", description="x", input_schema={"type": "object", "properties": {}}),
            MCPToolMeta(name="delete_thing", description="x", input_schema={"type": "object", "properties": {}}),
        ]
        client = self._make_stub_client(tools)
        registry = ToolRegistry()
        registered = register_mcp_tools(
            registry,
            client=client,
            server_id="x",
            mutation_class_map={"delete_thing": "hard_mutation"},
        )

        self.assertEqual(registered, ["mcp:x__read_thing"])

    def test_list_tools_failure_returns_empty_not_exception(self) -> None:
        from services.investigation.tools.mcp import register as register_mcp_tools

        client = self._make_stub_client([], raise_on_list=True)
        registry = ToolRegistry()
        registered = register_mcp_tools(registry, client=client, server_id="x")
        self.assertEqual(registered, [])

    def test_call_failure_produces_failed_result_not_exception(self) -> None:
        from services.investigation.tools.mcp import MCPToolMeta, register as register_mcp_tools

        tools = [MCPToolMeta(name="t", description="x", input_schema={"type": "object", "properties": {}})]
        client = self._make_stub_client(tools, raise_on_call=True)
        registry = ToolRegistry()
        register_mcp_tools(registry, client=client, server_id="x")
        defn, _ = registry.get("mcp", "x__t")
        result = registry.invoke(make_call(tool=defn))
        self.assertEqual(result.status, "failed")
        self.assertIn("stub call_tool failure", result.error or "")


class RootRegistryAutoWireTests(unittest.TestCase):
    """The engine root_registry auto-registers diagnostic packs gated
    on config/env. ``_overlay_root_registry`` then merges the root
    onto each per-run registry so the LLM planner can mix CloudOps
    snapshot tools with always-on Prometheus/AWS/etc. in one loop.
    """

    def test_overlay_does_not_override_per_run_tool_with_same_name(self) -> None:
        from services.runtime import _overlay_root_registry

        per_run = ToolRegistry()
        per_run.register(
            ToolDefinition(
                name="GetResources", domain="cloudops",
                description="per-run", args_schema={}, mutation_class="read_only",
            ),
            lambda _a: RawToolOutput(output_summary="per_run"),
        )
        root = ToolRegistry()
        root.register(
            ToolDefinition(
                name="GetResources", domain="cloudops",
                description="root", args_schema={}, mutation_class="read_only",
            ),
            lambda _a: RawToolOutput(output_summary="root"),
        )
        _overlay_root_registry(per_run, root)

        # Per-run wins; root's invoker is shadowed.
        defn, _ = per_run.get("cloudops", "GetResources")
        result = per_run.invoke(make_call(tool=defn))
        self.assertEqual(result.output_summary, "per_run")

    def test_overlay_adds_root_only_tools_to_per_run(self) -> None:
        from services.runtime import _overlay_root_registry

        per_run = ToolRegistry()
        root = ToolRegistry()
        root.register(
            ToolDefinition(
                name="instant", domain="prometheus",
                description="root", args_schema={}, mutation_class="read_only",
            ),
            lambda _a: RawToolOutput(output_summary="ok"),
        )
        _overlay_root_registry(per_run, root)
        self.assertIsNotNone(per_run.get("prometheus", "instant"))


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
