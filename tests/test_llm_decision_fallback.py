"""Tests for the Layer 3 LLM decision fallback.

The LLM path is tested by stubbing ``LlmActionProposer._invoke_goose`` — we
never want unit tests to spawn a real Goose subprocess. Tests cover:

1. The proposer's validator: allowlist enforcement, bound clamping, missing
   parameter detection, malformed JSON tolerance.
2. Integration with ``DecisionService``: that an enabled fallback produces a
   valid Decision when the LLM cooperates, and falls through to escalate
   when it doesn't.
3. The config gate: fallback stays off when the config flag is unset, even
   if a proposer is passed in.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from services.decision.llm_fallback import LlmActionProposer
from services.decision.service import DecisionService
from services.trigger.service import TriggerService
from services.ingest.service import IngestService
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.metric_action_rules import load_metric_action_rules


# Reuse the signal helper shape from the metric-action test.
def _unknown_signal(metric_name: str = "mystery.custom.rate", baseline: float = 10.0, observed: float = 50.0) -> dict:
    delta = (observed - baseline) / baseline * 100.0
    return {
        "signal_type": "otel_metric_regression",
        "signal_id": "sig_unknown",
        "observed_at": "2026-04-22T10:00:00Z",
        "environment": "production",
        "service": "mystery-service",
        "endpoint": metric_name,
        "cluster": "prod-east",
        "namespace": "default",
        "source": "otlp_push",
        "comparison_window": {"baseline": "2026-04-22T09:00:00Z", "observed": "2026-04-22T10:00:00Z"},
        "segment": {"customer_tier": "system", "region": "us-east-1"},
        "metric_regression": {
            "metric_name": metric_name,
            "metric_kind": "gauge",
            "unit": None,
            "baseline_value": baseline,
            "observed_value": observed,
            "delta_pct": round(delta, 2),
            "threshold_pct": None,
            "attributes": {},
        },
        "resource_attributes": {
            "service.name": "mystery-service",
            "deployment.environment": "production",
            "k8s.deployment.name": "mystery",
            "k8s.namespace.name": "default",
            "k8s.cluster.name": "prod-east",
        },
        "related_metrics": [],
        "related_context": {},
        "post_action_observations": {},
    }


def _llm_config(enabled: bool = True) -> RuntimeConfig:
    """Build a RuntimeConfig suitable for LLM fallback tests.

    ``goose_command`` must be set for the proposer to try calling it. Tests
    stub the subprocess call, so the actual value doesn't matter as long as
    it's truthy — the config gate treats ``None`` as "goose unavailable".
    """
    return replace(
        RuntimeConfig(),
        llm_decision_fallback_enabled=enabled,
        goose_command="goose",
        llm_decision_fallback_timeout_seconds=5.0,
    )


def _goose_json_reply(parsed: dict) -> str:
    """Wrap a parsed proposal as goose's ``--output-format json`` stdout.

    This mirrors the shape ``_extract_assistant_text`` expects: a top-level
    ``messages`` array with the final assistant message carrying the JSON.
    """
    return json.dumps(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": json.dumps(parsed)}],
                }
            ]
        }
    )


# ----------------------------------------------------------------------- validator


class ValidatorTests(unittest.TestCase):
    """Exercise validation in isolation by stubbing subprocess.run."""

    def _propose(self, fake_response: str, config: RuntimeConfig | None = None):
        proposer = LlmActionProposer(config or _llm_config())
        with patch.object(proposer, "_invoke_goose", return_value=fake_response):
            return proposer.propose(_unknown_signal())

    def test_accepts_well_formed_scale_proposal(self) -> None:
        result = self._propose(
            json.dumps(
                {
                    "decision_type": "scale_deployment",
                    "system": "kubernetes_service",
                    "action": "scale_deployment",
                    "parameters": {
                        "deployment_name": "mystery",
                        "namespace": "default",
                        "replicas": 4,
                    },
                    "confidence": 0.7,
                    "risk_level": "low",
                    "rollback_plan": "scale back",
                    "reasoning": "looks like a backlog",
                }
            )
        )
        self.assertIsNotNone(result.match)
        self.assertEqual(result.match.decision_type, "scale_deployment")
        self.assertEqual(result.match.parameters["replicas"], 4)

    def test_rejects_action_outside_allowlist(self) -> None:
        """LLM proposes something not in the table — must reject, not pass through."""
        result = self._propose(
            json.dumps(
                {
                    "decision_type": "delete_everything",
                    "system": "kubernetes_service",
                    "action": "delete_everything",
                    "parameters": {"namespace": "default"},
                    "confidence": 0.9,
                    "risk_level": "high",
                    "rollback_plan": "panic",
                }
            )
        )
        self.assertIsNone(result.match)
        self.assertIn("llm_action_not_allowed", result.risk_flags)

    def test_rejects_missing_required_parameters(self) -> None:
        """scale_deployment requires deployment_name + namespace — missing one fails."""
        result = self._propose(
            json.dumps(
                {
                    "decision_type": "scale_deployment",
                    "system": "kubernetes_service",
                    "action": "scale_deployment",
                    "parameters": {"deployment_name": "mystery"},  # no namespace
                    "confidence": 0.7,
                    "risk_level": "low",
                    "rollback_plan": "scale back",
                }
            )
        )
        self.assertIsNone(result.match)
        self.assertIn("llm_missing_parameter", result.risk_flags)

    def test_clamps_out_of_bound_replicas(self) -> None:
        """LLM proposes 100 replicas — spec caps at 50. Must clamp and flag, not reject."""
        result = self._propose(
            json.dumps(
                {
                    "decision_type": "scale_deployment",
                    "system": "kubernetes_service",
                    "action": "scale_deployment",
                    "parameters": {
                        "deployment_name": "mystery",
                        "namespace": "default",
                        "replicas": 100,
                    },
                    "confidence": 0.9,
                    "risk_level": "medium",
                    "rollback_plan": "scale back",
                }
            )
        )
        self.assertIsNotNone(result.match)
        self.assertEqual(result.match.parameters["replicas"], 50)
        self.assertIn("llm_bound_clamped", result.risk_flags)

    def test_drops_unknown_parameter_keys_silently(self) -> None:
        """LLM adds a parameter not in the spec — silently drop, don't fail the decision."""
        result = self._propose(
            json.dumps(
                {
                    "decision_type": "scale_deployment",
                    "system": "kubernetes_service",
                    "action": "scale_deployment",
                    "parameters": {
                        "deployment_name": "mystery",
                        "namespace": "default",
                        "replicas": 3,
                        "some_made_up_field": "wat",
                    },
                    "confidence": 0.6,
                    "risk_level": "low",
                    "rollback_plan": "scale back",
                }
            )
        )
        self.assertIsNotNone(result.match)
        self.assertNotIn("some_made_up_field", result.match.parameters)

    def test_tolerates_fenced_json_response(self) -> None:
        """LLM wraps output in ``` fences despite instructions — parser unwraps them."""
        fenced = "```json\n" + json.dumps(
            {
                "decision_type": "open_incident",
                "system": "incident_service",
                "action": "open_incident",
                "parameters": {"service": "mystery-service", "severity": "medium"},
                "confidence": 0.5,
                "risk_level": "medium",
                "rollback_plan": "close it",
            }
        ) + "\n```"
        # Goose wrapper would have produced: messages with fenced text
        wrapper = json.dumps({
            "messages": [{"role": "assistant", "content": [{"type": "text", "text": fenced}]}]
        })
        result = self._propose(_extract_text(wrapper))
        self.assertIsNotNone(result.match)
        self.assertEqual(result.match.action, "open_incident")

    def test_invalid_json_returns_risk_flag(self) -> None:
        result = self._propose("this is not json at all")
        self.assertIsNone(result.match)
        self.assertIn("llm_invalid_json", result.risk_flags)

    def test_confidence_caps_at_point_85(self) -> None:
        """Even if the LLM claims 0.99, we cap at 0.85 — no determinism, no max confidence."""
        result = self._propose(
            json.dumps(
                {
                    "decision_type": "scale_deployment",
                    "system": "kubernetes_service",
                    "action": "scale_deployment",
                    "parameters": {
                        "deployment_name": "mystery",
                        "namespace": "default",
                        "replicas": 3,
                    },
                    "confidence": 0.99,
                    "risk_level": "low",
                    "rollback_plan": "scale back",
                }
            )
        )
        self.assertIsNotNone(result.match)
        self.assertLessEqual(result.match.confidence, 0.85)


