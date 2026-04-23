"""Tests for the metric-action rule engine and its integration with the pipeline.

Coverage is intentionally broad here because the rule engine is the extension
point operators interact with — a bug in matching or rendering silently causes
the wrong action to run in production. The tests fall into four groups:

1. **Rule loading and validation** — bad rule files should fail at startup.
2. **Matcher semantics** — every documented match condition has a test that
   exercises both the hit and miss cases.
3. **Parameter rendering** — placeholders resolve correctly against the
   signal, including OTel attribute keys with dots.
4. **End-to-end** — an OTel payload flows through ingest → trigger →
   decision → actuator and produces the expected ``scale_deployment``
   execution plan.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.actuators.service import KubernetesAdapter
from services.decision.service import DecisionService
from services.ingest.otel_signal import AlertContext, OtlpPushIngester
from services.ingest.service import IngestService
from services.trigger.service import TriggerService
from shared.mesh_runtime.metric_action_rules import (
    MetricActionMatcher,
    MetricActionRule,
    load_metric_action_rules,
)


def _signal(
    *,
    metric_name: str,
    baseline: float,
    observed: float,
    deployment: str = "checkout",
    namespace: str = "default",
    cluster: str = "prod-east",
    service: str = "checkout-api",
    extra_attrs: dict | None = None,
) -> dict:
    """Helper: build a synthetic otel_metric_regression signal for matcher tests."""
    resource_attrs = {
        "service.name": service,
        "deployment.environment": "production",
        "k8s.deployment.name": deployment,
        "k8s.namespace.name": namespace,
        "k8s.cluster.name": cluster,
    }
    if extra_attrs:
        resource_attrs.update(extra_attrs)
    delta = ((observed - baseline) / baseline * 100.0) if baseline else None
    return {
        "signal_type": "otel_metric_regression",
        "signal_id": "sig_test",
        "observed_at": "2026-04-22T10:00:00Z",
        "environment": "production",
        "service": service,
        "endpoint": metric_name,
        "cluster": cluster,
        "namespace": namespace,
        "source": "otlp_push",
        "comparison_window": {"baseline": "2026-04-22T09:00:00Z", "observed": "2026-04-22T10:00:00Z"},
        "segment": {"customer_tier": "system", "region": "us-east-1"},
        "metric_regression": {
            "metric_name": metric_name,
            "metric_kind": "gauge",
            "unit": None,
            "baseline_value": baseline,
            "observed_value": observed,
            "delta_pct": round(delta, 2) if delta is not None else None,
            "threshold_pct": None,
            "attributes": {},
        },
        "resource_attributes": resource_attrs,
        "related_metrics": [],
        "related_context": {},
        "post_action_observations": {},
    }


# ---------------------------------------------------------------------- loading


class RuleLoadingTests(unittest.TestCase):
    def test_loads_starter_policy_without_error(self) -> None:
        """The shipped starter policy must parse and compile cleanly — otherwise
        every production deployment would fail at startup."""
        load_metric_action_rules.cache_clear()
        matcher = load_metric_action_rules(None)  # resolves to default policy path
        self.assertGreaterEqual(len(matcher.rules), 1)

    def test_missing_file_returns_empty_matcher(self) -> None:
        """Feature is opt-in: no policy file means no rules, no behavior change."""
        load_metric_action_rules.cache_clear()
        matcher = load_metric_action_rules("/nonexistent/policy.json")
        self.assertEqual(matcher.rules, [])

    def test_invalid_regex_fails_at_load_time(self) -> None:
        """A malformed pattern should be caught during startup, not the first
        inbound signal when nobody's watching."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(
                {
                    "rules": [
                        {
                            "name": "bad regex",
                            "match": {"metric_name_pattern": "[unclosed"},
                            "propose": {
                                "decision_type": "no_action",
                                "system": "audit_log_sink",
                                "action": "record_no_action",
                                "parameters": {},
                            },
                        }
                    ]
                },
                handle,
            )
            path = handle.name
        try:
            load_metric_action_rules.cache_clear()
            with self.assertRaises(ValueError):
                load_metric_action_rules(path)
        finally:
            Path(path).unlink()

    def test_rule_validates_required_propose_keys(self) -> None:
        """propose must have decision_type, system, action, parameters."""
        with self.assertRaises(ValueError):
            MetricActionRule(name="incomplete", match={}, propose={"decision_type": "no_action"})


