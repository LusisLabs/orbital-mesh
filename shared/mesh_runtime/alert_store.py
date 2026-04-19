"""Durable + in-memory store for normalized webhook alert events.

Every ingested alert is appended to a per-source JSONL log under
``<state_dir>/alerts/<source_id>/events.jsonl`` and kept in a bounded memory
tail for cheap reads. The JSONL layout is deliberately append-only so operators
can grep/tail it without locking.
"""

from __future__ import annotations

import fcntl
import json
import threading
from collections import deque
from pathlib import Path
from typing import Any, Deque

from .webhook_templates import AlertEvent


DEFAULT_TAIL_SIZE = 500


class AlertStore:
    def __init__(self, state_directory: str | Path, tail_size: int = DEFAULT_TAIL_SIZE):
        self.root = Path(state_directory) / "alerts"
        self.root.mkdir(parents=True, exist_ok=True)
        self._sources_path = Path(state_directory) / "webhook_sources.json"
        self._tail_size = tail_size
        self._lock = threading.Lock()
        self._tails: dict[str, Deque[AlertEvent]] = {}

    # ---- source registry --------------------------------------------------

    def load_sources(self) -> dict[str, dict[str, Any]]:
        if not self._sources_path.exists():
            return {}
        raw = self._sources_path.read_text().strip()
        if not raw:
            return {}
        parsed = json.loads(raw)
        return dict(parsed.get("sources", {}))

    def save_sources(self, sources: dict[str, dict[str, Any]]) -> None:
        self._sources_path.parent.mkdir(parents=True, exist_ok=True)
        with self._sources_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                handle.truncate()
                json.dump({"sources": sources}, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    # ---- events -----------------------------------------------------------

    def append(self, event: AlertEvent) -> AlertEvent:
        source_dir = self.root / event.source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / "events.jsonl"
        line = json.dumps(event.to_dict(), sort_keys=True) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(line)
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        with self._lock:
            tail = self._tails.setdefault(event.source_id, deque(maxlen=self._tail_size))
            tail.append(event)
        return event

    def list_events(
        self,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[AlertEvent]:
        if limit <= 0:
            return []
        with self._lock:
            if source_id is not None:
                tail = self._tails.get(source_id)
                if tail is not None:
                    # Cache is warm — use it.
                    return list(tail)[-limit:][::-1]
                events = self._read_from_disk(source_id, limit)
                self._tails[source_id] = deque(events[::-1], maxlen=self._tail_size)
                return events
            collected: list[AlertEvent] = []
            for candidate in sorted(self.root.iterdir()):
                if not candidate.is_dir():
                    continue
                collected.extend(self._read_from_disk(candidate.name, limit))
        collected.sort(key=lambda event: event.received_at, reverse=True)
        return collected[:limit]

    def latest_for_alert_id(self, source_id: str, alert_id: str) -> AlertEvent | None:
        with self._lock:
            tail = self._tails.get(source_id)
            if tail is not None:
                for event in reversed(tail):
                    if event.alert_id == alert_id:
                        return event
        for event in self._read_from_disk(source_id, limit=self._tail_size):
            if event.alert_id == alert_id:
                return event
        return None

    def _read_from_disk(self, source_id: str, limit: int) -> list[AlertEvent]:
        path = self.root / source_id / "events.jsonl"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()
        events: list[AlertEvent] = []
        # Read the tail (newest first).
        for line in lines[-limit:]:
            stripped = line.strip()
            if not stripped:
                continue
            events.append(AlertEvent.from_dict(json.loads(stripped)))
        return events[::-1]
