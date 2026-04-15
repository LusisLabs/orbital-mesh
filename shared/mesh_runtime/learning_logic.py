from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def learning_context_from_outcomes(
    outcomes: list[dict[str, Any]],
    service: str,
    endpoint: str | None = None,
    flag_key: str | None = None,
) -> dict[str, Any]:
    if not outcomes:
        return {"similar_prior_cases": 0, "rollbacks_last_24h": 0, "regressions_last_7d": 0}
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    similar = 0
    rollbacks_24h = 0
    regressions_7d = 0
    for record in outcomes:
        if record.get("service") != service:
            continue
        if endpoint is not None and record.get("endpoint") not in (None, endpoint):
            continue
        if flag_key is not None and record.get("flag_key") not in (None, flag_key):
            continue
        recorded_at = parse_timestamp(record.get("recorded_at", ""))
        if recorded_at is None:
            continue
        similar += 1
        if recorded_at >= cutoff_24h and record.get("decision_type") in (
            "rollback_deployment",
            "reduce_rollout",
            "disable_flag",
        ):
            rollbacks_24h += 1
        if recorded_at >= cutoff_7d and record.get("outcome") != "successful":
            regressions_7d += 1
    return {
        "similar_prior_cases": similar,
        "rollbacks_last_24h": rollbacks_24h,
        "regressions_last_7d": regressions_7d,
    }


def historical_success_rate(
    outcomes: list[dict[str, Any]],
    decision_type: str,
    service: str | None = None,
) -> float | None:
    total = 0
    successful = 0
    for record in outcomes:
        if record.get("decision_type") != decision_type:
            continue
        if service is not None and record.get("service") != service:
            continue
        total += 1
        if record.get("outcome") == "successful":
            successful += 1
    if total == 0:
        return None
    return round(successful / total, 3)


def recovery_patterns(outcomes: list[dict[str, Any]], service: str | None = None) -> dict[str, int]:
    patterns: dict[str, int] = {}
    for record in outcomes:
        if service is not None and record.get("service") != service:
            continue
        updates = record.get("world_model_updates", {})
        pattern = updates.get("service_recovery_pattern") or updates.get("cluster_recovery_pattern")
        if pattern:
            patterns[pattern] = patterns.get(pattern, 0) + 1
    return patterns


def parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
