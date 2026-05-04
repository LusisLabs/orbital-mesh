from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import RuntimeConfig
from .contracts import ClaimRecord, MemoryPacket, ObservationRecord, RelationshipRecord, RetrievalRecord, SupersessionRecord
from .control_plane_models import GoalRecord, RunEvent, RunSession
from .learning_logic import historical_success_rate, learning_context_from_outcomes, recovery_patterns
from .merkle import build_merkle_proof, build_merkle_snapshot, leaf_hash_for_payload
from .mesh_state_store import RunFilters
from .state import RuntimeStateStore
from .vault import VaultManager

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "migrations" / "postgres"
_VAULT_FORCE_STAGES = {"completed", "failed", "cancelled", "no_trigger", "awaiting_operator", "recovery_spawned"}
_FINAL_STAGES = {"completed", "failed", "cancelled", "no_trigger", "recovery_spawned"}
_VAULT_QUEUE_SIZE = 256
_LOG = logging.getLogger("mesh.postgres_state_store")


class PostgresStateStore:
    def __init__(self, config: RuntimeConfig):
        if not config.database_url:
            raise ValueError("MESH_DATABASE_URL is required when MESH_STATE_BACKEND=postgres")
        self.config = config
        self.database_url = config.database_url
        self.runtime_store = RuntimeStateStore(config.state_directory)
        self.vault = VaultManager(config.vault_path, runtime_config=config)
        self._last_vault_materialized_at: dict[str, float] = {}
        self._vault_materialize_lock = threading.Lock()
        self._vault_materialize_min_interval_seconds = float(
            os.getenv("MESH_VAULT_MATERIALIZE_MIN_INTERVAL_SECONDS", "30")
        )
        self._vault_stop = threading.Event()
        self._vault_queue: queue.Queue[str | None] | None = None
        self._vault_thread: threading.Thread | None = None
        if config.vault_mirror_mode == "async":
            self._vault_queue = queue.Queue(maxsize=_VAULT_QUEUE_SIZE)
            self._vault_thread = threading.Thread(
                target=self._vault_mirror_loop,
                daemon=True,
                name="mesh-postgres-vault-mirror",
            )
            self._vault_thread.start()
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
        session = RunSession.new(
            goal_id=goal_id,
            scenario_key=scenario_key,
            steering_mode=steering_mode,
            auto_mode=auto_mode,
            pause_points=pause_points,
            evaluation_mode=evaluation_mode,
            orchestration_mode=orchestration_mode,
            artifacts=artifacts,
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
            session = self._save_run_session_tx(conn, session)
        terminal = session.stage in _VAULT_FORCE_STAGES or session.status in _VAULT_FORCE_STAGES
        if terminal:
            self._materialize_vault(session.run_id, force=True)
        else:
            self._schedule_materialize_vault(session.run_id)
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
        self._schedule_materialize_vault(run_id)
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
        self._schedule_materialize_vault(run_id)
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

    def record_benchmark(self, record: dict[str, Any]) -> None:
        payload = deepcopy(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO benchmark_records
                (benchmark_id, run_id, scenario_id, recorded_at, score, passed, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (benchmark_id) DO UPDATE SET
                  run_id = EXCLUDED.run_id,
                  scenario_id = EXCLUDED.scenario_id,
                  recorded_at = EXCLUDED.recorded_at,
                  score = EXCLUDED.score,
                  passed = EXCLUDED.passed,
                  payload = EXCLUDED.payload
                """,
                (
                    payload["benchmark_id"],
                    payload["run_id"],
                    payload["scenario_id"],
                    payload["recorded_at"],
                    payload.get("score", 0.0),
                    payload.get("passed", False),
                    self._jsonb(payload),
                ),
            )

    def list_benchmarks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM benchmark_records ORDER BY recorded_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [_json_payload(row[0]) for row in rows]

    def get_benchmark(self, benchmark_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM benchmark_records WHERE benchmark_id = %s",
                (benchmark_id,),
            ).fetchone()
        return _json_payload(row[0]) if row else None

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

    def append_observation(self, record: dict[str, Any]) -> dict[str, Any]:
        observation = ObservationRecord.from_dict(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO observation_records
                (observation_id, service, run_id, scope, kind, content, payload, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (observation_id) DO NOTHING
                """,
                (
                    observation.observation_id,
                    observation.service,
                    observation.run_id,
                    self._jsonb(observation.scope),
                    observation.kind,
                    observation.content,
                    self._jsonb(observation.to_dict()),
                    observation.created_at,
                ),
            )
        self.vault.write_memory_observation(observation.to_dict())
        return observation.to_dict()

    def list_observations(self, scope: dict[str, Any], filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        where = []
        params: list[Any] = []
        if scope.get("service") is not None:
            where.append("service = %s")
            params.append(scope["service"])
        if scope.get("run_id") is not None:
            where.append("(run_id = %s OR run_id IS NULL)")
            params.append(scope["run_id"])
        if filters.get("kind") is not None:
            where.append("kind = %s")
            params.append(filters["kind"])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(int(filters.get("limit", 250)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload
                FROM observation_records
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tuple(params),
            ).fetchall()
        return [_json_payload(row[0]) for row in rows]

    def save_claim(self, record: dict[str, Any]) -> dict[str, Any]:
        claim = ClaimRecord.from_dict(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO claim_records
                (claim_id, state, tier, statement, confidence, payload, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (claim_id) DO UPDATE SET
                  state = EXCLUDED.state,
                  tier = EXCLUDED.tier,
                  statement = EXCLUDED.statement,
                  confidence = EXCLUDED.confidence,
                  payload = EXCLUDED.payload,
                  updated_at = EXCLUDED.updated_at
                """,
                (
                    claim.claim_id,
                    claim.state,
                    claim.tier,
                    claim.statement,
                    claim.confidence,
                    self._jsonb(claim.to_dict()),
                    claim.updated_at,
                ),
            )
        self.vault.write_memory_claim(claim.to_dict())
        return claim.to_dict()

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM claim_records WHERE claim_id = %s", (claim_id,)).fetchone()
        return _json_payload(row[0]) if row else None

    def list_claims(self, scope: dict[str, Any], filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        rows_payload = self._load_claim_rows(filters)
        claims = [_json_payload(row) for row in rows_payload]
        if scope.get("service") is not None:
            claims = [record for record in claims if scope["service"] in record.get("entity_refs", [])]
        return claims[: int(filters.get("limit", len(claims)))]

    def save_relationship(self, record: dict[str, Any]) -> dict[str, Any]:
        relationship = RelationshipRecord.from_dict(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO relationship_records
                (relationship_id, from_id, to_id, relationship_type, payload)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (relationship_id) DO UPDATE SET
                  from_id = EXCLUDED.from_id,
                  to_id = EXCLUDED.to_id,
                  relationship_type = EXCLUDED.relationship_type,
                  payload = EXCLUDED.payload
                """,
                (
                    relationship.relationship_id,
                    relationship.from_id,
                    relationship.to_id,
                    relationship.type,
                    self._jsonb(relationship.to_dict()),
                ),
            )
        return relationship.to_dict()

    def list_relationships(
        self,
        node_ids: list[str] | None = None,
        relationship_types: list[str] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        del scope
        where = []
        params: list[Any] = []
        if node_ids:
            where.append("(from_id = ANY(%s) OR to_id = ANY(%s))")
            params.extend([node_ids, node_ids])
        if relationship_types:
            where.append("relationship_type = ANY(%s)")
            params.append(relationship_types)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT payload FROM relationship_records {where_sql}",
                tuple(params),
            ).fetchall()
        return [_json_payload(row[0]) for row in rows]

    def save_supersession(self, record: dict[str, Any]) -> dict[str, Any]:
        supersession = SupersessionRecord.from_dict(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO supersession_records
                (supersession_id, old_claim_id, new_claim_id, payload, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (supersession_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    supersession.supersession_id,
                    supersession.old_claim_id,
                    supersession.new_claim_id,
                    self._jsonb(supersession.to_dict()),
                    supersession.created_at,
                ),
            )
        old_claim = self.get_claim(supersession.old_claim_id)
        if old_claim is not None:
            old_claim["state"] = "superseded"
            old_claim["superseded_by"] = supersession.new_claim_id
            old_claim["updated_at"] = supersession.created_at
            self.save_claim(old_claim)
        return supersession.to_dict()

    def retrieve_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        from .memory_retrieval import MemoryRetrievalService

        return MemoryRetrievalService(self).retrieve(request)

    def record_memory_retrieval(self, record: dict[str, Any]) -> dict[str, Any]:
        retrieval = RetrievalRecord.from_dict(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_records
                (retrieval_id, query, scope, channels, payload, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (retrieval_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    retrieval.retrieval_id,
                    retrieval.query,
                    self._jsonb(retrieval.scope),
                    retrieval.channels,
                    self._jsonb(retrieval.to_dict()),
                    retrieval.created_at,
                ),
            )
        self.vault.write_memory_retrieval(retrieval.to_dict())
        return retrieval.to_dict()

    def save_memory_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        model = MemoryPacket.from_dict(packet)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_packets (packet_id, scope, payload, generated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (packet_id) DO UPDATE SET payload = EXCLUDED.payload, generated_at = EXCLUDED.generated_at
                """,
                (
                    model.packet_id,
                    self._jsonb(model.scope),
                    self._jsonb(model.to_dict()),
                    model.generated_at,
                ),
            )
        return model.to_dict()

    def get_memory_packet(self, packet_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM memory_packets WHERE packet_id = %s", (packet_id,)).fetchone()
        return _json_payload(row[0]) if row else None

    def run_memory_maintenance(self, now: str | None = None) -> dict[str, Any]:
        from .memory_lifecycle import MemoryLifecycleService

        return MemoryLifecycleService(self).run_memory_maintenance(now=now)

    def search_memory(self, query: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
        from .memory_retrieval import MemoryRetrievalService

        return MemoryRetrievalService(self).legacy_search(query, scope)

    def tree(self) -> list[dict[str, Any]]:
        return self.vault.tree()

    def read_document(self, relative_path: str) -> dict[str, str]:
        return self.vault.read_document(relative_path)

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            for path in sorted(MIGRATION_DIR.glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))

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

    def _save_run_session_tx(self, conn: Any, session: RunSession) -> RunSession:
        conn.execute("SELECT run_id FROM runs WHERE run_id = %s FOR UPDATE", (session.run_id,)).fetchone()
        payload = session.to_dict()
        current = self._get_run_session_tx(conn, session.run_id)
        if current is not None:
            payload = _merge_session_snapshot(payload, current.to_dict())
            session = RunSession(**payload)
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
        return session

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

    def _load_claim_rows(self, filters: dict[str, Any]) -> list[Any]:
        where = []
        params: list[Any] = []
        if filters.get("tier") is not None:
            where.append("tier = %s")
            params.append(filters["tier"])
        if filters.get("state") is not None:
            where.append("state = %s")
            params.append(filters["state"])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(int(filters.get("limit", 1000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload
                FROM claim_records
                {where_sql}
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                tuple(params),
            ).fetchall()
        return [row[0] for row in rows]

    def _materialize_vault(self, run_id: str, *, force: bool = False) -> None:
        with self._vault_materialize_lock:
            now = time.monotonic()
            last_materialized = self._last_vault_materialized_at.get(run_id)
            if (
                not force
                and last_materialized is not None
                and now - last_materialized < self._vault_materialize_min_interval_seconds
            ):
                return
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
            self._last_vault_materialized_at[run_id] = now

    def _schedule_materialize_vault(self, run_id: str) -> None:
        if self.config.vault_mirror_mode == "off":
            return
        if self._vault_stop.is_set():
            self._materialize_vault(run_id, force=True)
            return
        if self._vault_queue is None:
            self._materialize_vault(run_id)
            return
        try:
            self._vault_queue.put_nowait(run_id)
        except queue.Full:
            self._materialize_vault(run_id)

    def _vault_mirror_loop(self) -> None:
        assert self._vault_queue is not None
        while True:
            run_id = self._vault_queue.get()
            try:
                if run_id is None:
                    return
                self._materialize_vault(run_id)
            except Exception:
                _LOG.exception("postgres-state vault materialization failed for run %s", run_id)
            finally:
                self._vault_queue.task_done()

    def flush_background_tasks(self, timeout: float = 5.0) -> bool:
        vault_queue = self._vault_queue
        if vault_queue is None:
            return True
        deadline = time.monotonic() + max(timeout, 0.0)
        while getattr(vault_queue, "unfinished_tasks", 0) > 0:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self, timeout: float = 5.0) -> None:
        vault_queue = self._vault_queue
        vault_thread = self._vault_thread
        if vault_queue is None or vault_thread is None:
            return
        if not vault_thread.is_alive():
            return
        deadline = time.monotonic() + max(timeout, 0.0)
        self.flush_background_tasks(timeout=timeout)
        self._vault_stop.set()
        remaining = max(0.0, deadline - time.monotonic())
        try:
            vault_queue.put(None, timeout=remaining)
        except queue.Full:
            return
        vault_thread.join(timeout=max(0.0, deadline - time.monotonic()))


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _merge_session_snapshot(candidate: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = _preserve_event_cursor(candidate, current)
    merged = _preserve_final_lifecycle(merged, current)
    merged["artifacts"] = _merge_artifacts(merged.get("artifacts"), current.get("artifacts"))
    return merged


def _preserve_event_cursor(candidate: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    current_sequence = int(current.get("latest_event_sequence") or 0)
    candidate_sequence = int(candidate.get("latest_event_sequence") or 0)
    if current_sequence <= candidate_sequence:
        return candidate
    merged = dict(candidate)
    merged["latest_event_id"] = current.get("latest_event_id")
    merged["latest_event_sequence"] = current_sequence
    merged["latest_merkle_root"] = current.get("latest_merkle_root")
    return merged


def _preserve_final_lifecycle(candidate: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    current_final = current.get("stage") in _FINAL_STAGES or current.get("status") in _FINAL_STAGES
    candidate_final = candidate.get("stage") in _FINAL_STAGES or candidate.get("status") in _FINAL_STAGES
    if not current_final or candidate_final:
        return candidate
    merged = dict(candidate)
    for key in ("stage", "status", "pending_pause_stage", "error"):
        merged[key] = current.get(key)
    return merged


def _merge_artifacts(candidate_raw: Any, current_raw: Any) -> dict[str, Any]:
    candidate = candidate_raw if isinstance(candidate_raw, dict) else {}
    current = current_raw if isinstance(current_raw, dict) else {}
    merged = {**current, **candidate}
    current_agent_tasks = current.get("agent_tasks")
    candidate_agent_tasks = candidate.get("agent_tasks")
    if isinstance(current_agent_tasks, list) and isinstance(candidate_agent_tasks, dict):
        if candidate_agent_tasks.get("status") == "pending":
            merged["agent_tasks"] = current_agent_tasks
    return merged


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
