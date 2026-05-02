from __future__ import annotations

from collections import Counter
from typing import Any

from shared.mesh_runtime.control_plane_models import AgentAttempt, AgentTask

_SUPPORTING_ACTIONS = {
    "open_pr",
    "review",
    "root_cause_review",
    "stage_validation",
    "evo_discover_candidate",
    "prepare_benchmark",
}

_NOISE_FLAGS = {
    "allowed_paths_missing",
    "code_write_gate_closed",
    "evo_workspace_missing",
    "kubernetes_scope_missing",
    "non_code_task",
    "test_commands_missing",
}


def reconcile_agent_tasks(tasks: list[AgentTask]) -> dict[str, Any]:
    attempts: list[AgentAttempt] = [attempt for task in tasks for attempt in task.attempts]
    actions = [attempt.recommended_action for attempt in attempts if attempt.status == "completed"]
    risk_flags = [flag for attempt in attempts for flag in attempt.risk_flags]
    normalized_actions = [_normalize_action(action) for action in actions]
    counts = Counter(actions)
    normalized_counts = Counter(normalized_actions)
    selected_action = _select_action(normalized_counts)
    completed = sum(1 for attempt in attempts if attempt.status == "completed")
    material_actions = {action for action in normalized_actions if action != "supporting_artifact"}
    disagreement = len(material_actions) > 1
    material_risk_flags = [flag for flag in risk_flags if flag not in _NOISE_FLAGS]
    risk_penalty = min(len(material_risk_flags) * 0.08, 0.4)
    support_count = normalized_counts.get(selected_action, 0) + normalized_counts.get("supporting_artifact", 0)
    agreement_score = (support_count / len(actions)) if actions else 0.0
    confidence = max(0.0, min(1.0, agreement_score - risk_penalty))
    if disagreement and confidence < 0.67:
        selected_action = "human_review"
    return {
        "selected_action": selected_action,
        "confidence": round(confidence, 4),
        "attempt_count": len(attempts),
        "completed_attempt_count": completed,
        "recommendation_counts": dict(counts),
        "normalized_recommendation_counts": dict(normalized_counts),
        "disagreement": disagreement,
        "risk_flags": sorted(set(risk_flags)),
        "material_risk_flags": sorted(set(material_risk_flags)),
        "losing_attempt_ids": [
            attempt.attempt_id
            for attempt in attempts
            if _normalize_action(attempt.recommended_action) not in {selected_action, "supporting_artifact"}
            or any(flag not in _NOISE_FLAGS for flag in attempt.risk_flags)
        ],
        "all_attempt_ids": [attempt.attempt_id for attempt in attempts],
    }


def _normalize_action(action: str) -> str:
    if action in _SUPPORTING_ACTIONS:
        return "supporting_artifact"
    return action


def _select_action(counts: Counter[str]) -> str:
    actionable = {key: value for key, value in counts.items() if key != "supporting_artifact"}
    if "execute" in actionable:
        return "execute"
    if actionable:
        return Counter(actionable).most_common(1)[0][0]
    return "human_review"
