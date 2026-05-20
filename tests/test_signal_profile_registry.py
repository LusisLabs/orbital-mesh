"""Tests for ``SignalProfile`` + ``SignalProfileRegistry``.

Three layers covered:

1. Registry contract — uniqueness, completeness, generic-sentinel
   handling. These are the fail-loud invariants from the spec.
2. Default registry — every shipping profile registers, every
   ``signal_type`` and ``trigger_type`` resolves, the generic
   fallback catches unknown types.
3. Wired strategies — PR 1 wires ``investigation_planner`` and
   ``rca_builder`` for every profile. These tests assert those two
   are real (not ``NotYetWiredStrategy`` placeholders) and produce
   contract-valid output for every profile.
"""

from __future__ import annotations

import unittest

from shared.mesh_runtime.contracts import Decision, InvestigationPlan, RcaReport, Trigger
from shared.mesh_runtime.signal_profile import (
    GENERIC_PROFILE_KEY,
    IncompleteProfile,
    ProfileAlreadyRegistered,
    SignalProfile,
    SignalProfileRegistry,
)

from services.signal_profiles import build_default_registry
from services.signal_profiles._shared_strategies import (
    HarnessDrivenInvestigationPlanner,
    HarnessDrivenRcaBuilder,
    NotYetWiredStrategy,
    NotYetWired,
)


def _make_trigger(trigger_type: str = "reth_node_degraded") -> Trigger:
    return Trigger(
        trigger_id="trg_test_0001",
        trigger_type=trigger_type,
        triggered_at="2026-05-13T12:00:00Z",
        environment="prod",
        service="payments-checkout",
        endpoint="/api/v1/checkout",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=None,
        segment={},
        metrics={},
        related_context={"error_signatures": []},
    )


def _make_decision() -> Decision:
    return Decision(
        decision_id="dec_test_0001",
        trigger_id="trg_test_0001",
        summary="test decision",
        decision_type="escalate",
        autonomy_tier="tier_3_review",
        reasoning={"ranked_hypotheses": []},
        expected_outcome={"latency_ms_p99": "no_change", "error_rate_p99": "no_change"},
        risk={"impact": "low", "rollback_cost": "low"},
        confidence=0.42,
        execution_plan={"mode": "manual", "steps": []},
    )


def _stub_profile(signal_type: str = "test_signal", trigger_type: str = "test_trigger") -> SignalProfile:
    """Build a fully-populated stub profile for registry semantics tests.

    Every strategy slot uses a ``NotYetWiredStrategy`` — the tests in
    this module only need the profile to satisfy structural validation,
    not produce real artifacts.
    """
    return SignalProfile(
        signal_type=signal_type,
        trigger_type=trigger_type,
        schema_name="test.schema.json",
        ingest_normalizer=NotYetWiredStrategy("ingest_normalizer:test"),
        trigger_detector=NotYetWiredStrategy("trigger_detector:test"),
        investigation_planner=NotYetWiredStrategy("investigation_planner:test"),
        evidence_strategy=NotYetWiredStrategy("evidence_strategy:test"),
        rca_builder=NotYetWiredStrategy("rca_builder:test"),
        decision_strategy=NotYetWiredStrategy("decision_strategy:test"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:test"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:test"),
    )


