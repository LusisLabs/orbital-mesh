"""LLM observer — read a deterministic decision and emit a typed verdict.

# Where this fits

The deterministic engine in ``services/decision/service.py`` produces a
single bounded decision based on policy and falsifiable hypotheses. The
observer reads that decision, the evidence pack, and the ranked
hypotheses, and emits a *verdict* that the decision service uses as a
one-way safety gate.

The hard property the observer is designed around: it can only PROMOTE
the safety direction. ``approve``  ``escalate``  ``reject_unsafe``
flow forward, never backward. So even a hallucinating model can only
make the system more conservative, never more aggressive. That, plus
the typed JSON response, plus a verdict allowlist, plus the existing
Promptfoo evaluation gate, plus the orchestrator's autonomy policy, is
the layered defense.

# Why OpenAI-compatible

We deliberately don't bind to one provider's SDK. Mesh runs on operator
infra; whatever LLM is reachable from there should work. Anything that
speaks ``/v1/chat/completions`` qualifies — local vLLM, Ollama, OpenAI,
Anthropic via Oai-shim, Groq, Together, OpenRouter. Switching providers
is a config change.

# Failure modes are not failures

Every failure mode of the observer (provider down, timeout, bad JSON,
unknown verdict, schema-invalid output) returns ``ObserverVerdict``
with ``verdict="approve"`` and an error message in ``error``. The
deterministic decision stands. The observer is additive — it can only
make the decision *safer*, never less safe, and a missing observer
cannot block the pipeline.

NB: this is the opposite of "fail closed". We chose "fail open" here
deliberately because the deterministic engine is the safety floor;
silently escalating every run when the LLM is down would generate alert
fatigue and degrade trust in the observer's outputs. The observer is a
second pair of eyes, not the only pair.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.observer.client import (
    ObserverClientError,
    chat_completion,
    extract_message_content,
)
from services.observer.prompts import build_messages


_LOG = logging.getLogger("mesh.observer")


_ALLOWED_VERDICTS: frozenset[str] = frozenset({
    "approve",
    "escalate",
    "request_more_evidence",
    "reject_unsafe",
})


# Verdicts that must promote the decision to escalate. The decision
# service does not act on the LLM's output directly; it asks
# ``promotes_to_escalate()`` and applies the deterministic floor.
_PROMOTES_TO_ESCALATE: frozenset[str] = frozenset({
    "escalate",
    "reject_unsafe",
    "request_more_evidence",
})


@dataclass
class ObserverConfig:
    """Knobs for ``LlmObserver``. All optional — disabled by default.

    Wiring is intentionally provider-neutral: any URL that speaks
    ``/v1/chat/completions`` works. Read by ``RuntimeConfig.from_env``
    from these env vars:

    * ``MESH_OBSERVER_ENABLED``    -> bool  (default: false)
    * ``MESH_OBSERVER_BASE_URL``   -> str   (e.g., https://api.openai.com)
    * ``MESH_OBSERVER_API_KEY``    -> str
    * ``MESH_OBSERVER_MODEL``      -> str   (e.g., gpt-4o-mini, claude-sonnet-4-6)
    * ``MESH_OBSERVER_TIMEOUT_S``  -> float (default: 8.0)
    """

    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 8.0
    max_tokens: int = 512
    # ``openai`` (default) speaks /v1/chat/completions; ``anthropic``
    # speaks /v1/messages and adapts the response to the same shape.
    provider: str = "openai"
    prompt_cache_enabled: bool = True
    prompt_cache_mode: str = "explicit"
    prompt_cache_ttl: str = "5m"


@dataclass
class ObserverVerdict:
    """The observer's typed output, attached to the run record."""

    verdict: str                # one of _ALLOWED_VERDICTS
    reason: str
    concerns: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str = ""
    latency_ms: float | None = None
    raw_response: str | None = None
    error: str | None = None
    observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "concerns": list(self.concerns),
            "confidence": round(self.confidence, 3),
            "model": self.model,
            "latency_ms": self.latency_ms,
            "raw_response": self.raw_response,
            "error": self.error,
            "observed_at": self.observed_at,
        }

    def promotes_to_escalate(self) -> bool:
        """True iff the verdict requires the decision service to
        escalate. ``approve`` and any errored verdict do not promote."""
        return self.verdict in _PROMOTES_TO_ESCALATE and self.error is None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _approve_fallback(model: str, error: str) -> ObserverVerdict:
    """When the observer can't run or returns garbage, default to
    ``approve`` so the deterministic decision stands. The error string
    is stamped on the verdict so operators can see what happened."""
    return ObserverVerdict(
        verdict="approve",
        reason="observer unavailable; deterministic decision stands",
        concerns=[],
        confidence=0.0,
        model=model,
        latency_ms=None,
        raw_response=None,
        error=error,
        observed_at=_now_iso(),
    )


