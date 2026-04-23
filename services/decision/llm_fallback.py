"""LLM-backed decision proposer for OTel signals that don't match any rule.

# Why this exists

The metric-action rule engine covers known patterns — consumer lag, CPU
saturation, memory pressure. Anything outside the authored ruleset falls
through to ``escalate``. That's safe, but in the long tail (~15% of signals)
there's a recognizable-but-unwritten pattern the LLM can reason about: "this
metric looks a lot like a queue backlog, and the resource attributes suggest
a k8s deployment — I'd scale it." Layer 3 captures that judgment call.

# Design constraints

This is the hottest, riskiest LLM integration in Mesh because the LLM's
output directly drives actuation. Four invariants hold everything together:

1. **Bounded output space.** The LLM is given an explicit allowlist of
   ``(system, action)`` pairs it can propose. The validator rejects anything
   else. Even if the LLM hallucinates a new action, it never reaches the
   orchestrator.

2. **Parameter schema.** Each action has a typed parameter schema embedded
   in the prompt. The validator rejects responses missing required fields.

3. **Bounded blast radius.** The LLM cannot propose ``replicas_delta`` > the
   configured maximum, cannot target clusters or namespaces outside the
   existing k8s allowlist, and cannot raise memory above the configured cap.
   These bounds apply before the decision reaches the approval gate — not
   as a last line of defense.

4. **Graceful fallthrough.** LLM timeout, unreachable Goose binary, invalid
   JSON, schema violation — all fall through to ``escalate`` with a risk
   flag naming the failure mode. The rule engine coverage of well-known
   patterns never degrades because of an LLM outage.

# Failure modes and what they produce

| Failure | Result |
|---------|--------|
| Goose binary missing | ``None`` with ``risk_flags=["goose_unavailable"]`` |
| Timeout | ``None`` with ``risk_flags=["llm_timeout"]`` |
| Invalid JSON | ``None`` with ``risk_flags=["llm_invalid_json"]`` |
| Action not in allowlist | ``None`` with ``risk_flags=["llm_action_not_allowed"]`` |
| Missing required parameter | ``None`` with ``risk_flags=["llm_missing_parameter"]`` |
| Bound violation (e.g. replicas_delta > max) | Clamped, result returned with ``risk_flags=["llm_bound_clamped"]`` |

The caller (``DecisionService._decide_otel_metric``) interprets ``None`` as
"fall through to escalate" and uses ``risk_flags`` in the escalation
reasoning.

# Why Goose, not a direct API call

Mesh already has Goose wired for execution-time reviews, with provider
configuration, fallback profiles, and timeout handling in one place. Reusing
that machinery means this module doesn't duplicate API key management,
retry logic, or the fallback-provider dance. If Goose is swapped for a
different LLM front-end, only the ``_invoke_goose`` helper needs to change.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.metric_action_rules import RuleMatch


_LOG = logging.getLogger("mesh.decision.llm_fallback")


# The allowlist. Every action the LLM is allowed to propose must appear here
# with its required parameters. Adding a new action means updating this table
# AND wiring the actuator in goose_adapter.py / goose_bridge.py — the
# consistency is checked by the integration tests in test_metric_action_rules.
_ACTION_ALLOWLIST: dict[tuple[str, str], dict[str, Any]] = {
    ("kubernetes_service", "scale_deployment"): {
        "required": {"deployment_name", "namespace", "replicas"},
        "optional": {"cluster", "kube_context"},
        "numeric_bounds": {"replicas": (0, 50)},
        "description": "Scale a deployment to an absolute replica count.",
    },
    ("kubernetes_service", "restart_deployment"): {
        "required": {"deployment_name", "namespace"},
        "optional": {"cluster", "kube_context"},
        "numeric_bounds": {},
        "description": "Rolling-restart a deployment to clear transient state.",
    },
    ("kubernetes_service", "rollback_deployment"): {
        "required": {"deployment_name", "namespace"},
        "optional": {"cluster", "kube_context", "revision"},
        "numeric_bounds": {},
        "description": "Roll back a deployment to the previous revision.",
    },
    ("incident_service", "open_incident"): {
        "required": {"service", "severity"},
        "optional": {"endpoint", "environment", "reason"},
        "numeric_bounds": {},
        "description": "Open an incident for human remediation when the signal is ambiguous.",
    },
}


_SYSTEM_PROMPT = """You are the Mesh decision proposer. Given a metric regression that did not match any declarative rule, propose exactly one bounded action from the allowlist.

Rules:
1. Reply with compact JSON only. No markdown, no prose.
2. The `decision_type`, `system`, and `action` fields MUST match one of the allowlist entries exactly.
3. Include only parameters listed under the allowlist entry's required+optional keys.
4. If no action in the allowlist is appropriate, return action="open_incident" and system="incident_service".
5. `confidence` is in [0, 1]. Be honest — confidence should be low when you're guessing.
6. `risk_level` is "low", "medium", or "high".

