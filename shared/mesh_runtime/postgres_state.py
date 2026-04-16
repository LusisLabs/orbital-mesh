from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import RuntimeConfig
from .control_plane_models import GoalRecord, RunEvent, RunSession
from .learning_logic import historical_success_rate, learning_context_from_outcomes, recovery_patterns
from .merkle import build_merkle_proof, build_merkle_snapshot, leaf_hash_for_payload
from .mesh_state_store import RunFilters
from .state import RuntimeStateStore
from .vault import VaultManager

MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "postgres" / "001_live_persistence.sql"


class PostgresStateStore:
    def __init__(self, config: RuntimeConfig):
        if not config.database_url:
            raise ValueError("MESH_DATABASE_URL is required when MESH_STATE_BACKEND=postgres")
        self.config = config
        self.database_url = config.database_url
        self.runtime_store = RuntimeStateStore(config.state_directory)
        self.vault = VaultManager(config.vault_path, runtime_config=config)
        self._initialize_schema()

    def ensure_default_goal(self) -> GoalRecord:
        goals = self.list_goals()
        if goals:
            return goals[0]
        now = _timestamp()
        return self.save_goal(
            GoalRecord(
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
        )

    def list_goals(self) -> list[GoalRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM goals ORDER BY created_at DESC").fetchall()
        return [GoalRecord(**_json_payload(row[0])) for row in rows]

    def save_goal(self, goal: GoalRecord) -> GoalRecord:
        goal = GoalRecord(**{**goal.to_dict(), "note_path": self.vault.write_goal(goal)})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO goals (goal_id, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (goal_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at
                """,
                (goal.goal_id, self._jsonb(goal.to_dict()), goal.created_at, goal.updated_at),
            )
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

    def create_run(self, *args: Any, **kwargs: Any) -> RunSession:
        return self.create_run_session(*args, **kwargs)

    def get_run_session(self, run_id: str) -> RunSession | None:
        with self._connect() as conn:
            row = conn.execute("SELECT snapshot FROM run_snapshots WHERE run_id = %s", (run_id,)).fetchone()
        return RunSession(**_json_payload(row[0])) if row else None

    def get_run(self, run_id: str) -> RunSession | None:
        return self.get_run_session(run_id)

    def list_run_sessions(self, limit: int = 50) -> list[RunSession]:
        return self.list_runs(RunFilters(limit=limit))

    def list_runs(self, filters: RunFilters | None = None) -> list[RunSession]:
        filters = filters or RunFilters()
        where = []
        params: list[Any] = []
        if filters.status is not None:
            where.append("r.status = %s")
            params.append(filters.status)
        if filters.stage is not None:
            where.append("r.stage = %s")
            params.append(filters.stage)
        if filters.goal_id is not None:
            where.append("r.goal_id = %s")
            params.append(filters.goal_id)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(filters.limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT s.snapshot
                FROM run_snapshots s
                JOIN runs r ON r.run_id = s.run_id
                {where_sql}
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                tuple(params),
            ).fetchall()
        return [RunSession(**_json_payload(row[0])) for row in rows]

    def save_run_session(self, session: RunSession) -> RunSession:
        with self._connect() as conn:
            self._save_run_session_tx(conn, session)
        self._materialize_vault(session.run_id)
        return session

    def update_snapshot(self, run_id: str, snapshot: dict[str, Any]) -> RunSession:
        session = RunSession(**snapshot)
        if session.run_id != run_id:
            raise ValueError(f"snapshot run_id {session.run_id!r} does not match {run_id!r}")
        return self.save_run_session(session)

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
        with self._connect() as conn:
            self._lock_run_tx(conn, run_id)
            sequence = self._next_sequence(conn, run_id)
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
            self._append_event_tx(conn, event)
            session = self._get_run_session_tx(conn, run_id)
            if session is not None:
                events = self._list_events_tx(conn, run_id)
                snapshot = build_merkle_snapshot(run_id, events)
                session.latest_event_id = event.event_id
                session.latest_event_sequence = event.sequence
                session.latest_merkle_root = snapshot.root_hash
                session.updated_at = _timestamp()
                self._save_run_session_tx(conn, session)
                conn.execute(
                    "INSERT INTO merkle_roots (run_id, event_id, root_hash) VALUES (%s, %s, %s)",
                    (run_id, event.event_id, snapshot.root_hash),
                )
        self._materialize_vault(run_id)
        return event

    def append_event(self, run_id: str, event: RunEvent) -> RunEvent:
        if event.run_id != run_id:
            raise ValueError(f"event run_id {event.run_id!r} does not match {run_id!r}")
        with self._connect() as conn:
            self._lock_run_tx(conn, run_id)
            if event.sequence <= 0:
                event.sequence = self._next_sequence(conn, run_id)
            if not event.merkle_leaf_hash:
                event.merkle_leaf_hash = leaf_hash_for_payload(event.canonical_payload())
            self._append_event_tx(conn, event)
            session = self._get_run_session_tx(conn, run_id)
            if session is not None:
                events = self._list_events_tx(conn, run_id)
                snapshot = build_merkle_snapshot(run_id, events)
                session.latest_event_id = event.event_id
                session.latest_event_sequence = event.sequence
                session.latest_merkle_root = snapshot.root_hash
                session.updated_at = _timestamp()
                self._save_run_session_tx(conn, session)
                conn.execute(
                    "INSERT INTO merkle_roots (run_id, event_id, root_hash) VALUES (%s, %s, %s)",
                    (run_id, event.event_id, snapshot.root_hash),
                )
        self._materialize_vault(run_id)
        return event

    def list_run_events(self, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        with self._connect() as conn:
            events = self._list_events_tx(conn, run_id)
        return [event for event in events if event.sequence > after_sequence]

    def list_events(self, run_id: str) -> list[RunEvent]:
        return self.list_run_events(run_id)

    def get_merkle_snapshot(self, run_id: str):
        return build_merkle_snapshot(run_id, self.list_run_events(run_id))

    def get_merkle_proof(self, run_id: str, event_id: str):
        return build_merkle_proof(run_id, self.list_run_events(run_id), event_id)

    def record_operator_note(self, run_id: str, note: str) -> RunSession | None:
        session = self.get_run_session(run_id)
        if session is None:
            return None
        session.operator_notes.append(note)
        session.updated_at = _timestamp()
        self.save_run_session(session)
        return session

    def record_approval(self, run_id: str, approval: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO approvals (run_id, event_id, approval) VALUES (%s, %s, %s)",
                (run_id, approval.get("event_id"), self._jsonb(approval)),
            )

    def record_learning_outcome(self, outcome: dict[str, Any]) -> None:
        record = deepcopy(outcome)
        record.setdefault("recorded_at", _timestamp())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_outcomes
                (run_id, event_id, decision_type, service, endpoint, outcome, recorded_at, world_model_updates)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.get("run_id"),
                    record.get("event_id"),
                    record["decision_type"],
                    record["service"],
                    record.get("endpoint"),
                    record["outcome"],
                    record["recorded_at"],
                    self._jsonb(record.get("world_model_updates", {})),
                ),
            )

    def get_learning_context(self, service: str, endpoint: str | None = None) -> dict[str, Any]:
        return learning_context_from_outcomes(self._load_learning_outcomes(service=service, endpoint=endpoint), service, endpoint)

    def get_historical_success_rate(self, decision_type: str, service: str | None = None) -> float | None:
        return historical_success_rate(self._load_learning_outcomes(decision_type=decision_type, service=service), decision_type, service)

    def get_recovery_patterns(self, service: str | None = None) -> dict[str, int]:
        return recovery_patterns(self._load_learning_outcomes(service=service), service)

    def put_artifact(self, artifact: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (run_id, event_id, artifact_key, uri, path, content_hash, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    artifact.get("run_id"),
                    artifact.get("event_id"),
                    artifact.get("artifact_key"),
                    artifact.get("uri"),
                    artifact.get("path"),
                    artifact.get("content_hash"),
                    self._jsonb(artifact.get("metadata", artifact)),
                ),
            )

    def search_memory(self, query: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
        del scope
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_id, run_id, kind, content, metadata, created_at
                FROM memory_items
                WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)
                ORDER BY created_at DESC
                LIMIT 25
                """,
                (query,),
            ).fetchall()
        return [
            {
                "memory_id": row[0],
                "run_id": row[1],
                "kind": row[2],
                "content": row[3],
                "metadata": _json_payload(row[4]),
                "created_at": str(row[5]),
            }
            for row in rows
        ]

    def tree(self) -> list[dict[str, Any]]:
        return self.vault.tree()

    def read_document(self, relative_path: str) -> dict[str, str]:
        return self.vault.read_document(relative_path)

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(MIGRATION_PATH.read_text(encoding="utf-8"))

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Postgres backend requires psycopg. Install psycopg or use MESH_STATE_BACKEND=file.") from exc
        return psycopg.connect(self.database_url)

    def _jsonb(self, value: Any):
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise RuntimeError("Postgres backend requires psycopg JSON support.") from exc
        return Jsonb(value)

    def _save_run_session_tx(self, conn: Any, session: RunSession) -> None:
        payload = session.to_dict()
        conn.execute(
            """
            INSERT INTO runs (run_id, goal_id, scenario_key, stage, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
              goal_id = EXCLUDED.goal_id,
              scenario_key = EXCLUDED.scenario_key,
              stage = EXCLUDED.stage,
              status = EXCLUDED.status,
              updated_at = EXCLUDED.updated_at
            """,
            (
                session.run_id,
                session.goal_id,
                session.scenario_key,
                session.stage,
                session.status,
                session.created_at,
                session.updated_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO run_snapshots (run_id, snapshot, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET snapshot = EXCLUDED.snapshot, updated_at = EXCLUDED.updated_at
            """,
            (session.run_id, self._jsonb(payload), session.updated_at),
        )

    def _get_run_session_tx(self, conn: Any, run_id: str) -> RunSession | None:
        row = conn.execute("SELECT snapshot FROM run_snapshots WHERE run_id = %s", (run_id,)).fetchone()
        return RunSession(**_json_payload(row[0])) if row else None

    def _next_sequence(self, conn: Any, run_id: str) -> int:
        row = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = %s", (run_id,)).fetchone()
        return int(row[0])

    def _lock_run_tx(self, conn: Any, run_id: str) -> None:
        row = conn.execute("SELECT run_id FROM runs WHERE run_id = %s FOR UPDATE", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"run {run_id!r} does not exist")

    def _append_event_tx(self, conn: Any, event: RunEvent) -> None:
        conn.execute(
            """
            INSERT INTO run_events
            (run_id, sequence, event_id, stage, event_type, recorded_at, payload, summary, merkle_leaf_hash, artifact_key, integration_name, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event.run_id,
                event.sequence,
                event.event_id,
                event.stage,
                event.event_type,
                event.recorded_at,
                self._jsonb(event.payload),
                self._jsonb(event.summary) if event.summary is not None else None,
                event.merkle_leaf_hash,
                event.artifact_key,
                event.integration_name,
                event.status,
            ),
        )

    def _list_events_tx(self, conn: Any, run_id: str) -> list[RunEvent]:
        rows = conn.execute(
            """
            SELECT event_id, run_id, sequence, stage, event_type, recorded_at, payload, summary,
                   merkle_leaf_hash, artifact_key, integration_name, status
            FROM run_events
            WHERE run_id = %s
            ORDER BY sequence ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            RunEvent(
                event_id=row[0],
                run_id=row[1],
                sequence=row[2],
                stage=row[3],
                event_type=row[4],
                recorded_at=str(row[5]),
                payload=_json_payload(row[6]),
                summary=_json_payload(row[7]) if row[7] is not None else None,
                merkle_leaf_hash=row[8],
                artifact_key=row[9],
                integration_name=row[10],
                status=row[11],
            )
            for row in rows
        ]

    def _load_learning_outcomes(
        self,
        decision_type: str | None = None,
        service: str | None = None,
        endpoint: str | None = None,
    ) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if decision_type is not None:
            where.append("decision_type = %s")
            params.append(decision_type)
        if service is not None:
            where.append("service = %s")
            params.append(service)
        if endpoint is not None:
            where.append("(endpoint IS NULL OR endpoint = %s)")
            params.append(endpoint)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT run_id, event_id, decision_type, service, endpoint, outcome, recorded_at, world_model_updates
                FROM learning_outcomes
                {where_sql}
                ORDER BY recorded_at DESC
                LIMIT 500
                """,
                tuple(params),
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "event_id": row[1],
                "decision_type": row[2],
                "service": row[3],
                "endpoint": row[4],
                "outcome": row[5],
                "recorded_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
                "world_model_updates": _json_payload(row[7]),
            }
            for row in rows
        ]

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


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
