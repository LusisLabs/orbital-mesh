from __future__ import annotations

import fcntl
import json
import threading
from collections import deque
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Iterator
from uuid import uuid4

from .config import RuntimeConfig
from .control_plane_models import GoalRecord, RunEvent, RunSession
from .merkle import build_merkle_proof, build_merkle_snapshot, leaf_hash_for_payload
from .state import RuntimeStateStore
from .vault import VaultManager


_EVENT_CACHE_SIZE = 512


class ControlPlaneStateStore:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.state_directory = Path(config.state_directory)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self.runtime_store = RuntimeStateStore(self.state_directory)
        self.vault = VaultManager(config.vault_path, runtime_config=config)
        self._goals_path = self.state_directory / "goals.json"
        self._run_sessions_path = self.state_directory / "run_sessions.json"
        self._run_events_dir = self.state_directory / "run_events"
        self._run_events_dir.mkdir(parents=True, exist_ok=True)
        # Hot cache: SSE subscribers poll list_run_events on a 1s loop; reading
        # JSON from disk + redeserializing is 10-50x more expensive than a
        # deque slice. The tail is bounded per run_id and invalidated on write.
        self._event_tail_cache: dict[str, Deque[RunEvent]] = {}
        self._event_cache_lock = threading.Lock()
        self._session_cache: dict[str, RunSession] = {}

    def ensure_default_goal(self) -> GoalRecord:
        goals = self.list_goals()
        if goals:
            return goals[0]
        now = _timestamp()
        goal = GoalRecord(
            goal_id="goal_default",
            title="Operate the mesh remediation loop with continuous visibility",
            objective=(
                "Keep the feature-flag remediation system observable, steerable, and reversible while "
                "capturing durable operator memory for each run."
            ),
            success_criteria=[
                "Every run streams stage transitions live.",
                "Execution never bypasses evaluation or operator policy.",
                "Run history is mirrored into the local vault with Merkle roots.",
            ],
            status="active",
            created_at=now,
            updated_at=now,
            tags=["operations", "control-plane"],
        )
        return self.save_goal(goal)

    def list_goals(self) -> list[GoalRecord]:
        if not self._goals_path.exists():
            return []
        with _locked_json(self._goals_path) as payload:
            records = payload.get("goals", [])
            return [GoalRecord(**record) for record in records if isinstance(record, dict)]

    def save_goal(self, goal: GoalRecord) -> GoalRecord:
        goal = replace(goal, note_path=self.vault.write_goal(goal))
        with _locked_json(self._goals_path) as payload:
            records = payload.setdefault("goals", [])
            for index, existing in enumerate(records):
                if existing.get("goal_id") == goal.goal_id:
                    records[index] = goal.to_dict()
                    break
            else:
                records.insert(0, goal.to_dict())
        return goal

    def create_run_session(
        self,
        goal_id: str | None,
        scenario_key: str | None,
        steering_mode: str,
        auto_mode: bool,
        pause_points: list[str],
        evaluation_mode: str,
        orchestration_mode: str,
        artifacts: dict[str, Any],
    ) -> RunSession:
        now = _timestamp()
        session = RunSession(
            run_id=f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}",
            created_at=now,
            updated_at=now,
            goal_id=goal_id,
            scenario_key=scenario_key,
            stage="queued",
            status="queued",
            steering_mode=steering_mode,
            auto_mode=auto_mode,
            pause_points=list(pause_points),
            pending_pause_stage=None,
            evaluation_mode=evaluation_mode,
            orchestration_mode=orchestration_mode,
            latest_event_id=None,
            latest_event_sequence=0,
            latest_merkle_root=None,
            operator_notes=[],
            artifacts=deepcopy(artifacts),
            error=None,
        )
        self.save_run_session(session)
        return session

    def list_run_sessions(self, limit: int = 50) -> list[RunSession]:
        if not self._run_sessions_path.exists():
            return []
        with _locked_json(self._run_sessions_path) as payload:
            sessions = payload.get("runs", [])
            return [RunSession(**record) for record in sessions[:limit] if isinstance(record, dict)]

    def get_run_session(self, run_id: str) -> RunSession | None:
        sessions = self.list_run_sessions(limit=200)
        for session in sessions:
            if session.run_id == run_id:
                return session
        return None

    def save_run_session(self, session: RunSession) -> RunSession:
        session_dict = session.to_dict()
        with _locked_json(self._run_sessions_path) as payload:
            records = payload.setdefault("runs", [])
            for index, existing in enumerate(records):
                if existing.get("run_id") == session.run_id:
                    records[index] = session_dict
                    break
            else:
                records.insert(0, session_dict)
            records.sort(key=lambda record: record.get("created_at", ""), reverse=True)
        self._materialize_vault(session.run_id)
        return session

    def append_run_event(
        self,
        run_id: str,
        stage: str,
        event_type: str,
        payload: dict[str, Any],
        summary: dict[str, Any] | None = None,
        artifact_key: str | None = None,
        integration_name: str | None = None,
        status: str | None = None,
    ) -> RunEvent:
        event_path = self._run_events_dir / f"{run_id}.json"
        with _locked_json(event_path) as event_payload:
            existing_events = [RunEvent(**record) for record in event_payload.get("events", []) if isinstance(record, dict)]
            sequence = len(existing_events) + 1
            event = RunEvent(
                event_id=f"evt_{sequence:04d}_{uuid4().hex[:8]}",
                run_id=run_id,
                sequence=sequence,
                stage=stage,
                event_type=event_type,
                recorded_at=_timestamp(),
                payload=deepcopy(payload),
                summary=deepcopy(summary),
                artifact_key=artifact_key,
                integration_name=integration_name,
                status=status,
            )
            event.merkle_leaf_hash = leaf_hash_for_payload(event.canonical_payload())
            existing_events.append(event)
            event_payload["events"] = [record.to_dict() for record in existing_events]

        with self._event_cache_lock:
            tail = self._event_tail_cache.setdefault(
                run_id, deque(maxlen=_EVENT_CACHE_SIZE)
            )
            tail.append(event)

        snapshot = self.get_merkle_snapshot(run_id)
        session = self.get_run_session(run_id)
        if session is not None:
            session.latest_event_id = event.event_id
            session.latest_event_sequence = event.sequence
            session.latest_merkle_root = snapshot.root_hash
            session.updated_at = _timestamp()
            self.save_run_session(session)
        return event

    def list_run_events(self, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        with self._event_cache_lock:
            cached = self._event_tail_cache.get(run_id)
            if cached is not None:
                return [event for event in cached if event.sequence > after_sequence]
        event_path = self._run_events_dir / f"{run_id}.json"
        if not event_path.exists():
            return []
        with _locked_json(event_path) as payload:
            records = payload.get("events", [])
            events = [RunEvent(**record) for record in records if isinstance(record, dict)]
        with self._event_cache_lock:
            # Warm the cache with whatever we just loaded; subsequent polls hit
            # the hot path.
            tail = deque(events[-_EVENT_CACHE_SIZE:], maxlen=_EVENT_CACHE_SIZE)
            self._event_tail_cache[run_id] = tail
        return [event for event in events if event.sequence > after_sequence]

    def get_merkle_snapshot(self, run_id: str):
        events = self.list_run_events(run_id)
        return build_merkle_snapshot(run_id, events)

    def get_merkle_proof(self, run_id: str, event_id: str):
        events = self.list_run_events(run_id)
        return build_merkle_proof(run_id, events, event_id)

    def record_operator_note(self, run_id: str, note: str) -> RunSession | None:
        session = self.get_run_session(run_id)
        if session is None:
            return None
        session.operator_notes.append(note)
        session.updated_at = _timestamp()
        self.save_run_session(session)
        return session

    def tree(self) -> list[dict[str, Any]]:
        return self.vault.tree()

    def read_document(self, relative_path: str) -> dict[str, str]:
        return self.vault.read_document(relative_path)

    def _materialize_vault(self, run_id: str) -> None:
        session = self.get_run_session(run_id)
        if session is None:
            return
        goal = None
        if session.goal_id is not None:
            for candidate in self.list_goals():
                if candidate.goal_id == session.goal_id:
                    goal = candidate
                    break
        events = self.list_run_events(run_id)
        merkle = build_merkle_snapshot(run_id, events)
        self.vault.write_run_bundle(session, events, merkle, goal)


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


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

