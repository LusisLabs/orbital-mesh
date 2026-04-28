from __future__ import annotations

import threading
from collections import deque
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque
from uuid import uuid4

from .config import RuntimeConfig
from .contracts import ClaimRecord, MemoryPacket, ObservationRecord, RelationshipRecord, RetrievalRecord, SupersessionRecord
from .control_plane_models import GoalRecord, RunEvent, RunSession
from .json_store import LockedJsonFile
from .learning_logic import historical_success_rate, learning_context_from_outcomes, recovery_patterns
from .mesh_state_store import RunFilters
from .merkle import build_merkle_proof, build_merkle_snapshot, leaf_hash_for_payload
from .state import RuntimeStateStore
from .vault import VaultManager


_EVENT_CACHE_SIZE = 512


class FileStateStore:
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
        self._memory_dir = self.state_directory / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._observations_path = self._memory_dir / "observations.json"
        self._claims_path = self._memory_dir / "claims.json"
        self._relationships_path = self._memory_dir / "relationships.json"
        self._supersessions_path = self._memory_dir / "supersessions.json"
        self._retrievals_path = self._memory_dir / "retrievals.json"
        self._packets_path = self._memory_dir / "packets.json"
        self._benchmarks_path = self.state_directory / "benchmarks" / "records.json"
        self._benchmarks_path.parent.mkdir(parents=True, exist_ok=True)
        # Hot cache: SSE subscribers poll list_run_events on a 1s loop; reading
        # JSON from disk + redeserializing is 10-50x more expensive than a
        # deque slice. The tail is bounded per run_id, populated on append
        # and warmed on first read.
        self._event_tail_cache: dict[str, Deque[RunEvent]] = {}
        self._event_cache_lock = threading.Lock()

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
        with LockedJsonFile(self._goals_path) as payload:
            records = payload.get("goals", [])
            return [GoalRecord(**record) for record in records if isinstance(record, dict)]

    def save_goal(self, goal: GoalRecord) -> GoalRecord:
        goal = replace(goal, note_path=self.vault.write_goal(goal))
        with LockedJsonFile(self._goals_path) as payload:
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

    def list_run_sessions(self, limit: int = 50) -> list[RunSession]:
        if not self._run_sessions_path.exists():
            return []
        with LockedJsonFile(self._run_sessions_path) as payload:
            sessions = payload.get("runs", [])
            return [RunSession(**record) for record in sessions[:limit] if isinstance(record, dict)]

    def list_runs(self, filters: RunFilters | None = None) -> list[RunSession]:
        filters = filters or RunFilters()
        sessions = self.list_run_sessions(limit=max(filters.limit, 1))
        if filters.status is not None:
            sessions = [session for session in sessions if session.status == filters.status]
        if filters.stage is not None:
            sessions = [session for session in sessions if session.stage == filters.stage]
        if filters.goal_id is not None:
            sessions = [session for session in sessions if session.goal_id == filters.goal_id]
        return sessions[: filters.limit]

    def get_run_session(self, run_id: str) -> RunSession | None:
        sessions = self.list_run_sessions(limit=200)
        for session in sessions:
            if session.run_id == run_id:
                return session
        return None

    def get_run(self, run_id: str) -> RunSession | None:
        return self.get_run_session(run_id)

    def save_run_session(self, session: RunSession) -> RunSession:
        session_dict = session.to_dict()
        with LockedJsonFile(self._run_sessions_path) as payload:
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
        event_path = self._run_events_dir / f"{run_id}.json"
        with LockedJsonFile(event_path) as event_payload:
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

    def append_event(self, run_id: str, event: RunEvent) -> RunEvent:
        if event.run_id != run_id:
            raise ValueError(f"event run_id {event.run_id!r} does not match {run_id!r}")
        event_path = self._run_events_dir / f"{run_id}.json"
        with LockedJsonFile(event_path) as event_payload:
            existing_events = [RunEvent(**record) for record in event_payload.get("events", []) if isinstance(record, dict)]
            if event.sequence <= 0:
                event.sequence = len(existing_events) + 1
            if not event.merkle_leaf_hash:
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
        with LockedJsonFile(event_path) as payload:
            records = payload.get("events", [])
            events = [RunEvent(**record) for record in records if isinstance(record, dict)]
        with self._event_cache_lock:
            # Warm the cache with whatever we just loaded; subsequent polls hit
            # the hot path.
            tail = deque(events[-_EVENT_CACHE_SIZE:], maxlen=_EVENT_CACHE_SIZE)
            self._event_tail_cache[run_id] = tail
        return [event for event in events if event.sequence > after_sequence]

    def list_events(self, run_id: str) -> list[RunEvent]:
        return self.list_run_events(run_id)

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

    def record_benchmark(self, record: dict[str, Any]) -> None:
        with LockedJsonFile(self._benchmarks_path) as payload:
            rows = payload.setdefault("benchmarks", [])
            rows.insert(0, deepcopy(record))
            payload["benchmarks"] = rows[:1000]

    def list_benchmarks(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._benchmarks_path.exists():
            return []
        with LockedJsonFile(self._benchmarks_path) as payload:
            rows = payload.get("benchmarks", [])
        return [deepcopy(row) for row in rows[:limit] if isinstance(row, dict)]

    def get_benchmark(self, benchmark_id: str) -> dict[str, Any] | None:
        for record in self.list_benchmarks(limit=1000):
            if record.get("benchmark_id") == benchmark_id:
                return record
        return None

    def record_approval(self, run_id: str, approval: dict[str, Any]) -> None:
        session = self.get_run_session(run_id)
        if session is None:
            return
        approvals = session.artifacts.setdefault("approvals", [])
        if isinstance(approvals, list):
            approvals.append(deepcopy(approval))
        else:
            session.artifacts["approvals"] = [deepcopy(approval)]
        session.updated_at = _timestamp()
        self.save_run_session(session)

    def record_learning_outcome(self, outcome: dict[str, Any]) -> None:
        learning_path = self.state_directory / "learning" / "outcomes.json"
        learning_path.parent.mkdir(parents=True, exist_ok=True)
        record = deepcopy(outcome)
        record.setdefault("recorded_at", _timestamp())
        with LockedJsonFile(learning_path) as payload:
            records = payload.setdefault("outcomes", [])
            records.append(record)
            if len(records) > 500:
                payload["outcomes"] = records[-500:]

    def get_learning_context(self, service: str, endpoint: str | None = None) -> dict[str, Any]:
        return learning_context_from_outcomes(self._load_learning_outcomes(), service, endpoint)

    def get_historical_success_rate(self, decision_type: str, service: str | None = None) -> float | None:
        return historical_success_rate(self._load_learning_outcomes(), decision_type, service)

    def get_recovery_patterns(self, service: str | None = None) -> dict[str, int]:
        return recovery_patterns(self._load_learning_outcomes(), service)

    def put_artifact(self, artifact: dict[str, Any]) -> None:
        artifact_path = self.state_directory / "artifacts.json"
        with LockedJsonFile(artifact_path) as payload:
            records = payload.setdefault("artifacts", [])
            records.append(deepcopy(artifact))

    def append_observation(self, record: dict[str, Any]) -> dict[str, Any]:
        observation = ObservationRecord.from_dict(record)
        with LockedJsonFile(self._observations_path) as payload:
            records = payload.setdefault("observations", [])
            records.append(observation.to_dict())
        self.vault.write_memory_observation(observation.to_dict())
        return observation.to_dict()

    def list_observations(self, scope: dict[str, Any], filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        with LockedJsonFile(self._observations_path) as payload:
            records = list(payload.get("observations", []))
        matches = [record for record in records if _scope_matches(record.get("scope", {}), scope) and _observation_matches(record, filters)]
        return matches[: int(filters.get("limit", len(matches)))]

    def save_claim(self, record: dict[str, Any]) -> dict[str, Any]:
        claim = ClaimRecord.from_dict(record)
        with LockedJsonFile(self._claims_path) as payload:
            records = payload.setdefault("claims", [])
            for index, existing in enumerate(records):
                if existing.get("claim_id") == claim.claim_id:
                    records[index] = claim.to_dict()
                    break
            else:
                records.append(claim.to_dict())
        self.vault.write_memory_claim(claim.to_dict())
        return claim.to_dict()

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        for record in self.list_claims({}, {"limit": 1000}):
            if record.get("claim_id") == claim_id:
                return record
        return None

    def list_claims(self, scope: dict[str, Any], filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        with LockedJsonFile(self._claims_path) as payload:
            records = list(payload.get("claims", []))
        matches = [record for record in records if _claim_scope_matches(record, scope) and _claim_matches(record, filters)]
        matches.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return matches[: int(filters.get("limit", len(matches)))]

    def save_relationship(self, record: dict[str, Any]) -> dict[str, Any]:
        relationship = RelationshipRecord.from_dict(record)
        with LockedJsonFile(self._relationships_path) as payload:
            records = payload.setdefault("relationships", [])
            for index, existing in enumerate(records):
                if existing.get("relationship_id") == relationship.relationship_id:
                    records[index] = relationship.to_dict()
                    break
            else:
                records.append(relationship.to_dict())
        return relationship.to_dict()

    def list_relationships(
        self,
        node_ids: list[str] | None = None,
        relationship_types: list[str] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        del scope
        with LockedJsonFile(self._relationships_path) as payload:
            records = list(payload.get("relationships", []))
        return [
            record
            for record in records
            if _relationship_matches(record, node_ids=node_ids, relationship_types=relationship_types)
        ]

    def save_supersession(self, record: dict[str, Any]) -> dict[str, Any]:
        supersession = SupersessionRecord.from_dict(record)
        with LockedJsonFile(self._supersessions_path) as payload:
            records = payload.setdefault("supersessions", [])
            records.append(supersession.to_dict())
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
        with LockedJsonFile(self._retrievals_path) as payload:
            records = payload.setdefault("retrievals", [])
            records.append(retrieval.to_dict())
        self.vault.write_memory_retrieval(retrieval.to_dict())
        return retrieval.to_dict()

    def save_memory_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        model = MemoryPacket.from_dict(packet)
        with LockedJsonFile(self._packets_path) as payload:
            records = payload.setdefault("packets", [])
            for index, existing in enumerate(records):
                if existing.get("packet_id") == model.packet_id:
                    records[index] = model.to_dict()
                    break
            else:
                records.append(model.to_dict())
        return model.to_dict()

    def get_memory_packet(self, packet_id: str) -> dict[str, Any] | None:
        with LockedJsonFile(self._packets_path) as payload:
            for record in payload.get("packets", []):
                if record.get("packet_id") == packet_id:
                    return deepcopy(record)
        return None

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

    def _load_learning_outcomes(self) -> list[dict[str, Any]]:
        learning_path = self.state_directory / "learning" / "outcomes.json"
        if not learning_path.exists():
            return []
        try:
            with LockedJsonFile(learning_path) as payload:
                return list(payload.get("outcomes", []))
        except ValueError:
            return []


ControlPlaneStateStore = FileStateStore


def _scope_matches(candidate: dict[str, Any], scope: dict[str, Any]) -> bool:
    if not scope:
        return True
    for key, value in scope.items():
        if value is None:
            continue
        candidate_value = candidate.get(key)
        if candidate_value is None:
            continue
        if candidate_value != value:
            return False
    return True


def _observation_matches(record: dict[str, Any], filters: dict[str, Any]) -> bool:
    if "service" in filters and filters["service"] is not None and record.get("service") != filters["service"]:
        return False
    if "run_id" in filters and filters["run_id"] is not None and record.get("run_id") != filters["run_id"]:
        return False
    if "kind" in filters and filters["kind"] is not None and record.get("kind") != filters["kind"]:
        return False
    return True


def _claim_scope_matches(record: dict[str, Any], scope: dict[str, Any]) -> bool:
    if not scope:
        return True
    candidate_scope = record.get("scope")
    if isinstance(candidate_scope, dict) and _scope_matches(candidate_scope, scope):
        return True
    service = scope.get("service")
    if service is None:
        return True
    return service in record.get("entity_refs", [])


def _claim_matches(record: dict[str, Any], filters: dict[str, Any]) -> bool:
    if "tier" in filters and filters["tier"] is not None and record.get("tier") != filters["tier"]:
        return False
    if "state" in filters and filters["state"] is not None and record.get("state") != filters["state"]:
        return False
    return True


def _relationship_matches(
    record: dict[str, Any],
    *,
    node_ids: list[str] | None,
    relationship_types: list[str] | None,
) -> bool:
    if relationship_types and record.get("type") not in relationship_types:
        return False
    if not node_ids:
        return True
    node_set = set(node_ids)
    return record.get("from_id") in node_set or record.get("to_id") in node_set


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