class RegistryContractTests(unittest.TestCase):
    """The fail-loud invariants from the spec (invariant 3)."""

    def test_empty_registry_returns_none_for_unknown_lookups(self) -> None:
        registry = SignalProfileRegistry(profiles=[])
        self.assertIsNone(registry.get("anything"))
        self.assertIsNone(registry.get_for_trigger("anything"))

    def test_get_or_generic_raises_without_generic_when_unknown(self) -> None:
        registry = SignalProfileRegistry(profiles=[])
        with self.assertRaises(IncompleteProfile):
            registry.get_or_generic("unknown")

    def test_duplicate_signal_type_registration_raises(self) -> None:
        with self.assertRaises(ProfileAlreadyRegistered):
            SignalProfileRegistry(
                profiles=[
                    _stub_profile("dup_signal", "trigger_a"),
                    _stub_profile("dup_signal", "trigger_b"),
                ]
            )

    def test_duplicate_trigger_type_registration_raises(self) -> None:
        with self.assertRaises(ProfileAlreadyRegistered):
            SignalProfileRegistry(
                profiles=[
                    _stub_profile("signal_a", "dup_trigger"),
                    _stub_profile("signal_b", "dup_trigger"),
                ]
            )

    def test_concrete_profile_cannot_use_generic_sentinel(self) -> None:
        sentinel_profile = _stub_profile(GENERIC_PROFILE_KEY, "trigger_x")
        with self.assertRaises(IncompleteProfile):
            SignalProfileRegistry(profiles=[sentinel_profile])

    def test_generic_profile_must_use_sentinel(self) -> None:
        wrong = _stub_profile("not_sentinel", "trigger_y")
        with self.assertRaises(IncompleteProfile):
            SignalProfileRegistry(profiles=[], generic=wrong)


class GenericFallbackTests(unittest.TestCase):
    """Invariant 1 + 2: every signal type resolves, unknown types
    cannot bypass the generic profile.
    """

    def test_unknown_signal_type_resolves_to_generic(self) -> None:
        registry = build_default_registry()
        profile = registry.get_or_generic("aws_cloudwatch_alarm_not_yet_registered")
        self.assertEqual(profile.signal_type, GENERIC_PROFILE_KEY)
        self.assertEqual(profile.signal_source, "generic")

    def test_none_signal_type_resolves_to_generic(self) -> None:
        registry = build_default_registry()
        profile = registry.get_or_generic(None)
        self.assertEqual(profile.signal_type, GENERIC_PROFILE_KEY)

    def test_known_signal_type_does_not_resolve_to_generic(self) -> None:
        registry = build_default_registry()
        profile = registry.get_or_generic("reth_node")
        self.assertEqual(profile.signal_type, "reth_node")
        self.assertNotEqual(profile.signal_type, GENERIC_PROFILE_KEY)

    def test_unknown_trigger_type_falls_back_to_generic(self) -> None:
        registry = build_default_registry()
        profile = registry.get_or_generic_for_trigger("invented_trigger_type")
        self.assertEqual(profile.signal_type, GENERIC_PROFILE_KEY)


class ShippingSignalTypesMatchCodebaseTests(unittest.TestCase):
    """Regression guard: every signal_type the codebase actually emits
    must resolve to a concrete profile (NOT the generic fallback).

    The previous shape of this PR had ``FeatureFlagSignalProfile`` register
    ``signal_type="feature_flag_alert"`` because the docstring mistakenly
    claimed the FF path rode the webhook payload schema. In reality the
    codebase emits ``signal_type="feature_flag"`` (the default when an
    inbound signal omits the field — see
    ``services/ingest/service.py:71``). The mismatch meant real
    feature-flag signals fell through to the generic agentic-fallback
    profile and lost their specialised evidence + decision logic.

    This test pins the registry's signal_type keys to the actual values
    the rest of the codebase emits, so a future rename of either side
    has to update both.
    """

    SHIPPING_SIGNAL_TYPES: tuple[str, ...] = (
        # Emitted by services/ingest/bare_metal_node.py
        "reth_node",
        # Emitted by services/ingest/kubernetes_live_signal.py + ingest/service.py
        "kubernetes_deployment_issue",
        # Emitted by services/ingest/otel_signal.py
        "otel_metric_regression",
        # Emitted by services/ingest/webhook_service.py
        "webhook_alert",
        # Default in services/ingest/service.py:71 + services/trigger/service.py:68
        # when a payload omits ``signal_type``. The feature-flag profile MUST
        # match this exact string.
        "feature_flag",
    )

    def test_every_shipping_signal_type_resolves_to_concrete_profile(self) -> None:
        registry = build_default_registry()
        for signal_type in self.SHIPPING_SIGNAL_TYPES:
            profile = registry.get_or_generic(signal_type)
            self.assertNotEqual(
                profile.signal_type,
                GENERIC_PROFILE_KEY,
                f"signal_type={signal_type!r} fell through to the generic profile; "
                "either register a concrete profile for it or update SHIPPING_SIGNAL_TYPES.",
            )
            self.assertEqual(profile.signal_type, signal_type)


