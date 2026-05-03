"""Evidence-aware SRE judgment layer for evaluation.

Hard policy checks still live in ``EvaluationService``. This module adds the
softer SRE review that answers: execute, defer, human review, or reject?
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from services.observer.client import ChatMessage, ObserverClientError, chat_completion, extract_message_content
from services.observer.redaction import redact_for_observer
from shared.mesh_runtime import Decision, Trigger


_RECOMMENDATION_RANK = {
    "execute": 0,
    "defer": 1,
    "human_review": 2,
    "reject": 3,
}


@dataclass
class SreCheck:
    name: str
    verdict: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "verdict": self.verdict, "reason": self.reason}


@dataclass
class SreJudgment:
    recommendation: str
    confidence: float
    risk_assessment: str
    missing_evidence: list[str] = field(default_factory=list)
    sre_rationale: str = ""
    required_followups: list[str] = field(default_factory=list)
    checks: list[SreCheck] = field(default_factory=list)
    model: str = "native"
    agreement: bool | None = None
    raw_judgments: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "confidence": round(max(0.0, min(float(self.confidence), 1.0)), 3),
            "risk_assessment": self.risk_assessment,
            "missing_evidence": list(self.missing_evidence),
            "sre_rationale": self.sre_rationale,
            "required_followups": list(self.required_followups),
            "checks": [check.to_dict() for check in self.checks],
            "model": self.model,
            "agreement": self.agreement,
            "raw_judgments": list(self.raw_judgments),
            "error": self.error,
        }


class SreJudge:
    def evaluate(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        stage_results: dict[str, Any],
        blocking_reasons: list[str],
    ) -> SreJudgment:
        raise NotImplementedError


class NativeSreJudge(SreJudge):
    """Deterministic fallback SRE judgment.

    This does not replace policy checks; it translates the current evidence
    and blockers into a structured SRE-style recommendation.
    """

    def evaluate(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        stage_results: dict[str, Any],
        blocking_reasons: list[str],
    ) -> SreJudgment:
        checks = [
            SreCheck("decision_has_evidence", "pass" if decision.reasoning.get("evidence") else "fail", "decision includes evidence"),
            SreCheck("risk_level", "pass" if decision.risk.get("level") != "high" else "fail", f"risk={decision.risk.get('level')}"),
            SreCheck("blocking_reasons", "pass" if not blocking_reasons else "fail", "; ".join(blocking_reasons) or "none"),
        ]
        if decision.decision_type == "defer_until":
            recommendation = "defer"
            rationale = "Decision explicitly requests a timed recheck before action."
        elif any(_is_hard_blocker(reason) for reason in blocking_reasons):
            recommendation = "human_review"
            rationale = "Hard safety or review blockers are present."
        elif blocking_reasons:
            recommendation = "human_review"
            rationale = "Evaluation has unresolved blockers."
        else:
            recommendation = "execute"
            rationale = "No blockers remain after policy and readiness checks."
        return SreJudgment(
            recommendation=recommendation,
            confidence=0.75 if recommendation == "execute" else 0.65,
            risk_assessment=str(decision.risk.get("level", "medium")),
            missing_evidence=_missing_evidence_from_decision(decision),
            sre_rationale=rationale,
            required_followups=[] if recommendation == "execute" else ["human review or additional evidence"],
            checks=checks,
            model="native",
        )


@dataclass
class LlmSreJudgeConfig:
    enabled: bool = False
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 25
    max_tokens: int = 1500


class LlmSreJudge(SreJudge):
    def __init__(self, config: LlmSreJudgeConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        stage_results: dict[str, Any],
        blocking_reasons: list[str],
    ) -> SreJudgment:
        if not (self.config.enabled and self.config.base_url and self.config.api_key and self.config.model):
            return SreJudgment(
                recommendation="human_review",
                confidence=0.0,
                risk_assessment="high",
                sre_rationale="LLM SRE judge is not configured.",
                model=self.config.model or "llm_unconfigured",
                error="sre_judge_unconfigured",
            )
        payload = redact_for_observer(
            {
                "trigger": trigger.to_dict(),
                "decision": decision.to_dict(),
                "evaluation_stage_results": stage_results,
                "blocking_reasons": blocking_reasons,
            }
        )
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are a senior SRE evaluating a bounded remediation decision. "
                    "Return JSON only with recommendation execute|defer|human_review|reject, "
                    "confidence, risk_assessment low|medium|high, missing_evidence, "
                    "sre_rationale, required_followups, and checks."
                ),
            ),
            ChatMessage(role="user", content=json.dumps(payload, indent=2, sort_keys=True)),
        ]
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
            )
            parsed = json.loads(extract_message_content(response))
        except (ObserverClientError, json.JSONDecodeError, ValueError, TypeError) as exc:
            return SreJudgment(
                recommendation="human_review",
                confidence=0.0,
                risk_assessment="high",
                sre_rationale="SRE judge failed; route to human review.",
                model=self.config.model,
                error=str(exc),
            )
        return _judgment_from_payload(parsed, model=self.config.model)


class MultiModelSreJudge(SreJudge):
    def __init__(self, primary: SreJudge, secondary: SreJudge | None = None) -> None:
        self.primary = primary
        self.secondary = secondary

    def evaluate(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        stage_results: dict[str, Any],
        blocking_reasons: list[str],
    ) -> SreJudgment:
        primary = self.primary.evaluate(
            trigger=trigger,
            decision=decision,
            stage_results=stage_results,
            blocking_reasons=blocking_reasons,
        )
        if self.secondary is None:
            return primary
        secondary = self.secondary.evaluate(
            trigger=trigger,
            decision=decision,
            stage_results=stage_results,
            blocking_reasons=blocking_reasons,
        )
        agreement = primary.recommendation == secondary.recommendation
        chosen = _most_conservative([primary, secondary])
        if not agreement and chosen.recommendation == "execute":
            chosen = SreJudgment(
                recommendation="human_review",
                confidence=max(primary.confidence, secondary.confidence),
                risk_assessment="medium",
                sre_rationale="SRE judges disagreed; route to human review.",
                model=f"{primary.model}+{secondary.model}",
            )
        chosen.agreement = agreement
        chosen.raw_judgments = [primary.to_dict(), secondary.to_dict()]
        chosen.model = f"{primary.model}+{secondary.model}"
        return chosen


def _judgment_from_payload(payload: dict[str, Any], *, model: str) -> SreJudgment:
    recommendation = str(payload.get("recommendation", "human_review")).strip()
    if recommendation not in _RECOMMENDATION_RANK:
        recommendation = "human_review"
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    checks = []
    for item in payload.get("checks", []):
        if isinstance(item, dict):
            checks.append(
                SreCheck(
                    name=str(item.get("name", "unknown")),
                    verdict=str(item.get("verdict", "unknown")),
                    reason=str(item.get("reason", "")),
                )
            )
    return SreJudgment(
        recommendation=recommendation,
        confidence=confidence,
        risk_assessment=str(payload.get("risk_assessment", "medium")),
        missing_evidence=[str(item) for item in payload.get("missing_evidence", []) if item],
        sre_rationale=str(payload.get("sre_rationale", "")),
        required_followups=[str(item) for item in payload.get("required_followups", []) if item],
        checks=checks,
        model=model,
    )


def _most_conservative(judgments: list[SreJudgment]) -> SreJudgment:
    return max(judgments, key=lambda judgment: _RECOMMENDATION_RANK.get(judgment.recommendation, 2))


def _is_hard_blocker(reason: str) -> bool:
    lowered = reason.lower()
    return any(
        token in lowered
        for token in (
            "falls outside",
            "human review",
            "risk level is high",
            "not idempotent",
            "required credentials",
            "approval required",
            "not allowlisted",
        )
    )


def _missing_evidence_from_decision(decision: Decision) -> list[str]:
    evidence_pack = decision.reasoning.get("evidence_pack", {})
    artifact = evidence_pack.get("evidence_pack_artifact", {}) if isinstance(evidence_pack, dict) else {}
    missing = artifact.get("missing_fields", []) if isinstance(artifact, dict) else []
    return [str(item) for item in missing]
