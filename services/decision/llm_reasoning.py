"""LLM-backed escalation reasoning for novel or ambiguous scenarios.

When the rule engine produces ``escalate`` or a low-confidence decision, the
EscalationReasoner queries an LLM to see if the situation can be resolved with
a concrete action instead of deferring to a human.  The rule engine always runs
first — the LLM can only *upgrade* from ``escalate`` to an allowed action, never
override a concrete rule-engine decision.
"""

from __future__ import annotations

import json
import subprocess
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.mesh_runtime.config import RuntimeConfig
    from shared.mesh_runtime.context_store import ContextStore
    from shared.mesh_runtime.learning import LearningStore
    from shared.mesh_runtime import Trigger

ALLOWED_ACTIONS = frozenset({
    "reduce_rollout",
    "disable_flag",
    "restart_deployment",
    "rollback_deployment",
    "escalate",
    "no_action",
})

MESH_ROOT = Path(__file__).resolve().parents[2]

_SYSTEM_PROMPT = (
    "You are a Kubernetes remediation reasoning engine.  Given the current "
    "deployment state, error signatures, incident history, and historical "
    "success rates, decide the best bounded remediation action.\n\n"
    "RULES:\n"
    "- You may ONLY suggest one of these actions: "
    "reduce_rollout, disable_flag, restart_deployment, rollback_deployment, "
    "escalate, no_action.\n"
    "- Respond with ONLY compact JSON matching this shape:\n"
    '  {"suggested_action": string, "confidence": float 0-1, '
    '"reasoning_chain": string[], "risk_assessment": string}\n'
    "- Do not include markdown fences or extra text."
)


@dataclass
class ReasoningResult:
    suggested_action: str
    confidence: float
    reasoning_chain: list[str]
    risk_assessment: str
    raw_response: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggested_action": self.suggested_action,
            "confidence": self.confidence,
            "reasoning_chain": self.reasoning_chain,
            "risk_assessment": self.risk_assessment,
        }


def _default_escalate() -> ReasoningResult:
    return ReasoningResult(
        suggested_action="escalate",
        confidence=0.0,
        reasoning_chain=["LLM reasoning unavailable — defaulting to escalation"],
        risk_assessment="unknown",
    )


class EscalationReasoner:
    """Query an LLM for remediation reasoning when rules produce ``escalate``."""

    def __init__(
        self,
        config: RuntimeConfig,
        context_store: ContextStore | None = None,
        learning_store: LearningStore | None = None,
    ) -> None:
        self.config = config
        self.context_store = context_store
        self.learning_store = learning_store

    def reason(self, trigger: Trigger) -> ReasoningResult:
        prompt = self._build_prompt(trigger)
        raw = self._call_llm(prompt)
        if raw is None:
            return _default_escalate()
        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(self, trigger: Trigger) -> str:
        sections: list[str] = []

        # 1. Current signal
        sections.append("## Current Signal")
        sections.append(f"Service: {trigger.service}")
        sections.append(f"Trigger type: {trigger.trigger_type}")
        rc = trigger.related_context or {}
        if rc.get("deployment_name"):
            sections.append(f"Deployment: {rc['deployment_name']}")
        if rc.get("namespace"):
            sections.append(f"Namespace: {rc['namespace']}")
        if rc.get("error_signatures"):
            sections.append(f"Error signatures: {', '.join(rc['error_signatures'])}")
        if rc.get("rollout_status"):
            sections.append(f"Rollout status: {rc['rollout_status']}")

        # 2. Service context from context store
        if self.context_store:
            svc_ctx = self.context_store.get_service_context(trigger.service)
            if svc_ctx:
                sections.append("\n## Service History")
                sections.append(f"Total runs: {svc_ctx.get('total_runs', 0)}")
                sr = svc_ctx.get("success_rate")
                if sr is not None:
                    sections.append(f"Success rate: {sr}")
                if svc_ctx.get("common_error_patterns"):
                    sections.append(f"Common errors: {', '.join(svc_ctx['common_error_patterns'])}")

        # 3. Similar past incidents
        if self.context_store:
            error_sig = "|".join(rc.get("error_signatures", [])) or trigger.trigger_type
            similar = self.context_store.get_similar_incidents(error_sig, limit=5)
            if similar:
                sections.append("\n## Similar Past Incidents (most recent first)")
                for inc in similar:
                    sections.append(
                        f"- {inc.get('decision_type', '?')} → {inc.get('outcome', '?')} "
                        f"(error: {inc.get('error_signature', '?')})"
                    )

        # 4. Success rates from learning store
        if self.learning_store:
            sections.append("\n## Historical Success Rates")
            for action in sorted(ALLOWED_ACTIONS - {"escalate", "no_action"}):
                rate = self.learning_store.get_historical_success_rate(action, trigger.service)
                if rate is not None:
                    sections.append(f"- {action}: {rate:.0%}")

            # Recovery patterns
            patterns = self.learning_store.get_recovery_patterns(trigger.service)
            if patterns:
                sections.append("\n## Known Recovery Patterns")
                for pattern, count in sorted(patterns.items(), key=lambda x: -x[1]):
                    sections.append(f"- {pattern}: seen {count} time(s)")

        sections.append(
            "\n## Task\nGiven the above context, suggest the best bounded "
            "remediation action from the allowed set."
        )
        return "\n".join(sections)

    # ------------------------------------------------------------------
    # LLM invocation
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str) -> str | None:
        provider = self.config.llm_escalation_provider
        if provider == "goose":
            return self._call_goose(prompt)
        return None

    def _call_goose(self, prompt: str) -> str | None:
        goose_bin = self.config.goose_command
        if not goose_bin:
            return None
        command = [
            goose_bin,
            "run",
            "--text", prompt,
            "--system", _SYSTEM_PROMPT,
            "--no-session",
            "--quiet",
            "--output-format", "json",
        ]
        if self.config.llm_escalation_model:
            command.extend(["--model", self.config.llm_escalation_model])
        try:
            completed = subprocess.run(
                command,
                cwd=MESH_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.config.llm_escalation_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        return _extract_assistant_text(payload)

    # ------------------------------------------------------------------
    # Response parsing with guardrails
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> ReasoningResult:
        parsed = _parse_json_from_text(raw)
        if parsed is None:
            return _default_escalate()

        action = str(parsed.get("suggested_action", "escalate"))
        if action not in ALLOWED_ACTIONS:
            return ReasoningResult(
                suggested_action="escalate",
                confidence=0.0,
                reasoning_chain=[f"LLM suggested disallowed action '{action}' — escalating"],
                risk_assessment="unknown",
                raw_response=raw,
            )

        confidence = _clamp(float(parsed.get("confidence", 0.0)), 0.0, 1.0)
        reasoning_chain = parsed.get("reasoning_chain", [])
        if not isinstance(reasoning_chain, list):
            reasoning_chain = [str(reasoning_chain)]
        risk_assessment = str(parsed.get("risk_assessment", "unknown"))

        return ReasoningResult(
            suggested_action=action,
            confidence=confidence,
            reasoning_chain=[str(r) for r in reasoning_chain],
            risk_assessment=risk_assessment,
            raw_response=raw,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_assistant_text(payload: dict) -> str | None:
    messages = payload.get("messages", [])
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        parts = message.get("content", [])
        text = "".join(
            part.get("text", "") for part in parts if part.get("type") == "text"
        ).strip()
        if text:
            return text
    return None


def _parse_json_from_text(text: str) -> dict | None:
    cleaned = text.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))
