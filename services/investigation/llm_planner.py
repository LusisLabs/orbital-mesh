"""LLM-backed investigation planner — bridges the observer's chat client
to the harness's ``LlmProbeSelector`` decision_provider contract.

The ``LlmProbeSelector`` (in ``harness/native_selector.py``) is gated
behind a ``decision_provider`` callable: given a context dict (tools,
observations, trigger), the provider returns a proposal dict
``{action, tool_name, args, reason, confidence}``. This module builds
that callable using the same observer LLM the rest of Mesh uses
(``services/observer/client.py``).

When ``MESH_OBSERVER_ENABLED=1`` and a key is configured, the auto-wired
investigation harness will use the LLM-backed selector instead of the
rule-based ``CloudOpsLoopPlanner``. When the observer is disabled, this
module returns ``None`` and the rule-based selector is used — the
deterministic safety floor.

All LLM failure modes (timeout, malformed JSON, unknown tool) collapse to
``action="stop"`` with a recorded reason. The caller (LlmProbeSelector)
treats that as "stop the loop" and falls back to whatever evidence is
already collected. The harness cannot crash from a hallucinating model.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from services.observer.client import ChatMessage, ObserverClientError, chat_completion
from shared.mesh_runtime import RuntimeConfig


_LOG = logging.getLogger(__name__)

DecisionProvider = Callable[[dict[str, Any]], dict[str, Any]]


_SYSTEM_PROMPT = """You are an SRE investigation planner. You are given:

1. ``observations``: the tool calls already made and their results
2. ``available_tools``: the tools you can still call (with their schemas)
3. ``trigger``: the original alert that started this investigation
4. ``ranked_root_causes``: candidate root causes the harness is currently considering

Decide ONE next action:

- ``continue``: invoke a tool to gather more evidence
- ``stop``: enough evidence collected; the current ranked_root_causes are reliable

Respond with valid JSON ONLY (no prose, no code fence, no commentary):

{
  "action": "continue" | "stop",
  "tool_name": "<one of available_tools.name, only if action=continue>",
  "args": {<args matching tool's args_schema>},
  "reason": "<one short sentence of why>",
  "confidence": <number between 0 and 1>
}

Constraints:
- Read-only tools only. The harness rejects mutating tools.
- Do not invent tools. Pick from ``available_tools``.
- Stop early if a strong root cause candidate is supported by multiple observations.
"""


_JSON_FENCE_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_llm_decision_provider(config: RuntimeConfig) -> DecisionProvider | None:
    """Return a decision_provider for ``LlmProbeSelector``, or None if LLM is disabled.

    Disabled (returns None) means the harness falls back to the
    rule-based selector. Enabled means every harness iteration calls
    the observer LLM with the current context and asks for the next
    tool call. Failures collapse to ``stop`` and are logged.
    """

    if not config.observer_enabled or not config.observer_api_key:
        return None

    base_url = config.observer_base_url or _default_base_url(config.observer_provider)
    if not base_url:
        return None

    def provider(context: dict[str, Any]) -> dict[str, Any]:
        try:
            messages = [
                ChatMessage(role="system", content=_SYSTEM_PROMPT, cache_hint=True),
                ChatMessage(role="user", content=json.dumps(context, default=str)[:24_000]),
            ]
            response = chat_completion(
                base_url=base_url,
                api_key=config.observer_api_key,
                model=config.observer_model or _default_model(config.observer_provider),
                messages=messages,
                provider=config.observer_provider,
                timeout_seconds=config.observer_timeout_seconds,
                max_tokens=config.observer_max_tokens,
                temperature=0.0,
                prompt_cache_enabled=True,
                prompt_cache_mode=config.observer_prompt_cache_mode,
                prompt_cache_ttl=config.observer_prompt_cache_ttl,
            )
        except (ObserverClientError, Exception) as exc:  # noqa: BLE001 — fail-open by design
            _LOG.warning("llm_planner: provider call failed: %s", exc)
            return {"action": "stop", "reason": f"llm_planner_error:{type(exc).__name__}", "confidence": 0.0}

        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return _parse_proposal(content)

    return provider


def _parse_proposal(raw: str) -> dict[str, Any]:
    """Extract a proposal dict from raw LLM output. Tolerant of fenced JSON and stray prose."""

    if not raw:
        return {"action": "stop", "reason": "llm_planner_empty_response", "confidence": 0.0}
    candidates: list[str] = []
    if "```" in raw:
        for chunk in raw.split("```"):
            if chunk.lstrip().startswith("json"):
                chunk = chunk.lstrip()[4:]
            candidates.append(chunk)
    candidates.append(raw)
    for candidate in candidates:
        match = _JSON_FENCE_RE.search(candidate)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"action": "stop", "reason": "llm_planner_unparseable_response", "confidence": 0.0}


def _default_base_url(provider: str) -> str:
    if provider == "anthropic":
        return "https://api.anthropic.com"
    return "https://api.openai.com"


def _default_model(provider: str) -> str:
    if provider == "anthropic":
        return "claude-haiku-4-5-20251001"
    return "gpt-4o-mini"
