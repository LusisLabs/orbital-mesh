from __future__ import annotations

from typing import Iterable


_TERMINAL_REVIEW_PATTERNS = (
    "recent rollback cooldown is active",
    "signal indicates multi-service impact",
    "signal indicates high business impact",
    "required execution credentials are unavailable",
    "cross-run correlation requires approval",
    "correlated failure type is",
    "unclassified trigger type",
)

_RECOVERABLE_REVIEW_PATTERNS = (
    "conflicting signals are present",
    "historical success rate is weak for",
    "no source run event ids available for analysis provenance",
    "kubernetes trigger lacks error signatures",
)

_TERMINAL_BLOCKER_PATTERNS = (
    "decision type falls outside the allowed action set",
    "execution plan falls outside the allowed action set",
    "duplicate evaluation suppressed for trigger_id",
    "scope requires approval before execution",
    "decision routes to human review",
    "recent rollback cooldown conflict",
    "risk level is high",
    "action is not idempotent",
    "rollback parameters are missing",
    "required credentials are unavailable",
    "remediation safety case has hard stops",
)

_RECOVERABLE_BLOCKER_PATTERNS = (
    "trajectory quality gate did not pass",
    "confidence below minimum threshold",
    "remediation safety score below execution threshold",
    "repo path is missing or does not exist",
    "allowed repo patch paths are missing",
    "bounded test commands are missing",
    "patch template is missing",
    "patch template field `",
)

_RETRY_HINTS = {
    "trajectory quality gate did not pass": "Expand grounded evidence and rerun the Mesh trajectory scorer against the updated run context.",
    "confidence below minimum threshold": "Add corroborating evidence from prior runs, active memory, or historical outcomes before reevaluating.",
    "conflicting signals are present": "Collect corroborating evidence to disambiguate the conflicting telemetry before rerunning.",
    "historical success rate is weak for": "Bring in stronger verification or service-specific prior cases before retrying the action.",
    "no source run event ids available for analysis provenance": "Preserve run-event provenance on the next attempt so the analysis can cite source evidence.",
    "kubernetes trigger lacks error signatures": "Collect fresh rollout event signatures or pod symptoms before retrying.",
    "repo path is missing or does not exist": "Restore bounded repo context before relaunching the remediation run.",
    "allowed repo patch paths are missing": "Attach bounded repo patch paths before retrying.",
    "bounded test commands are missing": "Attach bounded verification commands before retrying.",
    "patch template is missing": "Attach a bounded patch template before retrying.",
    "patch template field `": "Fill in the missing bounded patch template fields before retrying.",
}


def _matches(reason: str, patterns: Iterable[str]) -> str | None:
    lowered = reason.strip().lower()
    for pattern in patterns:
        if pattern.lower() in lowered:
            return pattern
    return None


def classify_review_reasons(review_reasons: Iterable[str]) -> dict[str, object]:
    terminal: list[str] = []
    recoverable: list[str] = []
    unclassified: list[str] = []
    for raw_reason in review_reasons:
        reason = str(raw_reason).strip()
        if not reason:
            continue
        if _matches(reason, _TERMINAL_REVIEW_PATTERNS):
            terminal.append(reason)
            continue
        if _matches(reason, _RECOVERABLE_REVIEW_PATTERNS):
            recoverable.append(reason)
            continue
        unclassified.append(reason)
    return {
        "terminal_review_reasons": terminal,
        "recoverable_review_reasons": recoverable,
        "unclassified_review_reasons": unclassified,
        "can_auto_remediate": bool(recoverable) and not terminal and not unclassified,
    }


def classify_blocking_reasons(
    blocking_reasons: Iterable[str],
    *,
    scenario_review_reasons: Iterable[str] = (),
) -> dict[str, object]:
    review = classify_review_reasons(scenario_review_reasons)
    terminal: list[str] = []
    recoverable: list[str] = []
    derived: list[str] = []
    unclassified: list[str] = []
    review_can_auto_remediate = bool(review["can_auto_remediate"])

    for raw_reason in blocking_reasons:
        reason = str(raw_reason).strip()
        if not reason:
            continue
        if reason in {"approval required before execution", "approval_required_before_execution"}:
            if review_can_auto_remediate:
                recoverable.append(reason)
            else:
                terminal.append(reason)
            derived.append(reason)
            continue
        if _matches(reason, _TERMINAL_BLOCKER_PATTERNS):
            terminal.append(reason)
            continue
        if _matches(reason, _RECOVERABLE_BLOCKER_PATTERNS):
            recoverable.append(reason)
            continue
        if reason in review["recoverable_review_reasons"]:
            recoverable.append(reason)
            continue
        if reason in review["terminal_review_reasons"] or reason in review["unclassified_review_reasons"]:
            terminal.append(reason)
            continue
        unclassified.append(reason)

    hints = []
    for reason in recoverable:
        matched = _matches(reason, _RETRY_HINTS)
        if matched is None:
            continue
        hint = _RETRY_HINTS[matched]
        if hint not in hints:
            hints.append(hint)

    can_auto_remediate = bool(recoverable) and not terminal and not unclassified
    return {
        "terminal_blockers": terminal,
        "recoverable_blockers": recoverable,
        "derived_blockers": derived,
        "unclassified_blockers": unclassified,
        "review_reason_analysis": review,
        "can_auto_remediate": can_auto_remediate,
        "recommended_route": "needs_more_evidence" if can_auto_remediate else ("human_review" if blocking_reasons else "execute"),
        "retry_hints": hints,
    }
