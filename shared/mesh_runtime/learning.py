"""Learning store — aggregates remediation outcomes for feedback-to-decision learning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

    def count_recent_decisions(
        self,
        decision_type: str,
        service: str,
        within_seconds: int,
    ) -> int:
        """Count Mesh's own past ``decision_type`` outcomes for ``service``
        in the last ``within_seconds`` of wall-clock time.

        Used to enforce restart-rate caps even when the inbound trigger
        didn't carry a host-stamped count. The trigger's
        ``systemd_restarts_last_1h`` reflects what systemd remembers;
        this method reflects what *Mesh* did. We take the max of both
        to protect against the case where the trigger is delivered with
        the count missing or stale.

        Outcomes are recorded by ``FeedbackService`` at T+10m / T+30m,
        so a restart issued <10 min ago is not yet counted here. That's
        the correct gap for the cross-run case (which is about decisions
        spaced 30 minutes apart, not 30 seconds).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
        count = 0
        outcomes: list[dict[str, Any]]
        if self._state_store is not None and hasattr(self._state_store, "list_learning_outcomes"):
            try:
                outcomes = list(self._state_store.list_learning_outcomes() or [])
            except Exception:
                outcomes = []
        else:
            outcomes = self._load_outcomes()
        for outcome in outcomes:
            if outcome.get("decision_type") != decision_type:
                continue
            if outcome.get("service") != service:
                continue
            recorded = outcome.get("recorded_at")
            if not isinstance(recorded, str):
                continue
            try:
                ts = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                count += 1
        return count

    def _load_outcomes(self) -> list[dict[str, Any]]:
        if not self._outcomes_path.exists():
            return []
        try:
            with LockedJsonFile(self._outcomes_path) as payload:
                return list(payload.get("outcomes", []))
        except ValueError:
            return []