def _extract_text(wrapper: str) -> str:
    """Mirror what _invoke_goose does when the subprocess returns wrapped output.

    Used in tests where we want to simulate goose's own JSON shape rather
    than the bare assistant text.
    """
    from services.decision.llm_fallback import _extract_assistant_text
    return _extract_assistant_text(wrapper)


# ---------------------------------------------------------------- config gating


class ConfigGatingTests(unittest.TestCase):
    def test_disabled_config_does_not_invoke_subprocess(self) -> None:
        """Even if a proposer is constructed, it must no-op when disabled."""
        proposer = LlmActionProposer(_llm_config(enabled=False))
        with patch.object(proposer, "_invoke_goose") as fake_invoke:
            result = proposer.propose(_unknown_signal())
        self.assertIsNone(result.match)
        self.assertIn("llm_fallback_disabled", result.risk_flags)
        fake_invoke.assert_not_called()

    def test_missing_goose_command_returns_goose_unavailable(self) -> None:
        config = replace(_llm_config(), goose_command=None)
        proposer = LlmActionProposer(config)
        result = proposer.propose(_unknown_signal())
        self.assertIsNone(result.match)
        self.assertIn("goose_unavailable", result.risk_flags)


# -------------------------------------------------------------- DecisionService


class DecisionIntegrationTests(unittest.TestCase):
    def test_llm_match_produces_decision(self) -> None:
        """When the LLM returns a valid proposal, the decision carries it."""
        proposer = LlmActionProposer(_llm_config())
        fake_response = _goose_json_reply(
            {
                "decision_type": "scale_deployment",
                "system": "kubernetes_service",
                "action": "scale_deployment",
                "parameters": {
                    "deployment_name": "mystery",
                    "namespace": "default",
                    "replicas": 4,
                },
                "confidence": 0.7,
                "risk_level": "low",
                "rollback_plan": "scale back",
                "reasoning": "backlog-shaped signal",
            }
        )
        envelope = IngestService().normalize_signal(_unknown_signal())
        trigger = TriggerService().detect(envelope)
        load_metric_action_rules.cache_clear()
        service = DecisionService(llm_proposer=proposer)
        with patch("subprocess.run") as fake_run:
            fake_run.return_value.returncode = 0
            fake_run.return_value.stdout = fake_response
            fake_run.return_value.stderr = ""
            decision = service.decide(trigger)
        self.assertEqual(decision.decision_type, "scale_deployment")
        self.assertEqual(decision.execution_plan["action"], "scale_deployment")
        # The decision carries the LLM risk flags in its evidence list so
        # operators can see where the proposal came from.
        evidence = decision.reasoning["evidence"]
        self.assertTrue(any("llm" in item.lower() or "rule" in item.lower() for item in evidence))

    def test_llm_timeout_escalates_with_flag(self) -> None:
        """Timeout must escalate — never silently absorb."""
        proposer = LlmActionProposer(_llm_config())
        envelope = IngestService().normalize_signal(_unknown_signal())
        trigger = TriggerService().detect(envelope)
        load_metric_action_rules.cache_clear()
        service = DecisionService(llm_proposer=proposer)
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("goose", 5)):
            decision = service.decide(trigger)
        self.assertEqual(decision.decision_type, "escalate")
        # The escalation reasoning must name the timeout so operators see why
        # the LLM didn't contribute, rather than thinking the rule just wasn't authored.
        self.assertIn("llm_timeout", decision.reasoning["evidence_pack"]["llm_risk_flags"])


if __name__ == "__main__":
    unittest.main()
