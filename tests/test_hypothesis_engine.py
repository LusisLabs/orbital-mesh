"""Tests for the HypothesisEngine — generation + falsification."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock

from services.decision.hypothesis_engine import (
    FalsificationPredicate,
    Hypothesis,
    HypothesisEngine,
)
from shared.mesh_runtime import Trigger
from shared.mesh_runtime.context_store import ContextStore
from shared.mesh_runtime.infra_graph import GraphEdge, GraphNode, InfraGraph, _node_key


def _make_trigger(
    *,
    service: str = "search",
    error_signatures: list[str] | None = None,
    related_context_extras: dict | None = None,
) -> Trigger:
    related = {
        "error_signatures": error_signatures or [],
        "deployment_name": "search-api",
        "namespace": "search",
        "rollout_status": "degraded",
        "event_reasons": [],
        "likely_layer": "application",
        "cluster": "test",
        "deployment_image": "registry/search:1.0",
    }
    if related_context_extras:
        related.update(related_context_extras)
    return Trigger(
        trigger_id="trig_test",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="2026-04-20T00:00:00Z",
        service=service,
        endpoint=f"deployment/{service}",
        environment="prod",
        flag_key="",
        current_rollout_pct=0,
        comparison_window={"start": "2026-04-20T00:00:00Z", "end": "2026-04-20T00:05:00Z"},
        segment={"customer_tier": "standard"},
        metrics={
            "baseline_p95_latency_ms": 100,
            "observed_p95_latency_ms": 100,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.01,
        },
        related_context=related,
    )


class HypothesisGenerationTests(unittest.TestCase):
    def test_crash_loop_generates_three_hypotheses(self):
        engine = HypothesisEngine()
        hypotheses = engine.generate(_make_trigger(error_signatures=["crash_loop"]))
        cause_labels = {h.candidate_cause for h in hypotheses}
        self.assertIn("recent_deploy", cause_labels)
        self.assertIn("config_change", cause_labels)
        self.assertIn("transient", cause_labels)

    def test_oom_killed_generates_hypotheses(self):
        engine = HypothesisEngine()
        hypotheses = engine.generate(_make_trigger(error_signatures=["oom_killed"]))
        actions = {h.recommended_action for h in hypotheses}
        self.assertIn("scale_deployment", actions)
        self.assertIn("rollback_deployment", actions)

    def test_unknown_signature_falls_back_to_escalate(self):
        engine = HypothesisEngine()
        hypotheses = engine.generate(_make_trigger(error_signatures=["exotic_panic"]))
        self.assertEqual(len(hypotheses), 1)
        self.assertEqual(hypotheses[0].recommended_action, "escalate")

    def test_multiple_signatures_merge_without_duplicates(self):
        engine = HypothesisEngine()
        hypotheses = engine.generate(_make_trigger(error_signatures=["crash_loop", "oom_killed"]))
        ids = [h.hypothesis_id for h in hypotheses]
        self.assertEqual(len(ids), len(set(ids)))  # no dupes

    def test_hypotheses_sorted_by_posterior_descending(self):
        engine = HypothesisEngine()
        hypotheses = engine.generate(_make_trigger(error_signatures=["crash_loop"]))
        posteriors = [h.posterior_confidence for h in hypotheses]
        self.assertEqual(posteriors, sorted(posteriors, reverse=True))


class FalsificationTests(unittest.TestCase):
    def test_recent_deploy_supported_from_signal_context(self):
        engine = HypothesisEngine()
        trigger = _make_trigger(
            error_signatures=["crash_loop"],
            related_context_extras={"recent_deploy_within_window": True},
        )
        hypotheses = engine.generate(trigger)
        # recent_deploy hypothesis should be boosted
        recent_deploy = next(h for h in hypotheses if h.candidate_cause == "recent_deploy")
        self.assertGreater(recent_deploy.posterior_confidence, recent_deploy.prior_confidence)

    def test_past_restart_success_supports_transient_hypothesis(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            context_store = ContextStore(tmp.name)
            # Seed: this service has restarted successfully before
            context_store.update_from_run({
                "run_id": "run_prior",
                "artifacts": {
                    "trigger": {"service": "search", "related_context": {}},
                    "decision": {"decision_type": "restart_deployment", "summary": "restart"},
                    "feedback": {"outcome": "successful"},
                },
            })
            engine = HypothesisEngine(context_store=context_store)
            trigger = _make_trigger(error_signatures=["crash_loop"])
            hypotheses = engine.generate(trigger)
            transient = next(h for h in hypotheses if h.candidate_cause == "transient")
            self.assertGreater(transient.posterior_confidence, transient.prior_confidence)
        finally:
            tmp.cleanup()

    def test_blast_wave_supports_registry_outage(self):
        engine = HypothesisEngine()
        trigger = _make_trigger(
            error_signatures=["image_pull_failure"],
            related_context_extras={"correlation": {"type": "blast_wave"}},
        )
        hypotheses = engine.generate(trigger)
        registry = next(h for h in hypotheses if h.candidate_cause == "registry_outage")
        self.assertGreater(registry.posterior_confidence, registry.prior_confidence)

    def test_upstream_dependency_predicate_uses_graph(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            graph = InfraGraph(tmp.name)
            nodes = [
                GraphNode(kind="namespace", name="search"),
                GraphNode(
                    kind="service",
                    name="search",
                    namespace="search",
                    attributes={"selector": {"app": "search"}},
                ),
                GraphNode(
                    kind="deployment",
                    name="search-api",
                    namespace="search",
                    attributes={"selector_labels": {"app": "search"}},
                ),
                GraphNode(kind="pod", name="search-pod", namespace="search", labels={"app": "search"}),
                GraphNode(kind="configmap", name="search-cfg", namespace="search"),
            ]
            edges = [
                GraphEdge(kind="exposes",
                          source=_node_key("service", "search", "search"),
                          target=_node_key("deployment", "search", "search-api")),
                GraphEdge(kind="owns",
                          source=_node_key("deployment", "search", "search-api"),
                          target=_node_key("pod", "search", "search-pod")),
                GraphEdge(kind="mounts",
                          source=_node_key("pod", "search", "search-pod"),
                          target=_node_key("configmap", "search", "search-cfg")),
            ]
            graph.update_snapshot(nodes, edges)
            engine = HypothesisEngine(infra_graph=graph)
            trigger = _make_trigger(
                error_signatures=["probe_failure"],
                related_context_extras={"namespace": "search"},
            )
            hypotheses = engine.generate(trigger)
            upstream = next(h for h in hypotheses if h.candidate_cause == "upstream_outage")
            # Upstream predicate should be supported since the graph has deps
            self.assertGreaterEqual(upstream.posterior_confidence, upstream.prior_confidence)
        finally:
            tmp.cleanup()


class PosteriorComputationTests(unittest.TestCase):
    def test_posterior_boosted_by_support(self):
        hypothesis = Hypothesis(
            hypothesis_id="h", description="", candidate_cause="x",
            recommended_action="restart_deployment", prior_confidence=0.5,
            predicates=[
                FalsificationPredicate(kind="k", result="supported", weight=1.0),
                FalsificationPredicate(kind="k2", result="supported", weight=1.0),
            ],
        )
        post = HypothesisEngine._posterior(hypothesis)
        self.assertGreater(post, 0.5)

    def test_posterior_reduced_by_disconfirm(self):
        hypothesis = Hypothesis(
            hypothesis_id="h", description="", candidate_cause="x",
            recommended_action="restart_deployment", prior_confidence=0.7,
            predicates=[
                FalsificationPredicate(kind="k", result="disconfirmed", weight=1.0),
            ],
        )
        post = HypothesisEngine._posterior(hypothesis)
        self.assertLess(post, 0.7)

    def test_posterior_clamped_to_upper_bound(self):
        hypothesis = Hypothesis(
            hypothesis_id="h", description="", candidate_cause="x",
            recommended_action="restart_deployment", prior_confidence=0.95,
            predicates=[
                FalsificationPredicate(kind=f"k{i}", result="supported", weight=5.0)
                for i in range(5)
            ],
        )
        post = HypothesisEngine._posterior(hypothesis)
        self.assertLessEqual(post, 0.95)

    def test_posterior_clamped_to_lower_bound(self):
        hypothesis = Hypothesis(
            hypothesis_id="h", description="", candidate_cause="x",
            recommended_action="restart_deployment", prior_confidence=0.10,
            predicates=[
                FalsificationPredicate(kind=f"k{i}", result="disconfirmed", weight=5.0)
                for i in range(5)
            ],
        )
        post = HypothesisEngine._posterior(hypothesis)
        self.assertGreaterEqual(post, 0.05)


class DecisionServiceIntegrationTests(unittest.TestCase):
    """Verify the hypothesis engine upgrades escalate but never overrides concrete decisions."""

    def test_hypothesis_upgrades_escalate_fallback(self):
        """Unknown error signature → rule says escalate → hypothesis with concrete action upgrades."""
        from services.decision.service import DecisionService

        mock_engine = MagicMock()
        mock_engine.generate.return_value = [
            Hypothesis(
                hypothesis_id="h",
                description="upgrade hypothesis",
                candidate_cause="transient",
                recommended_action="restart_deployment",
                prior_confidence=0.60,
                posterior_confidence=0.70,
            ),
        ]
        svc = DecisionService(hypothesis_engine=mock_engine)
        trigger = _make_trigger(error_signatures=["exotic_panic"])
        decision = svc._decide_kubernetes(trigger)
        # Rule engine would have escalated; hypothesis upgrades to restart
        self.assertEqual(decision.decision_type, "restart_deployment")
        self.assertTrue(
            decision.reasoning["evidence_pack"]["hypothesis_upgrade_applied"]
        )

    def test_hypothesis_does_not_override_concrete_rule(self):
        """Crash loop + recent deploy → rule says rollback → hypothesis cannot override.

        The SRE-grade policy routes crash_loop with deploy correlation
        to ``rollback_deployment``. The invariant being exercised is
        that the rule engine's concrete decision is not overridden by
        the hypothesis engine. We use a hypothesis that proposes
        ``restart_pod`` (different from the rule's rollback) so a buggy
        override would be detectable.
        """
        from services.decision.service import DecisionService

        mock_engine = MagicMock()
        mock_engine.generate.return_value = [
            Hypothesis(
                hypothesis_id="h",
                description="",
                candidate_cause="config_change",
                recommended_action="restart_pod",  # would override rollback if allowed
                prior_confidence=0.85,
                posterior_confidence=0.90,
            ),
        ]
        svc = DecisionService(hypothesis_engine=mock_engine)
        trigger = _make_trigger(
            error_signatures=["crash_loop"],
            related_context_extras={"seconds_since_deploy": 120},
        )
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "rollback_deployment")
        self.assertFalse(
            decision.reasoning["evidence_pack"]["hypothesis_upgrade_applied"]
        )

    def test_hypotheses_recorded_in_reasoning(self):
        from services.decision.service import DecisionService

        mock_engine = MagicMock()
        mock_engine.generate.return_value = [
            Hypothesis(
                hypothesis_id="h1", description="d1", candidate_cause="x",
                recommended_action="restart_deployment",
                prior_confidence=0.5, posterior_confidence=0.55,
            ),
        ]
        svc = DecisionService(hypothesis_engine=mock_engine)
        trigger = _make_trigger(error_signatures=["crash_loop"])
        decision = svc._decide_kubernetes(trigger)
        hypotheses = decision.reasoning["evidence_pack"]["hypotheses"]
        self.assertEqual(len(hypotheses), 1)
        self.assertEqual(hypotheses[0]["hypothesis_id"], "h1")

    def test_low_posterior_does_not_upgrade_escalate(self):
        """If hypothesis confidence is low, stay at escalate."""
        from services.decision.service import DecisionService

        mock_engine = MagicMock()
        mock_engine.generate.return_value = [
            Hypothesis(
                hypothesis_id="h",
                description="",
                candidate_cause="transient",
                recommended_action="restart_deployment",
                prior_confidence=0.30,
                posterior_confidence=0.45,  # below 0.55 threshold
            ),
        ]
        svc = DecisionService(hypothesis_engine=mock_engine)
        trigger = _make_trigger(error_signatures=["exotic_panic"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "escalate")
        self.assertFalse(
            decision.reasoning["evidence_pack"]["hypothesis_upgrade_applied"]
        )


if __name__ == "__main__":
    unittest.main()