class DefaultRegistryShippingProfilesTests(unittest.TestCase):
    """Five concrete profiles register; their signal/trigger keys are
    distinct; the generic profile is reachable but not in the concrete
    set.
    """

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_all_five_concrete_profiles_present(self) -> None:
        expected = {
            "reth_node",
            "kubernetes_deployment_issue",
            "otel_metric_regression",
            "feature_flag",
            "webhook_alert",
        }
        self.assertEqual(set(self.registry.signal_types()), expected)

    def test_all_five_trigger_types_present(self) -> None:
        expected = {
            "reth_node_degraded",
            "kubernetes_deployment_unhealthy",
            "otel_metric_regression",
            "feature_flag_performance_regression",
            "webhook_alert_firing",
        }
        self.assertEqual(set(self.registry.trigger_types()), expected)

    def test_generic_profile_registered_separately(self) -> None:
        self.assertIsNotNone(self.registry.generic)
        # Not in the concrete-profile list (so we can't accidentally
        # register a real signal type with the sentinel name).
        self.assertNotIn(GENERIC_PROFILE_KEY, self.registry.signal_types())

    def test_every_concrete_profile_routes_through_get_for_trigger(self) -> None:
        # Verify the parallel index — every profile is reachable from
        # both directions.
        for profile in self.registry.profiles():
            by_trigger = self.registry.get_for_trigger(profile.trigger_type)
            self.assertIs(by_trigger, profile, profile.signal_type)


class PR1WiredStrategiesTests(unittest.TestCase):
    """PR 1 wires ``investigation_planner`` + ``rca_builder`` for every
    profile. These two strategies must NOT be ``NotYetWiredStrategy``
    placeholders, and they must produce contract-valid output.

    Other strategies (ingest/trigger/decision/scenario/feedback)
    are still placeholders until later PRs migrate them.
    """

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_every_profile_planner_is_wired(self) -> None:
        all_profiles = [*self.registry.profiles(), self.registry.generic]
        for profile in all_profiles:
            self.assertNotIsInstance(
                profile.investigation_planner,
                NotYetWiredStrategy,
                f"{profile.signal_type}: investigation_planner is still NotYetWiredStrategy",
            )

    def test_every_profile_rca_builder_is_wired(self) -> None:
        all_profiles = [*self.registry.profiles(), self.registry.generic]
        for profile in all_profiles:
            self.assertNotIsInstance(
                profile.rca_builder,
                NotYetWiredStrategy,
                f"{profile.signal_type}: rca_builder is still NotYetWiredStrategy",
            )

    def test_every_profile_planner_produces_contract_valid_plan(self) -> None:
        all_profiles = [*self.registry.profiles(), self.registry.generic]
        for profile in all_profiles:
            trigger = _make_trigger(profile.trigger_type)
            plan = profile.investigation_planner.plan(
                trigger=trigger, signal_payload={"signal_type": profile.signal_type}
            )
            self.assertIsInstance(plan, InvestigationPlan, profile.signal_type)
            self.assertEqual(plan.trigger_id, trigger.trigger_id)
            self.assertTrue(plan.plan_id, profile.signal_type)
            # validate() raises on schema violation — confirms contract conformance.
            plan.validate()

    def test_every_profile_rca_builder_produces_contract_valid_report(self) -> None:
        all_profiles = [*self.registry.profiles(), self.registry.generic]
        for profile in all_profiles:
            trigger = _make_trigger(profile.trigger_type)
            decision = _make_decision()
            report = profile.rca_builder.build(
                trigger=trigger,
                decision=decision,
                evidence_pack={"probe_results": [], "missing_fields": [], "sufficient": True},
            )
            self.assertIsInstance(report, RcaReport, profile.signal_type)
            self.assertEqual(report.trigger_id, trigger.trigger_id)
            report.validate()

    def test_every_profile_evidence_strategy_is_wired(self) -> None:
        all_profiles = [*self.registry.profiles(), self.registry.generic]
        for profile in all_profiles:
            self.assertNotIsInstance(
                profile.evidence_strategy,
                NotYetWiredStrategy,
                f"{profile.signal_type}: evidence_strategy is still NotYetWiredStrategy",
            )

    def test_non_migrated_strategies_are_still_placeholders(self) -> None:
        """Sanity check: the migration scaffold is still in place for
        the other 6 stages. Each PR removes some of these — when the
        full set is gone this test goes too.
        """
        unmigrated_fields = (
            "ingest_normalizer",
            "trigger_detector",
            "decision_strategy",
            "scenario_analyzer",
            "feedback_strategy",
        )
        for profile in [*self.registry.profiles(), self.registry.generic]:
            for field in unmigrated_fields:
                strategy = getattr(profile, field)
                self.assertIsInstance(
                    strategy,
                    NotYetWiredStrategy,
                    f"{profile.signal_type}.{field} unexpectedly migrated; update this test",
                )

    def test_placeholder_strategy_raises_on_call(self) -> None:
        """The placeholder MUST raise — silently no-op would defeat
        the whole point of invariant 1.
        """
        placeholder = self.registry.generic.ingest_normalizer
        with self.assertRaises(NotYetWired):
            placeholder.normalize({"signal_type": "unknown"})


