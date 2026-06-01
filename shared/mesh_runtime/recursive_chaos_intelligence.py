from __future__ import annotations

import hashlib
import json
from typing import Any

from .schema_validation import validate_payload


RECURSIVE_CHAOS_INTELLIGENCE_SCORE_VERSION = "mesh.recursive_chaos.intelligence_score.v1"
RECURSIVE_CHAOS_AUTOMATION_SUMMARY_VERSION = "mesh.recursive_chaos.automation_summary.v1"


def build_recursive_chaos_intelligence_score(
    *,
    automation_record: dict[str, Any],
    registry_profiles: list[dict[str, Any]],
    prior_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prior_records = prior_records or []
    executed = {str(item) for item in automation_record.get("profiles_executed", []) if str(item)}
    all_profiles = [profile for profile in registry_profiles if isinstance(profile, dict) and profile.get("profile_id")]
    all_profile_ids = {str(profile["profile_id"]) for profile in all_profiles}
    p0_profile_ids = {str(profile["profile_id"]) for profile in all_profiles if profile.get("priority_phase") == "p0"}

    profile_coverage = _ratio(len(executed & all_profile_ids), len(all_profile_ids))
    p0_coverage = _ratio(len(executed & p0_profile_ids), len(p0_profile_ids))
    cycles_total = _positive_int(automation_record.get("cycles_total"))
    learning_density = min(_positive_int(automation_record.get("learning_packet_count")) / max(cycles_total, 1), 1.0)
    repeated_hash_rate = _repeated_advisory_hash_rate(automation_record, prior_records)
    novelty_score = 1.0 - repeated_hash_rate
    safety_score = 1.0 if automation_record.get("execute") is False else 0.25

    score = _clamp(
        (profile_coverage * 0.30)
        + (p0_coverage * 0.20)
        + (learning_density * 0.20)
        + (novelty_score * 0.20)
        + (safety_score * 0.10)
    )
    scheduler_weights = _scheduler_weights(all_profiles=all_profiles, executed=executed)
    packet = {
        "schema_version": RECURSIVE_CHAOS_INTELLIGENCE_SCORE_VERSION,
        "state_slice": RECURSIVE_CHAOS_INTELLIGENCE_SCORE_VERSION,
        "score": score,
        "profile_coverage": _clamp(profile_coverage),
        "p0_coverage": _clamp(p0_coverage),
        "learning_density": _clamp(learning_density),
        "novelty_score": _clamp(novelty_score),
        "repeated_advisory_hash_rate": _clamp(repeated_hash_rate),
        "scheduler_weights": scheduler_weights,
        "recommended_next_profiles": [item["profile_id"] for item in scheduler_weights[:8]],
        "training_allowed": False,
        "production_authority": False,
        "score_hash": "",
    }
    packet["score_hash"] = f"sha256:{_canonical_sha256(packet)}"
    return packet


def build_recursive_chaos_feedback_gate(
    *,
    run_id: str,
    summary: dict[str, Any],
    advisory: dict[str, Any] | None = None,
    intelligence_score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    advisory = advisory or {}
    intelligence_score = intelligence_score or {}
    profiles = [str(item) for item in summary.get("profiles", [])]
    scheduler_weights = list(intelligence_score.get("scheduler_weights") or _default_scheduler_weights(profiles))
    recommended_next_profiles = list(
        intelligence_score.get("recommended_next_profiles")
        or [item.get("profile_id") for item in scheduler_weights if item.get("profile_id")]
    )
    packet = {
        "schema_version": "mesh.recursive_chaos.feedback_gate.v1",
        "state_slice": "mesh.recursive_chaos.feedback_gate.v1",
        "run_id": run_id,
        "session_status": summary.get("status"),
        "source": "recursive_chaos_arena",
        "mesh_brain_mode": "recommend_only",
        "mesh_model_mode": "recommend_only",
        "scheduler_weights": scheduler_weights,
        "recommended_next_profiles": recommended_next_profiles[:8],
        "sealed_source_packet_refs": list(advisory.get("sealed_source_packet_refs") or summary.get("learning_packet_refs") or []),
        "intelligence_score": intelligence_score or None,
        "mesh_model_training_allowed": False,
        "training_allowed": False,
        "production_authority": False,
        "promotion_authority": False,
        "sandbox_execute_allowed": False,
        "sandbox_execute_requires": [
            "local_disposable_target",
            "compose_sandbox_or_disposable_kubernetes_context",
            "operator_launcher_or_admin_role",
        ],
    }
    packet["feedback_hash"] = f"sha256:{_canonical_sha256(packet)}"
    validate_payload("recursive-chaos-feedback-gate.schema.json", packet)
    return packet


def validate_recursive_chaos_automation_summary(payload: dict[str, Any]) -> None:
    validate_payload("recursive-chaos-automation-summary.schema.json", payload)


def _scheduler_weights(*, all_profiles: list[dict[str, Any]], executed: set[str]) -> list[dict[str, Any]]:
    phase_weight = {"p0": 1.25, "p1": 1.0, "p2": 0.75}
    weighted: list[dict[str, Any]] = []
    for profile in all_profiles:
        profile_id = str(profile["profile_id"])
        phase = str(profile.get("priority_phase") or "unknown")
        missing_bonus = 0.45 if profile_id not in executed else 0.0
        proof_gate_bonus = min(len(profile.get("proof_gates") or []) * 0.03, 0.18)
        buyer_bonus = min(len(profile.get("buyer_classes") or []) * 0.04, 0.12)
        weight = round(phase_weight.get(phase, 0.5) + missing_bonus + proof_gate_bonus + buyer_bonus, 4)
        reason = "priority_phase"
        if missing_bonus:
            reason = "under_tested_profile"
        elif proof_gate_bonus >= 0.15:
            reason = "high_proof_gate_surface"
        weighted.append(
            {
                "profile_id": profile_id,
                "priority_phase": phase,
                "weight": weight,
                "reason": reason,
            }
        )
    return sorted(weighted, key=lambda item: (-float(item["weight"]), str(item["profile_id"])))


def _default_scheduler_weights(profiles: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile_id,
            "priority_phase": "unknown",
            "weight": 1.0,
            "reason": "sealed_packet_feedback",
        }
        for profile_id in profiles
    ]


def _repeated_advisory_hash_rate(current: dict[str, Any], prior_records: list[dict[str, Any]]) -> float:
    advisory_hash = current.get("advisory_hash")
    if not advisory_hash:
        return 0.0
    prior_hashes = {record.get("advisory_hash") for record in prior_records if isinstance(record, dict)}
    return 1.0 if advisory_hash in prior_hashes else 0.0


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _clamp(value: float) -> float:
    return round(max(0.0, min(float(value), 1.0)), 6)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
