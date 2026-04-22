from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def reciprocal_rank_fusion(rankings: dict[str, list[str]], constant: int = 60) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for _channel, ranked_ids in rankings.items():
        for rank, item_id in enumerate(ranked_ids, start=1):
            scores[item_id] += 1.0 / (constant + rank)
    return dict(scores)


def freshness_score(created_at: str | None, *, now: datetime | None = None, half_life_days: float = 30.0) -> float:
    if not created_at:
        return 0.5
    try:
        parsed = datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return 0.5
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age_days = max((now - parsed).total_seconds() / 86400.0, 0.0)
    if half_life_days <= 0:
        return 0.0
    return max(0.0, min(1.0, 0.5 ** (age_days / half_life_days)))


def confidence_from_factors(factors: dict[str, Any]) -> float:
    weights = {
        "support_score": 0.28,
        "recency_score": 0.18,
        "authority_score": 0.22,
        "consistency_score": 0.18,
        "verification_score": 0.14,
    }
    total = 0.0
    for key, weight in weights.items():
        value = factors.get(key, 0.0)
        try:
            total += max(0.0, min(float(value), 1.0)) * weight
        except (TypeError, ValueError):
            continue
    return round(max(0.0, min(total, 1.0)), 3)


def support_score(support_count: int) -> float:
    if support_count <= 0:
        return 0.0
    if support_count >= 5:
        return 1.0
    return round(min(1.0, 0.2 * support_count + 0.1), 3)
