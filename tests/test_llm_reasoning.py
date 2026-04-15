"""Tests for the EscalationReasoner — LLM-backed reasoning for novel scenarios."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from services.decision.llm_reasoning import (
    ALLOWED_ACTIONS,
    EscalationReasoner,
    ReasoningResult,
    _default_escalate,
    _parse_json_from_text,
)


def _mock_config(**overrides):
    cfg = MagicMock()
    cfg.llm_escalation_enabled = True
    cfg.llm_escalation_provider = "goose"
    cfg.llm_escalation_model = None
    cfg.llm_escalation_timeout_seconds = 30
    cfg.goose_command = "/usr/bin/goose"
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _mock_trigger(
    service="search",
    trigger_type="kubernetes_deployment_unhealthy",
    related_context=None,
):
    trigger = MagicMock()
    trigger.service = service
    trigger.trigger_type = trigger_type
    trigger.related_context = related_context or {
        "deployment_name": "search-api",
        "namespace": "search",
        "error_signatures": ["crash_loop"],
        "rollout_status": "degraded",
    }
    return trigger


class TestReasoningResult(unittest.TestCase):
    def test_to_dict(self):
        result = ReasoningResult(
            suggested_action="restart_deployment",
            confidence=0.82,
            reasoning_chain=["pods crashing", "restart likely to fix"],
            risk_assessment="low",
        )
        d = result.to_dict()
        self.assertEqual(d["suggested_action"], "restart_deployment")
        self.assertEqual(d["confidence"], 0.82)
        self.assertEqual(len(d["reasoning_chain"]), 2)
        self.assertNotIn("raw_response", d)

    def test_default_escalate(self):
        result = _default_escalate()
        self.assertEqual(result.suggested_action, "escalate")
        self.assertEqual(result.confidence, 0.0)


class TestParseJsonFromText(unittest.TestCase):
    def test_clean_json(self):
        text = '{"suggested_action": "restart_deployment", "confidence": 0.8}'
        parsed = _parse_json_from_text(text)
        self.assertEqual(parsed["suggested_action"], "restart_deployment")

    def test_fenced_json(self):
        text = 'Here is my answer:\n```json\n{"suggested_action": "rollback_deployment"}\n```'
        parsed = _parse_json_from_text(text)
        self.assertEqual(parsed["suggested_action"], "rollback_deployment")

    def test_embedded_json(self):
        text = 'Based on analysis: {"suggested_action": "no_action", "confidence": 0.7} done.'
        parsed = _parse_json_from_text(text)
        self.assertEqual(parsed["suggested_action"], "no_action")

    def test_invalid_text(self):
        self.assertIsNone(_parse_json_from_text("no json here"))


class TestEscalationReasoner(unittest.TestCase):
    def test_returns_default_when_goose_not_configured(self):
        config = _mock_config(goose_command=None)
        reasoner = EscalationReasoner(config)
        result = reasoner.reason(_mock_trigger())
        self.assertEqual(result.suggested_action, "escalate")
        self.assertEqual(result.confidence, 0.0)

    @patch("services.decision.llm_reasoning.subprocess.run")
    def test_parses_valid_goose_response(self, mock_run):
        goose_response = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "suggested_action": "restart_deployment",
                                "confidence": 0.82,
                                "reasoning_chain": ["pods in crash loop", "restart should clear transient state"],
                                "risk_assessment": "low — single deployment restart",
                            }),
                        }
                    ],
                }
            ]
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(goose_response))
        config = _mock_config()
        reasoner = EscalationReasoner(config)
        result = reasoner.reason(_mock_trigger())
        self.assertEqual(result.suggested_action, "restart_deployment")
        self.assertAlmostEqual(result.confidence, 0.82)
        self.assertEqual(len(result.reasoning_chain), 2)

    @patch("services.decision.llm_reasoning.subprocess.run")
    def test_rejects_disallowed_action(self, mock_run):
        goose_response = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "suggested_action": "delete_namespace",
                                "confidence": 0.99,
                                "reasoning_chain": ["nuke it"],
                                "risk_assessment": "yolo",
                            }),
                        }
                    ],
                }
            ]
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(goose_response))
        config = _mock_config()
        reasoner = EscalationReasoner(config)
        result = reasoner.reason(_mock_trigger())
        self.assertEqual(result.suggested_action, "escalate")
        self.assertEqual(result.confidence, 0.0)
        self.assertIn("disallowed", result.reasoning_chain[0])

    @patch("services.decision.llm_reasoning.subprocess.run")
    def test_clamps_confidence(self, mock_run):
        goose_response = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "suggested_action": "restart_deployment",
                                "confidence": 5.0,
                                "reasoning_chain": [],
                                "risk_assessment": "low",
                            }),
                        }
                    ],
                }
            ]
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(goose_response))
        config = _mock_config()
        reasoner = EscalationReasoner(config)
        result = reasoner.reason(_mock_trigger())
        self.assertLessEqual(result.confidence, 1.0)

    @patch("services.decision.llm_reasoning.subprocess.run")
    def test_handles_goose_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="timeout")
        config = _mock_config()
        reasoner = EscalationReasoner(config)
        result = reasoner.reason(_mock_trigger())
        self.assertEqual(result.suggested_action, "escalate")

    @patch("services.decision.llm_reasoning.subprocess.run")
    def test_handles_subprocess_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="goose", timeout=30)
        config = _mock_config()
        reasoner = EscalationReasoner(config)
        result = reasoner.reason(_mock_trigger())
        self.assertEqual(result.suggested_action, "escalate")

    def test_prompt_includes_context_store_data(self):
        config = _mock_config(goose_command=None)
        context_store = MagicMock()
        context_store.get_service_context.return_value = {
            "total_runs": 10,
            "success_rate": 0.8,
            "common_error_patterns": ["crash_loop", "oom_killed"],
        }
        context_store.get_similar_incidents.return_value = [
            {"decision_type": "restart_deployment", "outcome": "successful", "error_signature": "crash_loop"},
        ]
        reasoner = EscalationReasoner(config, context_store=context_store)
        prompt = reasoner._build_prompt(_mock_trigger())
        self.assertIn("Total runs: 10", prompt)
        self.assertIn("Success rate: 0.8", prompt)
        self.assertIn("restart_deployment", prompt)

    def test_prompt_includes_learning_store_data(self):
        config = _mock_config(goose_command=None)
        learning_store = MagicMock()
        learning_store.get_historical_success_rate.side_effect = lambda action, svc: (
            0.9 if action == "restart_deployment" else None
        )
        learning_store.get_recovery_patterns.return_value = {"restart_clears_oom": 3}
        reasoner = EscalationReasoner(config, learning_store=learning_store)
        prompt = reasoner._build_prompt(_mock_trigger())
        self.assertIn("restart_deployment: 90%", prompt)
        self.assertIn("restart_clears_oom", prompt)

    def test_unsupported_provider_returns_default(self):
        config = _mock_config(llm_escalation_provider="unsupported_llm")
        reasoner = EscalationReasoner(config)
        result = reasoner.reason(_mock_trigger())
        self.assertEqual(result.suggested_action, "escalate")


class TestDecisionServiceLLMIntegration(unittest.TestCase):
    """Verify the LLM hook in DecisionService respects guardrails."""

    def _make_k8s_trigger(self, error_signatures=None):
        from shared.mesh_runtime import Trigger
        return Trigger(
            trigger_id="trig_test",
            trigger_type="kubernetes_deployment_unhealthy",
            triggered_at="2026-04-15T00:00:00Z",
            service="search",
            endpoint="deployment/search",
            environment="prod",
            flag_key="",
            current_rollout_pct=0,
            comparison_window={"start": "2026-04-15T00:00:00Z", "end": "2026-04-15T00:05:00Z"},
            segment={"customer_tier": "standard"},
            metrics={
                "baseline_p95_latency_ms": 100,
                "observed_p95_latency_ms": 100,
                "baseline_error_rate": 0.01,
                "observed_error_rate": 0.01,
            },
            related_context={
                "error_signatures": error_signatures or [],
                "deployment_name": "search-api",
                "namespace": "search",
                "rollout_status": "degraded",
                "event_reasons": [],
                "likely_layer": "unknown",
                "cluster": "test",
                "deployment_image": "search:latest",
            },
        )

    def test_llm_upgrades_escalate_to_concrete_action(self):
        from services.decision.service import DecisionService

        mock_reasoner = MagicMock()
        mock_reasoner.reason.return_value = ReasoningResult(
            suggested_action="restart_deployment",
            confidence=0.8,
            reasoning_chain=["pods seem stuck"],
            risk_assessment="low",
        )
        svc = DecisionService(escalation_reasoner=mock_reasoner)
        trigger = self._make_k8s_trigger(error_signatures=["unknown_error"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "restart_deployment")
        self.assertLessEqual(decision.confidence, 0.85)

    def test_llm_cannot_override_concrete_decision(self):
        from services.decision.service import DecisionService

        mock_reasoner = MagicMock()
        mock_reasoner.reason.return_value = ReasoningResult(
            suggested_action="no_action",
            confidence=0.95,
            reasoning_chain=["everything is fine"],
            risk_assessment="none",
        )
        svc = DecisionService(escalation_reasoner=mock_reasoner)
        trigger = self._make_k8s_trigger(error_signatures=["crash_loop"])
        decision = svc._decide_kubernetes(trigger)
        # Rule engine says restart_deployment with confidence 0.78 — LLM should NOT be called
        self.assertEqual(decision.decision_type, "restart_deployment")
        mock_reasoner.reason.assert_not_called()

    def test_llm_capped_at_085(self):
        from services.decision.service import DecisionService

        mock_reasoner = MagicMock()
        mock_reasoner.reason.return_value = ReasoningResult(
            suggested_action="rollback_deployment",
            confidence=0.99,
            reasoning_chain=["very confident"],
            risk_assessment="low",
        )
        svc = DecisionService(escalation_reasoner=mock_reasoner)
        trigger = self._make_k8s_trigger(error_signatures=["unknown_error"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "rollback_deployment")
        self.assertLessEqual(decision.confidence, 0.85)


if __name__ == "__main__":
    unittest.main()