# ---------------------------------------------------------------------- matching


class MatcherSemanticsTests(unittest.TestCase):
    def _scale_rule(self) -> MetricActionRule:
        return MetricActionRule(
            name="scale on lag",
            match={
                "metric_name_pattern": "consumer_lag",
                "direction": "increasing",
                "delta_pct_min": 30,
                "resource_attributes": {"k8s.deployment.name": "*"},
            },
            propose={
                "decision_type": "scale_deployment",
                "system": "kubernetes_service",
                "action": "scale_deployment",
                "parameters": {
                    "deployment_name": "{resource_attributes.k8s.deployment.name}",
                    "namespace": "{resource_attributes.k8s.namespace.name}",
                    "replicas_delta": 2,
                },
            },
            bounds={"replicas_delta_max": 3},
            confidence=0.8,
            risk_level="low",
            rollback_plan="scale back",
        )

    def test_matches_on_name_pattern_and_delta(self) -> None:
        matcher = MetricActionMatcher(rules=[self._scale_rule()])
        signal = _signal(metric_name="kafka.consumer_lag", baseline=100, observed=200)
        result = matcher.match(signal)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision_type, "scale_deployment")
        self.assertEqual(result.parameters["deployment_name"], "checkout")
        self.assertEqual(result.parameters["replicas_delta"], 2)

    def test_missing_delta_skips_rule_with_delta_bound(self) -> None:
        """A bound without a delta means we can't confirm — skip. False positives
        are worse than missing a noisy signal."""
        matcher = MetricActionMatcher(rules=[self._scale_rule()])
        signal = _signal(metric_name="kafka.consumer_lag", baseline=0, observed=200)
        # baseline=0 produces delta_pct=None
        signal["metric_regression"]["delta_pct"] = None
        self.assertIsNone(matcher.match(signal))

    def test_wildcard_requires_key_presence(self) -> None:
        """``"*"`` means 'key must exist', not 'equals the literal star'."""
        matcher = MetricActionMatcher(rules=[self._scale_rule()])
        signal = _signal(metric_name="kafka.consumer_lag", baseline=100, observed=200)
        signal["resource_attributes"].pop("k8s.deployment.name")
        self.assertIsNone(matcher.match(signal))

    def test_delta_below_threshold_does_not_match(self) -> None:
        matcher = MetricActionMatcher(rules=[self._scale_rule()])
        # +10% < 30% threshold
        signal = _signal(metric_name="kafka.consumer_lag", baseline=100, observed=110)
        self.assertIsNone(matcher.match(signal))

    def test_first_matching_rule_wins(self) -> None:
        """Rule order in the registry is the tiebreaker — operators put specific
        rules first to get predictable behavior."""
        specific = MetricActionRule(
            name="specific checkout rule",
            match={"resource_attributes": {"k8s.deployment.name": "checkout"}},
            propose={
                "decision_type": "no_action",
                "system": "audit_log_sink",
                "action": "record_no_action",
                "parameters": {},
            },
        )
        matcher = MetricActionMatcher(rules=[specific, self._scale_rule()])
        signal = _signal(metric_name="kafka.consumer_lag", baseline=100, observed=200)
        result = matcher.match(signal)
        self.assertEqual(result.rule_name, "specific checkout rule")

    def test_clamps_replicas_delta_to_bound(self) -> None:
        """Rule authors can't accidentally ship a proposal that exceeds their
        own stated bound — the engine enforces at render time."""
        rule = self._scale_rule()
        rule.propose["parameters"]["replicas_delta"] = 10  # rule says +10
        rule.bounds["replicas_delta_max"] = 3                # bounds cap at +3
        matcher = MetricActionMatcher(rules=[rule])
        signal = _signal(metric_name="kafka.consumer_lag", baseline=100, observed=200)
        result = matcher.match(signal)
        self.assertEqual(result.parameters["replicas_delta"], 3)


# -------------------------------------------------------------------- rendering


