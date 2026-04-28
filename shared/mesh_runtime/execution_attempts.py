from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .json_store import LockedJsonFile


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ExecutionAttemptStore:
    """Durable ledger for side-effecting execution attempts.

    The critical state is ``remote_command_dispatched`` without an outcome:
    for stateful node restarts, retrying after that point can double-restart
    the host. The orchestrator treats that state as unknown outcome and
    escalates instead of replaying.
    """

    def __init__(self, state_directory: str | Path):
        self.path = Path(state_directory) / "execution_attempts.json"

    def get(self, idempotency_key: str) -> dict[str, Any] | None:
        with LockedJsonFile(self.path) as payload:
            attempts = payload.get("attempts", {})
            record = attempts.get(idempotency_key) if isinstance(attempts, dict) else None
            return dict(record) if isinstance(record, dict) else None

    def begin(self, idempotency_key: str, decision_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        with LockedJsonFile(self.path) as payload:
            attempts = payload.setdefault("attempts", {})
            record = attempts.get(idempotency_key)
            if isinstance(record, dict):
                record["attempt_count"] = int(record.get("attempt_count", 0) or 0) + 1
                record["updated_at"] = now
            else:
                record = {
                    "idempotency_key": idempotency_key,
                    "decision_id": decision_id,
                    "system": plan.get("system"),
                    "action": plan.get("action"),
                    "status": "attempt_started",
                    "attempt_count": 1,
                    "created_at": now,
                    "updated_at": now,
                }
                attempts[idempotency_key] = record
            return dict(record)

    def mark_dispatched(self, idempotency_key: str) -> dict[str, Any]:
        return self._update(idempotency_key, status="remote_command_dispatched", dispatched_at=_now_iso())

    def complete(
        self,
        idempotency_key: str,
        *,
        status: str,
        external_refs: dict[str, Any],
        failure: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._update(
            idempotency_key,
            status=status,
            completed_at=_now_iso(),
            external_refs=dict(external_refs),
            failure=dict(failure) if isinstance(failure, dict) else None,
        )

    def _update(self, idempotency_key: str, **updates: Any) -> dict[str, Any]:
        with LockedJsonFile(self.path) as payload:
            attempts = payload.setdefault("attempts", {})
            record = attempts.setdefault(
                idempotency_key,
                {
                    "idempotency_key": idempotency_key,
                    "status": "attempt_started",
                    "attempt_count": 0,
                    "created_at": _now_iso(),
                },
            )
            record.update(updates)
            record["updated_at"] = _now_iso()
            return dict(record)


def has_terminal_outcome(record: dict[str, Any] | None) -> bool:
    return bool(record and record.get("status") in {"succeeded", "failed", "rejected"})


def dispatched_without_outcome(record: dict[str, Any] | None) -> bool:
    return bool(record and record.get("status") == "remote_command_dispatched")