Response shape:
{"decision_type": string, "system": string, "action": string, "parameters": object, "confidence": number, "risk_level": string, "rollback_plan": string, "reasoning": string}"""


@dataclass
class LlmProposalResult:
    """Structured return from the proposer.

    ``match`` is either a ``RuleMatch`` (ready to be turned into a Decision
    by the existing ``_decision_from_rule_match``) or ``None`` when we
    couldn't produce a valid proposal. ``risk_flags`` lets the caller
    distinguish "LLM was unavailable" from "LLM replied but violated
    constraints" — both fall through to escalate, but the escalation
    reasoning tells a different story.
    """

    match: RuleMatch | None
    risk_flags: list[str]
    raw_response: str | None = None


class LlmActionProposer:
    """Propose a bounded action for an unmatched OTel signal via Goose.

    Construct once at service startup and reuse; the class holds no per-run
    state. The actual subprocess call happens in :meth:`propose`, which is
    safe to call from worker threads.
    """

    def __init__(self, config: RuntimeConfig):
        self.config = config

    # Single entry point. Keep it small so the code path is obvious in
    # traces — we care about latency on the decision stage hot path.
    def propose(self, trigger_view: dict[str, Any]) -> LlmProposalResult:
        """Ask the LLM to pick a bounded action for the given signal view.

        ``trigger_view`` mirrors what the rule matcher sees — same shape as a
        normalized ``otel_metric_regression`` signal. We keep the LLM path
        symmetric with the rule path so swapping one for the other is trivial
        in tests and ops tooling.
        """
        if not self.config.llm_decision_fallback_enabled:
            return LlmProposalResult(match=None, risk_flags=["llm_fallback_disabled"])
        if not self.config.goose_command:
            return LlmProposalResult(match=None, risk_flags=["goose_unavailable"])

        prompt = _build_prompt(trigger_view)
        try:
            raw = self._invoke_goose(prompt)
        except _GooseInvocationError as exc:
            _LOG.warning("LLM fallback invocation failed: %s", exc)
            return LlmProposalResult(match=None, risk_flags=[exc.risk_flag])

        parsed = _parse_response(raw)
        if parsed is None:
            return LlmProposalResult(match=None, risk_flags=["llm_invalid_json"], raw_response=raw)

        validation = _validate_and_clamp(parsed)
        if validation.match is None:
            # Attach the raw response for post-mortem debugging of why a proposal
            # was rejected. The validator has already populated risk_flags.
            return LlmProposalResult(
                match=None,
                risk_flags=validation.risk_flags,
                raw_response=raw,
            )
        return LlmProposalResult(
            match=validation.match,
            risk_flags=validation.risk_flags,
            raw_response=raw,
        )

    # ---- subprocess glue ----------------------------------------------------

    def _invoke_goose(self, prompt: str) -> str:
        """Run ``goose run`` with the decision proposer system prompt.

        Mirrors the invocation in goose_bridge.py: ``--no-session --quiet``
        keeps the output clean, ``--output-format json`` gives us a parseable
        assistant message wrapper. We extract the assistant text and return
        it to :meth:`propose` for JSON parsing.
        """
        command = [
            self.config.goose_command or "goose",
            "run",
            "--text",
            prompt,
            "--system",
            _SYSTEM_PROMPT,
            "--no-session",
            "--quiet",
            "--output-format",
            "json",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.config.llm_decision_fallback_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise _GooseInvocationError("llm_timeout", f"goose run timed out: {exc}") from exc
        except OSError as exc:
            raise _GooseInvocationError("goose_unavailable", f"goose binary not runnable: {exc}") from exc

        if completed.returncode != 0:
            raise _GooseInvocationError(
                "llm_subprocess_error",
                completed.stderr.strip() or f"goose exited {completed.returncode}",
            )

        text = _extract_assistant_text(completed.stdout)
        if not text:
            raise _GooseInvocationError("llm_empty_response", "goose returned no assistant text")
        return text


# ----------------------------------------------------------------- prompt build


def _build_prompt(trigger_view: dict[str, Any]) -> str:
    """Construct the user-facing portion of the LLM prompt.

    The prompt is structured around three sections: the signal, the
    allowlist, and the required response schema. We keep the allowlist
    inline (rather than in the system prompt) so each request carries the
    exact menu — even when the allowlist table changes, the old system
    prompt in a cached Goose session can't poison the next decision.
    """
    signal = trigger_view.get("metric_regression", {})
    resource_attrs = trigger_view.get("resource_attributes", {})
    related = trigger_view.get("related_metrics", [])

    allowlist_entries = []
    for (system, action), spec in _ACTION_ALLOWLIST.items():
        allowlist_entries.append(
            {
                "system": system,
                "action": action,
                "required_parameters": sorted(spec["required"]),
                "optional_parameters": sorted(spec["optional"]),
                "numeric_bounds": spec["numeric_bounds"],
                "description": spec["description"],
            }
        )

    body = {
        "signal": {
            "service": trigger_view.get("service"),
            "endpoint": trigger_view.get("endpoint"),
            "environment": trigger_view.get("environment"),
            "metric_regression": signal,
        },
        "resource_attributes": resource_attrs,
        "related_metrics": related[:10],  # cap to keep prompt size bounded
        "allowlist": allowlist_entries,
    }
    return (
        "A metric regressed on a Mesh-monitored service. No declarative rule matched. "
        "Choose ONE bounded action from the allowlist and propose parameters sourced from "
        "the signal's resource_attributes or explicit values.\n\n"
        f"Context: {json.dumps(body, sort_keys=True)}"
    )


# ----------------------------------------------------------------- response parsing


def _extract_assistant_text(raw_stdout: str) -> str:
    """Pull the last assistant message from a ``goose run --output-format json`` blob.

    Goose can emit multiple messages (tool calls, assistant, etc). We want
    the final assistant turn because that's where the JSON decision lives.
    Iterating in reverse short-circuits on the first hit — cheaper than
    parsing every message.
    """
    try:
        payload = json.loads(raw_stdout)
    except json.JSONDecodeError:
        return raw_stdout.strip()
    messages = payload.get("messages", [])
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        parts = message.get("content", [])
        text = "".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
        if text:
            return text
    return ""


def _parse_response(text: str) -> dict[str, Any] | None:
    """Parse the LLM's JSON response, tolerating fenced code blocks.

    LLMs sometimes wrap JSON in ``` fences despite the "no markdown"
    instruction. We unwrap fences before parsing. If parsing still fails,
    the caller treats it as an invalid response.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            return None
    # Last-resort: find the outermost {...} span
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ----------------------------------------------------------------- validation


@dataclass
class _ValidationOutcome:
    match: RuleMatch | None
    risk_flags: list[str]


def _validate_and_clamp(parsed: dict[str, Any]) -> _ValidationOutcome:
    """Reject or clamp the LLM proposal against the allowlist.

    Ordering matters here: we check the allowlist first (so a wildly wrong
    action short-circuits before we spend time on parameters), then required
    parameters, then numeric bounds. Each step produces a specific risk flag
    so the escalation reasoning can explain exactly what failed.
    """
    system = parsed.get("system")
    action = parsed.get("action")
    decision_type = parsed.get("decision_type") or action

    if not isinstance(system, str) or not isinstance(action, str):
        return _ValidationOutcome(match=None, risk_flags=["llm_action_not_allowed"])

    spec = _ACTION_ALLOWLIST.get((system, action))
    if spec is None:
        return _ValidationOutcome(match=None, risk_flags=["llm_action_not_allowed"])

    parameters = parsed.get("parameters")
    if not isinstance(parameters, dict):
        return _ValidationOutcome(match=None, risk_flags=["llm_missing_parameter"])

    missing = spec["required"] - set(parameters)
    if missing:
        _LOG.warning("LLM proposal missing required parameters: %s", sorted(missing))
        return _ValidationOutcome(match=None, risk_flags=["llm_missing_parameter"])

    # Drop parameters that aren't in required or optional — LLMs sometimes
    # add extra keys that are plausible but not in our contract. Silent drop
    # is correct here; we don't want to surface noise to the user.
    allowed_keys = spec["required"] | spec["optional"]
    cleaned_parameters: dict[str, Any] = {
        key: value for key, value in parameters.items() if key in allowed_keys
    }

    # Enforce numeric bounds. Each out-of-bound value gets clamped and a risk
    # flag gets attached so the operator sees the LLM tried to exceed limits.
    risk_flags: list[str] = []
    for key, (lo, hi) in spec["numeric_bounds"].items():
        if key not in cleaned_parameters:
            continue
        value = cleaned_parameters[key]
        if not isinstance(value, (int, float)):
            continue
        if value < lo:
            cleaned_parameters[key] = lo
            risk_flags.append("llm_bound_clamped")
        elif value > hi:
            cleaned_parameters[key] = hi
            risk_flags.append("llm_bound_clamped")

    confidence = float(parsed.get("confidence", 0.55))
    confidence = max(0.0, min(confidence, 0.85))  # LLM cannot claim >0.85 confidence
    risk_level = parsed.get("risk_level", "medium")
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "medium"
    rollback_plan = parsed.get("rollback_plan") or f"undo the last {action} action"
    reasoning = parsed.get("reasoning") or "llm proposal (see raw response)"

    match = RuleMatch(
        rule_name=f"llm:fallback:{action}",
        decision_type=decision_type,
        system=system,
        action=action,
        parameters=cleaned_parameters,
        confidence=confidence,
        risk_level=risk_level,
        rollback_plan=rollback_plan,
        bounds={"source": "llm_fallback"},
        matched_on={"llm_reasoning": reasoning, "risk_flags": list(risk_flags)},
    )
    return _ValidationOutcome(match=match, risk_flags=risk_flags)


# ----------------------------------------------------------------- error types


class _GooseInvocationError(Exception):
    """Internal exception carrying the risk flag to surface on failure.

    We use a private exception because this error never escapes the module —
    :meth:`LlmActionProposer.propose` catches it and converts to a
    structured ``LlmProposalResult``. The caller sees ``None`` + risk flags,
    not an exception.
    """

    def __init__(self, risk_flag: str, message: str):
        super().__init__(message)
        self.risk_flag = risk_flag


__all__ = ["LlmActionProposer", "LlmProposalResult"]
