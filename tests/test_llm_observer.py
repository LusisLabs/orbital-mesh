"""Tests for the OpenAI-compatible LlmObserver.

The HTTP client is mocked out so we exercise the verdict-parsing,
fallback-on-error, and verdict-allowlist logic without touching the
network.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.observer import LlmObserver, ObserverConfig
from services.observer.client import ObserverClientError
from services.observer.service import _try_parse_json_block


def _disabled_config() -> ObserverConfig:
    return ObserverConfig(enabled=False)


def _enabled_config() -> ObserverConfig:
    return ObserverConfig(
        enabled=True,
        base_url="http://localhost:1",
        api_key="sk-test",
        model="test-model",
        timeout_seconds=1.0,
    )


def _ok_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


_BASE_DET = {
    "decision_type": "restart_systemd_service",
    "autonomy_tier": "approval_required",
    "confidence": 0.7,
    "reasoning": {"primary_hypothesis": "peer starvation"},
}


_BASE_TRIGGER = {
    "trigger_id": "trig_test",
    "trigger_type": "reth_node_degraded",
    "service": "reth-mainnet-07",
    "related_context": {"error_signatures": ["peer_starvation"]},
}


class ObserverActivationTests(unittest.TestCase):
    def test_disabled_returns_approve_fallback(self):
        verdict = LlmObserver(_disabled_config()).review(
            trigger=_BASE_TRIGGER,
            evidence_pack=None,
            ranked_hypotheses=[],
            deterministic_decision=_BASE_DET,
        )
        self.assertEqual(verdict.verdict, "approve")
        self.assertFalse(verdict.promotes_to_escalate())
        self.assertEqual(verdict.error, "observer disabled")

    def test_missing_credentials_returns_approve_fallback(self):
        cfg = ObserverConfig(enabled=True, base_url="", api_key="", model="")
        verdict = LlmObserver(cfg).review(
            trigger=_BASE_TRIGGER,
            evidence_pack=None,
            ranked_hypotheses=[],
            deterministic_decision=_BASE_DET,
        )
        self.assertEqual(verdict.verdict, "approve")
        self.assertEqual(verdict.error, "observer disabled")


class ObserverHappyPathTests(unittest.TestCase):
    def test_approve_verdict_passed_through(self):
        body = '{"verdict": "approve", "reason": "evidence supports the decision", "concerns": [], "confidence": 0.85}'
        with patch("services.observer.service.chat_completion", return_value=_ok_response(body)):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={"sufficient": True},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "approve")
        self.assertFalse(verdict.promotes_to_escalate())
        self.assertEqual(verdict.confidence, 0.85)
        self.assertIsNone(verdict.error)

    def test_escalate_verdict_promotes(self):
        body = '{"verdict": "escalate", "reason": "disk pressure makes restart unsafe", "concerns": ["disk_used_pct=92"], "confidence": 0.9}'
        with patch("services.observer.service.chat_completion", return_value=_ok_response(body)):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={"sufficient": True, "pack": {"storage": {"disk_used_pct": 92.0}}},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "escalate")
        self.assertTrue(verdict.promotes_to_escalate())

    def test_reject_unsafe_promotes(self):
        body = '{"verdict": "reject_unsafe", "reason": "validator mid-attestation", "concerns": [], "confidence": 1.0}'
        with patch("services.observer.service.chat_completion", return_value=_ok_response(body)):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "reject_unsafe")
        self.assertTrue(verdict.promotes_to_escalate())

    def test_request_more_evidence_promotes(self):
        body = '{"verdict": "request_more_evidence", "reason": "execution fields are null", "concerns": ["missing peer_count"], "confidence": 0.6}'
        with patch("services.observer.service.chat_completion", return_value=_ok_response(body)):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={"sufficient": False, "missing_fields": ["execution.peer_count"]},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "request_more_evidence")
        self.assertTrue(verdict.promotes_to_escalate())


class ObserverDefensiveTests(unittest.TestCase):
    def test_unknown_verdict_falls_back_to_approve(self):
        body = '{"verdict": "yolo", "reason": "lol", "concerns": [], "confidence": 0.9}'
        with patch("services.observer.service.chat_completion", return_value=_ok_response(body)):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "approve")
        self.assertEqual(verdict.error, "unknown_verdict")
        self.assertFalse(verdict.promotes_to_escalate())

    def test_garbage_response_falls_back_to_approve(self):
        with patch(
            "services.observer.service.chat_completion",
            return_value=_ok_response("definitely not json"),
        ):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "approve")
        self.assertEqual(verdict.error, "json_parse_failed")

    def test_client_error_falls_back_to_approve(self):
        with patch(
            "services.observer.service.chat_completion",
            side_effect=ObserverClientError("upstream 500"),
        ):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "approve")
        self.assertIn("upstream 500", verdict.error or "")
        self.assertFalse(verdict.promotes_to_escalate())

    def test_unexpected_exception_falls_back_to_approve(self):
        with patch(
            "services.observer.service.chat_completion",
            side_effect=RuntimeError("ssl failure"),
        ):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "approve")
        self.assertIn("ssl failure", verdict.error or "")

    def test_json_extracted_from_markdown_fence(self):
        # Some providers wrap JSON in fences even when response_format is set.
        body = """Sure, here is my verdict:
```json
{"verdict": "escalate", "reason": "ok", "concerns": [], "confidence": 0.7}
```
"""
        with patch("services.observer.service.chat_completion", return_value=_ok_response(body)):
            verdict = LlmObserver(_enabled_config()).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )
        self.assertEqual(verdict.verdict, "escalate")


class JsonExtractTests(unittest.TestCase):
    def test_plain_json_parsed(self):
        result = _try_parse_json_block('{"verdict": "approve"}')
        self.assertEqual(result, {"verdict": "approve"})

    def test_json_in_fence_parsed(self):
        result = _try_parse_json_block('```json\n{"verdict": "escalate"}\n```')
        self.assertEqual(result, {"verdict": "escalate"})

    def test_garbage_returns_none(self):
        self.assertIsNone(_try_parse_json_block("not json at all"))


if __name__ == "__main__":
    unittest.main()
