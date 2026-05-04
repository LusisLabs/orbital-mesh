"""Tests for the OpenAI-compatible LlmObserver.

The HTTP client is mocked out so we exercise the verdict-parsing,
fallback-on-error, and verdict-allowlist logic without touching the
network.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from services.observer import LlmObserver, ObserverConfig
from services.observer.client import ChatMessage, ObserverClientError, chat_completion
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

    def test_observer_passes_prompt_cache_config_to_client(self):
        body = '{"verdict": "approve", "reason": "cached", "concerns": [], "confidence": 0.8}'
        cfg = _enabled_config()
        cfg.provider = "anthropic"
        cfg.prompt_cache_enabled = True
        cfg.prompt_cache_mode = "both"
        cfg.prompt_cache_ttl = "1h"
        with patch("services.observer.service.chat_completion", return_value=_ok_response(body)) as mocked:
            LlmObserver(cfg).review(
                trigger=_BASE_TRIGGER,
                evidence_pack={},
                ranked_hypotheses=[],
                deterministic_decision=_BASE_DET,
            )

        kwargs = mocked.call_args.kwargs
        self.assertTrue(kwargs["prompt_cache_enabled"])
        self.assertEqual(kwargs["prompt_cache_mode"], "both")
        self.assertEqual(kwargs["prompt_cache_ttl"], "1h")


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


class RetryAfterBudgetTests(unittest.TestCase):
    """``Retry-After`` must not push the call past the caller's
    ``timeout_seconds`` budget. An 8-second observer budget should not
    be silently stretched to 30 seconds because the provider rate-
    limited us — the deterministic decision needs to come back promptly
    or the observer should fail-open."""

    def test_retry_after_exceeding_budget_aborts_immediately(self):
        import urllib.error
        from io import BytesIO
        from services.observer.client import _post_with_retry, ObserverClientError

        class _Headers(dict):
            def get(self, k, default=None):
                return super().get(k, default)

        # Build a 429 with Retry-After well over the budget.
        headers = _Headers({"Retry-After": "30"})
        http_err = urllib.error.HTTPError(
            url="http://x", code=429, msg="Too Many Requests",
            hdrs=headers, fp=BytesIO(b'{"error":"rate_limit"}'),
        )
        http_err.headers = headers

        calls = {"n": 0}

        class _FakeResponse:
            def __init__(self) -> None:
                pass

        def fake_urlopen(req, timeout):
            calls["n"] += 1
            raise http_err

        # 5-second budget, 30s Retry-After -> must not sleep, must abort
        # quickly. We measure wall time to confirm.
        import time as _time
        from unittest.mock import patch as _patch

        start = _time.monotonic()
        with _patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ObserverClientError) as ctx:
                _post_with_retry(
                    url="http://x",
                    body=b"{}",
                    headers={},
                    timeout_seconds=5.0,
                    max_retries=1,
                )
        elapsed = _time.monotonic() - start

        # Single attempt — the retry was abandoned because Retry-After
        # exceeded budget. No 30-second sleep.
        self.assertEqual(calls["n"], 1)
        self.assertLess(elapsed, 2.0, "must not sleep through Retry-After when over budget")
        self.assertIn("retry-after", str(ctx.exception).lower())

    def test_retry_after_within_budget_does_retry(self):
        """Sanity: if Retry-After is short enough to fit, the retry runs."""
        import urllib.error
        from io import BytesIO
        from services.observer.client import _post_with_retry
        from unittest.mock import patch as _patch

        class _Headers(dict):
            def get(self, k, default=None):
                return super().get(k, default)

        headers = _Headers({"Retry-After": "0"})  # no wait
        http_err_429 = urllib.error.HTTPError(
            url="http://x", code=429, msg="Too Many Requests",
            hdrs=headers, fp=BytesIO(b"{}"),
        )
        http_err_429.headers = headers

        class _OkResponse:
            def __init__(self):
                self._read = b'{"choices":[]}'

            def read(self):
                return self._read

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        responses = [http_err_429, _OkResponse()]

        def fake_urlopen(req, timeout):
            r = responses.pop(0)
            if isinstance(r, urllib.error.HTTPError):
                raise r
            return r

        with _patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = _post_with_retry(
                url="http://x",
                body=b"{}",
                headers={},
                timeout_seconds=10.0,
                max_retries=1,
            )
        self.assertEqual(result, b'{"choices":[]}')


class AnthropicPromptCachingTests(unittest.TestCase):
    class _OkResponse:
        def __init__(self, payload: dict) -> None:
            self._raw = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _call_anthropic(self, **kwargs):
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.header_items())
            return self._OkResponse(
                {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 40,
                        "cache_read_input_tokens": 60,
                    },
                }
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = chat_completion(
                base_url="https://api.anthropic.com",
                api_key="sk-ant-test",
                model="claude-haiku-4-5-20251001",
                messages=[
                    ChatMessage(role="system", content="static policy", cache_hint=True),
                    ChatMessage(role="user", content="dynamic incident"),
                ],
                provider="anthropic",
                **kwargs,
            )
        return captured, response

    def test_explicit_cache_marks_stable_system_block(self):
        captured, response = self._call_anthropic()

        body = captured["body"]
        self.assertNotIn("cache_control", body)
        self.assertEqual(
            body["system"][0]["cache_control"],
            {"type": "ephemeral"},
        )
        self.assertEqual(response["_anthropic_cache_creation_input_tokens"], 40)
        self.assertEqual(response["_anthropic_cache_read_input_tokens"], 60)

    def test_automatic_cache_adds_top_level_cache_control(self):
        captured, _response = self._call_anthropic(
            prompt_cache_mode="automatic",
            prompt_cache_ttl="1h",
        )

        body = captured["body"]
        self.assertEqual(body["cache_control"], {"type": "ephemeral", "ttl": "1h"})
        self.assertNotIn("cache_control", body["system"][0])

    def test_prompt_cache_can_be_disabled(self):
        captured, _response = self._call_anthropic(prompt_cache_enabled=False)

        body = captured["body"]
        self.assertNotIn("cache_control", body)
        self.assertNotIn("cache_control", body["system"][0])


if __name__ == "__main__":
    unittest.main()