def _try_parse_json_block(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of ``text``.

    Some providers wrap responses in markdown fences or leading prose
    even when ``response_format=json_object`` is requested. We try a
    plain ``json.loads`` first, then a regex extraction of the first
    ``{...}`` block. Anything more complex than that should be a hard
    failure — verdicts are short typed objects, not freeform output.
    """
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


class LlmObserver:
    """Modular OpenAI-compatible observer.

    Constructed once and called on each decision. The provider client
    is stateless; we don't hold connections. Prompt-cache hit/miss is a
    server-side concern.
    """

    def __init__(self, config: ObserverConfig) -> None:
        self.config = config

    def is_active(self) -> bool:
        """Return True iff the observer should run for the next decision."""
        return bool(
            self.config.enabled
            and self.config.base_url
            and self.config.api_key
            and self.config.model
        )

    def review(
        self,
        *,
        trigger: dict[str, Any],
        evidence_pack: dict[str, Any] | None,
        ranked_hypotheses: list[dict[str, Any]],
        deterministic_decision: dict[str, Any],
        policy_excerpt: dict[str, Any] | None = None,
    ) -> ObserverVerdict:
        """Run one observer pass. Always returns an ``ObserverVerdict``."""
        if not self.is_active():
            return _approve_fallback(self.config.model, "observer disabled")

        messages = build_messages(
            evidence_pack=evidence_pack,
            deterministic_decision=deterministic_decision,
            ranked_hypotheses=ranked_hypotheses,
            trigger=trigger,
            policy_excerpt=policy_excerpt,
        )

        start = time.monotonic()
        try:
            response = chat_completion(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                model=self.config.model,
                messages=messages,
                timeout_seconds=self.config.timeout_seconds,
                response_format={"type": "json_object"},
                max_tokens=self.config.max_tokens,
                temperature=0.0,
                provider=self.config.provider,
                prompt_cache_enabled=self.config.prompt_cache_enabled,
                prompt_cache_mode=self.config.prompt_cache_mode,
                prompt_cache_ttl=self.config.prompt_cache_ttl,
            )
            content = extract_message_content(response)
        except ObserverClientError as exc:
            _LOG.warning("observer call failed: %s", exc)
            return _approve_fallback(self.config.model, f"client_error: {exc}")
        except Exception as exc:
            # Defensive: any unexpected error must not break the
            # pipeline. Surface as a fallback approval and let the
            # deterministic decision through.
            _LOG.exception("observer unexpected failure")
            return _approve_fallback(self.config.model, f"unexpected_error: {exc}")
        latency_ms = (time.monotonic() - start) * 1000.0

        parsed = _try_parse_json_block(content)
        if parsed is None:
            return ObserverVerdict(
                verdict="approve",
                reason="observer returned unparseable JSON; deterministic decision stands",
                concerns=[],
                confidence=0.0,
                model=self.config.model,
                latency_ms=latency_ms,
                raw_response=content[:1000],
                error="json_parse_failed",
                observed_at=_now_iso(),
            )

        verdict = str(parsed.get("verdict", "")).strip().lower()
        if verdict not in _ALLOWED_VERDICTS:
            return ObserverVerdict(
                verdict="approve",
                reason=(
                    f"observer emitted unknown verdict {verdict!r}; "
                    "deterministic decision stands"
                ),
                concerns=[],
                confidence=0.0,
                model=self.config.model,
                latency_ms=latency_ms,
                raw_response=content[:1000],
                error="unknown_verdict",
                observed_at=_now_iso(),
            )

        reason = str(parsed.get("reason", "")).strip() or "(no reason given)"
        concerns_raw = parsed.get("concerns", [])
        if isinstance(concerns_raw, list):
            concerns = [str(c) for c in concerns_raw if c]
        else:
            concerns = []
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return ObserverVerdict(
            verdict=verdict,
            reason=reason,
            concerns=concerns,
            confidence=confidence,
            model=self.config.model,
            latency_ms=latency_ms,
            raw_response=content[:1000],
            error=None,
            observed_at=_now_iso(),
        )


class MultiLlmObserver:
    """Run a primary observer plus an optional secondary sanity-check model."""

    def __init__(self, primary: LlmObserver, secondary: LlmObserver | None = None) -> None:
        self.primary = primary
        self.secondary = secondary

    def is_active(self) -> bool:
        return self.primary.is_active()

    def review(self, **kwargs: Any) -> ObserverVerdict:
        primary = self.primary.review(**kwargs)
        if self.secondary is None or not self.secondary.is_active():
            return primary
        secondary = self.secondary.review(**kwargs)
        verdicts = [primary, secondary]
        agreement = primary.verdict == secondary.verdict
        chosen = _most_conservative_verdict(verdicts)
        return ObserverVerdict(
            verdict=chosen.verdict,
            reason=(
                f"observer_agreement={agreement}; primary={primary.verdict}; "
                f"secondary={secondary.verdict}. {chosen.reason}"
            ),
            concerns=[
                f"primary:{primary.model}:{primary.verdict}",
                f"secondary:{secondary.model}:{secondary.verdict}",
                *chosen.concerns,
            ],
            confidence=max(primary.confidence, secondary.confidence),
            model=f"{primary.model}+{secondary.model}",
            latency_ms=(primary.latency_ms or 0) + (secondary.latency_ms or 0),
            raw_response=json.dumps(
                {
                    "observer_agreement": agreement,
                    "observer_verdicts": [primary.to_dict(), secondary.to_dict()],
                },
                sort_keys=True,
            )[:1000],
            error=None if not (primary.error or secondary.error) else primary.error or secondary.error,
            observed_at=_now_iso(),
        )


def _most_conservative_verdict(verdicts: list[ObserverVerdict]) -> ObserverVerdict:
    rank = {"approve": 0, "escalate": 1, "request_more_evidence": 2, "reject_unsafe": 3}
    return max(verdicts, key=lambda verdict: rank.get(verdict.verdict, 0))