class ParameterRenderingTests(unittest.TestCase):
    """Placeholder rendering has real sharp edges because OTel attribute keys
    contain dots (``k8s.deployment.name``) which collide with our path
    separator. These tests lock down the greedy-longest-match behavior."""

    def _rule_with_template(self, template: str) -> MetricActionMatcher:
        return MetricActionMatcher(
            rules=[
                MetricActionRule(
                    name="render test",
                    match={"metric_name_pattern": ".*"},
                    propose={
                        "decision_type": "no_action",
                        "system": "audit_log_sink",
                        "action": "record_no_action",
                        "parameters": {"rendered": template},
                    },
                )
            ]
        )

    def test_resolves_dotted_otel_attribute_key(self) -> None:
        matcher = self._rule_with_template("{resource_attributes.k8s.namespace.name}")
        signal = _signal(metric_name="x", baseline=1, observed=2, namespace="payments")
        result = matcher.match(signal)
        self.assertEqual(result.parameters["rendered"], "payments")

    def test_missing_attribute_renders_empty(self) -> None:
        """Missing values render as empty strings. Better to ship an actionable
        proposal with a visible empty field than silently drop the parameter."""
        matcher = self._rule_with_template("{resource_attributes.k8s.ghost.key}")
        signal = _signal(metric_name="x", baseline=1, observed=2)
        result = matcher.match(signal)
        self.assertEqual(result.parameters["rendered"], "")

    def test_top_level_signal_field(self) -> None:
        matcher = self._rule_with_template("{service}/{endpoint}")
        signal = _signal(metric_name="lag", baseline=1, observed=2, service="orders-api")
        result = matcher.match(signal)
        self.assertEqual(result.parameters["rendered"], "orders-api/lag")


# -------------------------------------------------------------- end-to-end flow


class EndToEndPipelineTests(unittest.TestCase):
    """Drive the full ingest → trigger → decision → actuator flow so a rule
    change in ``policies/metric-actions.policy.json`` is caught by CI before
    it reaches a deployment."""

    def _ingest_signal(self, raw: dict):
        envelope = IngestService().normalize_signal(raw)
        return envelope

    def test_scale_rule_produces_scale_decision_and_actuator_call(self) -> None:
        # An OTLP payload arrives — consumer lag climbed 100%.
        otlp_payload = {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "checkout-api"}},
                            {"key": "deployment.environment", "value": {"stringValue": "production"}},
                            {"key": "k8s.deployment.name", "value": {"stringValue": "checkout"}},
                            {"key": "k8s.namespace.name", "value": {"stringValue": "default"}},
                            {"key": "k8s.cluster.name", "value": {"stringValue": "prod-east"}},
                        ]
                    },
                    "scopeMetrics": [
                        {
                            "scope": {"name": "kafka"},
                            "metrics": [
                                {
                                    "name": "kafka.consumer_lag",
                                    "gauge": {
                                        "dataPoints": [
                                            {"asDouble": 100.0, "timeUnixNano": "1", "attributes": []},
                                            {"asDouble": 300.0, "timeUnixNano": "2", "attributes": []},
                                        ]
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        signal = OtlpPushIngester().build_signal(
            otlp_payload,
            alert_context=AlertContext(metric_name="kafka.consumer_lag", baseline_value=100.0),
        )

        envelope = self._ingest_signal(signal)
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.trigger_type, "otel_metric_regression")

        # Load the real shipped policy — if it regresses this test fails.
        load_metric_action_rules.cache_clear()
        decision = DecisionService().decide(trigger)
        self.assertEqual(decision.decision_type, "scale_deployment")
        self.assertEqual(decision.execution_plan["system"], "kubernetes_service")
        self.assertEqual(decision.execution_plan["action"], "scale_deployment")
        self.assertEqual(decision.execution_plan["parameters"]["deployment_name"], "checkout")
        self.assertEqual(decision.execution_plan["parameters"]["namespace"], "default")

        # Mock-mode actuator returns succeeded with the target in external_refs.
        result = KubernetesAdapter().scale_deployment(decision.execution_plan["parameters"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["external_refs"]["rollout_action"], "scale_deployment")

    def test_unmatched_metric_escalates(self) -> None:
        """A metric with no matching rule must escalate — silently absorbing
        into no_action would make Mesh ingest alerts and do nothing."""
        signal = _signal(
            metric_name="mystery.custom.metric.with.no.rule",
            baseline=10,
            observed=100,
        )
        envelope = self._ingest_signal(signal)
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)

        load_metric_action_rules.cache_clear()
        decision = DecisionService().decide(trigger)
        self.assertEqual(decision.decision_type, "escalate")
        self.assertEqual(decision.execution_plan["system"], "incident_service")


if __name__ == "__main__":
    unittest.main()