class HarnessDrivenPlannerTests(unittest.TestCase):
    def test_harness_planner_emits_empty_but_valid_plan(self) -> None:
        planner = HarnessDrivenInvestigationPlanner(signal_type="test")
        trigger = _make_trigger()
        plan = planner.plan(trigger=trigger, signal_payload={"signal_type": "test"})
        self.assertEqual(plan.probes, [])
        self.assertEqual(plan.probe_budget["mode"], "harness_driven")
        plan.validate()


class HarnessDrivenRcaBuilderTests(unittest.TestCase):
    def test_harness_rca_with_no_hypotheses_emits_unknown_cause(self) -> None:
        builder = HarnessDrivenRcaBuilder()
        report = builder.build(
            trigger=_make_trigger(),
            decision=_make_decision(),
            evidence_pack={"probe_results": [], "missing_fields": [], "sufficient": True},
        )
        self.assertEqual(report.likely_cause, "unknown")
        report.validate()

    def test_harness_rca_extracts_top_hypothesis_when_present(self) -> None:
        builder = HarnessDrivenRcaBuilder()
        decision = _make_decision()
        decision.reasoning["ranked_hypotheses"] = [
            {
                "candidate_cause": "service_selector_mismatch",
                "posterior_confidence": 0.83,
                "supporting_evidence": ["service has zero matching pods"],
                "disconfirming_evidence": [],
            }
        ]
        report = builder.build(
            trigger=_make_trigger(),
            decision=decision,
            evidence_pack={"probe_results": [], "missing_fields": [], "sufficient": True},
        )
        self.assertEqual(report.likely_cause, "service_selector_mismatch")
        self.assertAlmostEqual(report.confidence, 0.83)
        self.assertIn("service has zero matching pods", report.supporting_evidence)
        report.validate()

    def test_harness_rca_records_fast_path_signatures_as_safety_reason(self) -> None:
        builder = HarnessDrivenRcaBuilder()
        report = builder.build(
            trigger=_make_trigger(),
            decision=_make_decision(),
            evidence_pack={
                "probe_results": [],
                "missing_fields": [],
                "sufficient": True,
                "fast_path_signatures": ["jwt_missing"],
            },
        )
        self.assertIn("jwt_missing", report.safety_reason)


if __name__ == "__main__":
    unittest.main()
