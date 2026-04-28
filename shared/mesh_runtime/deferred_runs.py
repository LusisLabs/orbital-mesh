from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .json_store import LockedJsonFile


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class DeferredRunStore:
    def __init__(self, state_directory: str | Path):
        self.path = Path(state_directory) / "deferred_runs.json"

    def create(
        self,
        *,
        source_run_id: str,
        due_at: str,
        signal_payload: dict[str, Any],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "defer_id": f"defer_{uuid4().hex[:12]}",
            "source_run_id": source_run_id,
            "due_at": due_at,
            "signal_payload": signal_payload,
            "parameters": parameters,
            "status": "pending",
            "created_at": now_iso(),
            "claimed_at": None,
            "child_run_id": None,
        }
        with LockedJsonFile(self.path) as payload:
            records = payload.setdefault("deferred_runs", [])
            records.append(record)
        return dict(record)

    def claim_due(self, limit: int = 10) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        claimed: list[dict[str, Any]] = []
        with LockedJsonFile(self.path) as payload:
            records = payload.setdefault("deferred_runs", [])
            for record in records:
                if len(claimed) >= limit:
                    break
                if not isinstance(record, dict) or record.get("status") != "pending":
                    continue
                try:
                    due_at = parse_iso(str(record.get("due_at")))
                except (TypeError, ValueError):
                    due_at = now
                if due_at > now:
                    continue
                record["status"] = "claimed"
                record["claimed_at"] = now_iso()
                claimed.append(dict(record))
        return claimed

    def mark_spawned(self, defer_id: str, child_run_id: str) -> None:
        with LockedJsonFile(self.path) as payload:
            for record in payload.setdefault("deferred_runs", []):
                if isinstance(record, dict) and record.get("defer_id") == defer_id:
                    record["status"] = "spawned"
                    record["child_run_id"] = child_run_id
                    record["updated_at"] = now_iso()
                    return

    def mark_failed(self, defer_id: str, reason: str) -> None:
        with LockedJsonFile(self.path) as payload:
            for record in payload.setdefault("deferred_runs", []):
                if isinstance(record, dict) and record.get("defer_id") == defer_id:
                    record["status"] = "failed"
                    record["failure"] = {"reason": reason}
                    record["updated_at"] = now_iso()
                    return
