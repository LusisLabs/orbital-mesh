"""Learning store — aggregates remediation outcomes for feedback-to-decision learning."""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_MAX_OUTCOMES = 500


class LearningStore:
    def __init__(self, state_directory: str | Path):
        self._learning_dir = Path(state_directory) / "learning"
        self._learning_dir.mkdir(parents=True, exist_ok=True)
        self._outcomes_path = self._learning_dir / "outcomes.json"

    def record_outcome(
        self,
        decision_type: str,
        service: str,
        endpoint: str,
        outcome: str,
        world_model_updates: dict[str, Any],
    ) -> None:
        with _locked_json(self._outcomes_path) as payload:
            records = payload.setdefault("outcomes", [])
            records.append({
                "decision_type": decision_type,
                "service": service,
                "endpoint": endpoint,
                "outcome": outcome,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "world_model_updates": world_model_updates,
            })
            if len(records) > _MAX_OUTCOMES:
                payload["outcomes"] = records[-_MAX_OUTCOMES:]

    def enrich_context(
        self,
        service: str,
        endpoint: str | None = None,
        flag_key: str | None = None,
    ) -> dict[str, Any]:
        outcomes = self._load_outcomes()
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
            recorded_at = _parse_timestamp(record.get("recorded_at", ""))
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

    def get_historical_success_rate(
        self,
        decision_type: str,
        service: str | None = None,
    ) -> float | None:
        outcomes = self._load_outcomes()
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

    def get_recovery_patterns(self, service: str | None = None) -> dict[str, int]:
        outcomes = self._load_outcomes()
        patterns: dict[str, int] = {}
        for record in outcomes:
            if service is not None and record.get("service") != service:
                continue
            updates = record.get("world_model_updates", {})
            pattern = updates.get("service_recovery_pattern") or updates.get("cluster_recovery_pattern")
            if pattern:
                patterns[pattern] = patterns.get(pattern, 0) + 1
        return patterns

    def _load_outcomes(self) -> list[dict[str, Any]]:
        if not self._outcomes_path.exists():
            return []
        try:
            with _locked_json(self._outcomes_path) as payload:
                return list(payload.get("outcomes", []))
        except (json.JSONDecodeError, ValueError):
            return []


def _parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


class _locked_json:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None
        self.payload: dict[str, Any] = {}

    def __enter__(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        self.handle.seek(0)
        raw = self.handle.read()
        self.payload = json.loads(raw) if raw.strip() else {}
        return self.payload

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        if exc_type is None:
            self.handle.seek(0)
            self.handle.truncate()
            json.dump(self.payload, self.handle, indent=2, sort_keys=True)
            self.handle.write("\n")
            self.handle.flush()
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
