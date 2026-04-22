"""Learning store — aggregates remediation outcomes for feedback-to-decision learning."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .json_store import LockedJsonFile
from .learning_logic import historical_success_rate, learning_context_from_outcomes, recovery_patterns

if TYPE_CHECKING:
    from .mesh_state_store import MeshStateStore

_MAX_OUTCOMES = 500


class LearningStore:
    def __init__(self, state_directory: str | Path, state_store: MeshStateStore | None = None):
        self._learning_dir = Path(state_directory) / "learning"
        self._learning_dir.mkdir(parents=True, exist_ok=True)
        self._outcomes_path = self._learning_dir / "outcomes.json"
        self._state_store = state_store

    def record_outcome(
        self,
        decision_type: str,
        service: str,
        endpoint: str,
        outcome: str,
        world_model_updates: dict[str, Any],
    ) -> None:
        if self._state_store is not None:
            self._state_store.record_learning_outcome({
                "decision_type": decision_type,
                "service": service,
                "endpoint": endpoint,
                "outcome": outcome,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "world_model_updates": world_model_updates,
            })
            return
        with LockedJsonFile(self._outcomes_path) as payload:
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
        if self._state_store is not None:
            return self._state_store.get_learning_context(service, endpoint)
        return learning_context_from_outcomes(self._load_outcomes(), service, endpoint, flag_key)

    def get_historical_success_rate(
        self,
        decision_type: str,
        service: str | None = None,
    ) -> float | None:
        if self._state_store is not None:
            return self._state_store.get_historical_success_rate(decision_type, service)
        return historical_success_rate(self._load_outcomes(), decision_type, service)

    def get_recovery_patterns(self, service: str | None = None) -> dict[str, int]:
        if self._state_store is not None:
            return self._state_store.get_recovery_patterns(service)
        return recovery_patterns(self._load_outcomes(), service)

    def _load_outcomes(self) -> list[dict[str, Any]]:
        if not self._outcomes_path.exists():
            return []
        try:
            with LockedJsonFile(self._outcomes_path) as payload:
                return list(payload.get("outcomes", []))
        except ValueError:
            return []
