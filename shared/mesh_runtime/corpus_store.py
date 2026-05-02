"""Durable incident-corpus database and memory projection helpers.

Single-tenant by design. A Mesh deployment monitors one operational fleet
(its set of nodes / services); multi-tenant isolation is not modeled here.
If this assumption ever changes, every query in this module must grow a
tenant-id predicate — there is no implicit scoping.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid5, NAMESPACE_URL

from .breakthrough import (
    breakthrough_threshold_report,
    coverage_counts,
    normalize_coverage_labels,
    promotion_pattern_counts,
)


_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CorpusQuery:
    """Structured query over normalized incident-corpus rows."""

    service: str | None = None
    target_class: str | None = None
    outcome: str | None = None
    profile: str | None = None
    promotion_candidate: bool | None = None
    text: str | None = None
    limit: int = 50


class IncidentCorpusDatabase:
    """SQLite-backed corpus store for local replay, CI, and offline analysis."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def upsert_row(self, row: dict[str, Any]) -> None:
        row_id = str(row["row_id"])
        source = dict(row.get("source") or {})
        labels = dict(row.get("labels") or {})
        fact = dict(row.get("training_fact") or {})
        audit = dict(row.get("audit") or {})
        created_at = str(row.get("created_at") or _timestamp())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO corpus_rows (
                  row_id, schema_version, source_kind, collector, session_id, cycle_dir, profile, cycle,
                  run_id, domain, environment, service, target_class, outcome, decision_type,
                  evaluation_recommendation, execution_status, feedback_outcome, confidence,
                  risk_level, promotion_candidate, created_at, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(row_id) DO UPDATE SET
                  schema_version=excluded.schema_version,
                  source_kind=excluded.source_kind,
                  collector=excluded.collector,
                  session_id=excluded.session_id,
                  cycle_dir=excluded.cycle_dir,
                  profile=excluded.profile,
                  cycle=excluded.cycle,
                  run_id=excluded.run_id,
                  domain=excluded.domain,
                  environment=excluded.environment,
                  service=excluded.service,
                  target_class=excluded.target_class,
                  outcome=excluded.outcome,
                  decision_type=excluded.decision_type,
                  evaluation_recommendation=excluded.evaluation_recommendation,
                  execution_status=excluded.execution_status,
                  feedback_outcome=excluded.feedback_outcome,
                  confidence=excluded.confidence,
                  risk_level=excluded.risk_level,
                  promotion_candidate=excluded.promotion_candidate,
                  created_at=excluded.created_at,
                  payload_json=excluded.payload_json
                """,
                (
                    row_id,
                    row.get("schema_version"),
                    source.get("kind"),
                    source.get("collector"),
                    source.get("session_id"),
                    source.get("cycle_dir"),
                    source.get("profile") or labels.get("fault_profile"),
                    source.get("cycle"),
                    source.get("run_id"),
                    row.get("domain"),
                    row.get("environment"),
                    row.get("service"),
                    row.get("target_class"),
                    fact.get("outcome"),
                    fact.get("decision_type"),
                    fact.get("evaluation_recommendation"),
                    fact.get("execution_status"),
                    fact.get("feedback_outcome"),
                    fact.get("confidence"),
                    fact.get("risk_level"),
                    1 if fact.get("promotion_candidate") else 0,
                    created_at,
                    json.dumps(row, sort_keys=True),
                ),
            )
            conn.execute("DELETE FROM corpus_labels WHERE row_id = ?", (row_id,))
            for key, value in _label_pairs(labels):
                conn.execute(
                    "INSERT INTO corpus_labels (row_id, label_key, label_value) VALUES (?, ?, ?)",
                    (row_id, key, value),
                )
            conn.execute("DELETE FROM corpus_artifacts WHERE row_id = ?", (row_id,))
            for artifact_name in audit.get("artifact_files", ()) or ():
                conn.execute(
                    "INSERT INTO corpus_artifacts (row_id, artifact_name) VALUES (?, ?)",
                    (row_id, str(artifact_name)),
                )
            self._upsert_fts(conn, row)

    def import_jsonl(self, path: str | Path) -> int:
        """Import a JSONL corpus file row by row.

        Malformed lines are logged and skipped rather than aborting the import —
        a single bad line in a 100k-row export shouldn't lose the other 99,999
        good rows. Return value is the count of rows successfully imported.
        """

        imported = 0
        skipped_parse = 0
        skipped_upsert = 0
        jsonl_path = Path(path)
        if not jsonl_path.is_file():
            return 0
        for line_no, raw in enumerate(
            jsonl_path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                skipped_parse += 1
                _LOG.warning(
                    "corpus_store: skipping malformed JSON at %s:%d: %s",
                    jsonl_path, line_no, exc,
                )
                continue
            try:
                self.upsert_row(row)
            except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
                skipped_upsert += 1
                _LOG.warning(
                    "corpus_store: skipping unupsertable row at %s:%d: %s",
                    jsonl_path, line_no, exc,
                )
                continue
            imported += 1
        if skipped_parse or skipped_upsert:
            _LOG.info(
                "corpus_store: %s import complete — %d imported, %d parse-skipped, %d upsert-skipped",
                jsonl_path, imported, skipped_parse, skipped_upsert,
            )
        return imported

    def import_jsonl_files(self, paths: Sequence[str | Path]) -> int:
        """Import multiple corpus JSONL files with row-level upsert dedupe."""

        return sum(self.import_jsonl(path) for path in paths)

    def import_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self.upsert_row(row)
        return len(rows)

    def get_row(self, row_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            record = conn.execute("SELECT payload_json FROM corpus_rows WHERE row_id = ?", (row_id,)).fetchone()
        return json.loads(record["payload_json"]) if record else None

    def query(self, query: CorpusQuery) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if query.service:
            where.append("r.service = ?")
            params.append(query.service)
        if query.target_class:
            where.append("r.target_class = ?")
            params.append(query.target_class)
        if query.outcome:
            where.append("r.outcome = ?")
            params.append(query.outcome)
        if query.profile:
            where.append("r.profile = ?")
            params.append(query.profile)
        if query.promotion_candidate is not None:
            where.append("r.promotion_candidate = ?")
            params.append(1 if query.promotion_candidate else 0)
        join = ""
        order = "r.created_at DESC"
        if query.text:
            join = "JOIN corpus_rows_fts fts ON fts.row_id = r.row_id"
            where.append("corpus_rows_fts MATCH ?")
            params.append(_fts_query(query.text))
            order = "rank"
        params.append(max(1, min(int(query.limit), 500)))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT r.payload_json
                FROM corpus_rows r
                {join}
                {where_sql}
                ORDER BY {order}
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def outcome_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT outcome, COUNT(*) AS count FROM corpus_rows GROUP BY outcome").fetchall()
        return {str(row["outcome"]): int(row["count"]) for row in rows}

    def service_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT service, COUNT(*) AS count FROM corpus_rows GROUP BY service").fetchall()
        return {str(row["service"]): int(row["count"]) for row in rows}

    def environment_counts(self) -> dict[str, int]:
        return self._group_counts("environment")

    def source_kind_counts(self) -> dict[str, int]:
        return self._group_counts("source_kind")

    def target_class_counts(self) -> dict[str, int]:
        return self._group_counts("target_class")

    def collector_counts(self) -> dict[str, int]:
        return self._group_counts("collector")

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM corpus_rows").fetchone()["count"]
            promotion = conn.execute(
                "SELECT COUNT(*) AS count FROM corpus_rows WHERE promotion_candidate = 1"
            ).fetchone()["count"]
            artifacts = conn.execute("SELECT COUNT(*) AS count FROM corpus_artifacts").fetchone()["count"]
            labels = conn.execute("SELECT COUNT(*) AS count FROM corpus_labels").fetchone()["count"]
        return {
            "database_path": str(self.path),
            "row_count": int(total),
            "promotion_candidate_count": int(promotion),
            "label_count": int(labels),
            "artifact_ref_count": int(artifacts),
            "outcomes": self.outcome_counts(),
            "services": self.service_counts(),
            "environments": self.environment_counts(),
            "source_kinds": self.source_kind_counts(),
            "target_classes": self.target_class_counts(),
            "collectors": self.collector_counts(),
            "coverage": self.coverage_counts(),
            "promotion_patterns": self.promotion_pattern_counts(),
            "breakthrough": self.breakthrough_report(),
        }

    def coverage_counts(self, *, limit: int = 10000) -> dict[str, int]:
        rows = self._payload_rows(limit=limit)
        counts = coverage_counts(rows)
        extra: dict[str, int] = {}
        for row in rows:
            for label in normalize_coverage_labels(row):
                if label not in counts:
                    extra[label] = extra.get(label, 0) + 1
        return {**counts, **dict(sorted(extra.items()))}

    def promotion_pattern_counts(self, *, limit: int = 10000) -> dict[str, int]:
        rows = [row for row in self._payload_rows(limit=limit) if dict(row.get("training_fact") or {}).get("promotion_candidate")]
        return promotion_pattern_counts(rows)

    def breakthrough_report(self, *, limit: int = 5000) -> dict[str, Any]:
        """Return Breakthrough-threshold evidence from stored corpus rows."""

        return breakthrough_threshold_report(self._payload_rows(limit=limit))

    def _payload_rows(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM corpus_rows
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 10000)),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def _group_counts(self, column: str) -> dict[str, int]:
        allowed = {"environment", "source_kind", "target_class", "collector"}
        if column not in allowed:
            raise ValueError(f"unsupported corpus count column: {column}")
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {column} AS value, COUNT(*) AS count FROM corpus_rows GROUP BY {column}"
            ).fetchall()
        return {str(row["value"]): int(row["count"]) for row in rows}

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;

                CREATE TABLE IF NOT EXISTS corpus_rows (
                  row_id TEXT PRIMARY KEY,
                  schema_version TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  collector TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  cycle_dir TEXT NOT NULL,
                  profile TEXT NULL,
                  cycle INTEGER NULL,
                  run_id TEXT NULL,
                  domain TEXT NOT NULL,
                  environment TEXT NOT NULL,
                  service TEXT NULL,
                  target_class TEXT NULL,
                  outcome TEXT NOT NULL,
                  decision_type TEXT NULL,
                  evaluation_recommendation TEXT NULL,
                  execution_status TEXT NULL,
                  feedback_outcome TEXT NULL,
                  confidence REAL NULL,
                  risk_level TEXT NULL,
                  promotion_candidate INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_corpus_rows_service_outcome
                  ON corpus_rows(service, outcome, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_corpus_rows_target_profile
                  ON corpus_rows(target_class, profile, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_corpus_rows_promotion
                  ON corpus_rows(promotion_candidate, target_class, profile);
                CREATE INDEX IF NOT EXISTS idx_corpus_rows_run_id
                  ON corpus_rows(run_id);

                CREATE TABLE IF NOT EXISTS corpus_labels (
                  row_id TEXT NOT NULL REFERENCES corpus_rows(row_id) ON DELETE CASCADE,
                  label_key TEXT NOT NULL,
                  label_value TEXT NOT NULL,
                  PRIMARY KEY (row_id, label_key, label_value)
                );
                CREATE INDEX IF NOT EXISTS idx_corpus_labels_lookup
                  ON corpus_labels(label_key, label_value);

                CREATE TABLE IF NOT EXISTS corpus_artifacts (
                  row_id TEXT NOT NULL REFERENCES corpus_rows(row_id) ON DELETE CASCADE,
                  artifact_name TEXT NOT NULL,
                  PRIMARY KEY (row_id, artifact_name)
                );

                CREATE TABLE IF NOT EXISTS memory_projection_records (
                  row_id TEXT NOT NULL REFERENCES corpus_rows(row_id) ON DELETE CASCADE,
                  observation_id TEXT NOT NULL,
                  claim_id TEXT NULL,
                  projected_at TEXT NOT NULL,
                  PRIMARY KEY (row_id, observation_id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS corpus_rows_fts USING fts5(
                  row_id UNINDEXED,
                  service,
                  profile,
                  outcome,
                  target_class,
                  content
                );
                """
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _upsert_fts(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        row_id = str(row["row_id"])
        labels = dict(row.get("labels") or {})
        fact = dict(row.get("training_fact") or {})
        content = " ".join(
            str(value)
            for value in (
                row.get("row_id"),
                row.get("service"),
                row.get("target_class"),
                labels.get("fault_profile"),
                " ".join(f"{key} {item}" for key, item in _label_pairs(labels)),
                " ".join(str(item) for item in labels.get("error_signatures", ()) or ()),
                fact.get("outcome"),
                fact.get("decision_type"),
                fact.get("evaluation_recommendation"),
                fact.get("risk_level"),
            )
            if value
        )
        conn.execute("DELETE FROM corpus_rows_fts WHERE row_id = ?", (row_id,))
        conn.execute(
            """
            INSERT INTO corpus_rows_fts (row_id, service, profile, outcome, target_class, content)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                row.get("service") or "",
                labels.get("fault_profile") or "",
                fact.get("outcome") or "",
                row.get("target_class") or "",
                content,
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn


def project_corpus_row_to_memory(row: dict[str, Any], state_store: Any) -> dict[str, Any]:
    """Project a normalized corpus row into canonical observation/claim memory."""

    fact = dict(row.get("training_fact") or {})
    labels = dict(row.get("labels") or {})
    source = dict(row.get("source") or {})
    source_kind = str(source.get("kind") or "")
    service = str(row.get("service") or "unknown")
    row_id = str(row["row_id"])
    profile = str(labels.get("fault_profile") or source.get("profile") or "unknown")
    outcome = str(fact.get("outcome") or "unknown")
    decision_type = str(fact.get("decision_type") or "unknown")
    confidence = _bounded_confidence(fact.get("confidence"), default=0.65)
    now = _timestamp()
    observation_id = _stable_id("obs_corpus", row_id)
    observation = {
        "observation_id": observation_id,
        "scope": {
            "shared": True,
            "service": service,
            "domain": row.get("domain"),
            "target_class": row.get("target_class"),
            "memory_tier": "episodic",
        },
        "kind": "incident_corpus_row",
        "content": _observation_content(
            row,
            service=service,
            profile=profile,
            outcome=outcome,
            decision_type=decision_type,
        ),
        "service": service,
        "run_id": source.get("run_id"),
        "source_type": "incident_corpus",
        "source_refs": [{"row_id": row_id, "session_id": source.get("session_id"), "cycle_dir": source.get("cycle_dir")}],
        "created_at": now,
        "author": "mesh",
        "tags": ["incident_corpus", source_kind or "unknown_source", str(row.get("target_class") or "unknown"), outcome],
        "metadata": {
            "row_id": row_id,
            "profile": profile,
            "outcome": outcome,
            "source_kind": source_kind,
            "promotion_candidate": bool(fact.get("promotion_candidate")),
            "error_signatures": list(labels.get("error_signatures", ()) or ()),
            "raw_artifact_paths": list(source.get("raw_artifact_paths", ()) or ()),
            "clean_artifact_paths": list(source.get("clean_artifact_paths", ()) or ()),
        },
    }
    saved_observation = _save_observation_once(state_store, observation)
    claim: dict[str, Any] | None = None
    if _should_project_claim(row, outcome=outcome):
        tier = "procedural" if fact.get("promotion_candidate") else "semantic"
        statement = _claim_statement(row, profile=profile, outcome=outcome, decision_type=decision_type)
        claim = {
            "claim_id": _stable_id("claim_corpus", f"{row_id}:{service}:{profile}:{outcome}:{decision_type}"),
            "statement": statement,
            "entity_refs": _claim_entity_refs(row, service, profile, outcome, decision_type),
            "supporting_observation_ids": [observation_id],
            "contradicting_claim_ids": [],
            "superseded_by": None,
            "confidence": confidence,
            "confidence_factors": {
                "support_score": 0.7,
                "recency_score": 0.8,
                "authority_score": 0.8,
                "consistency_score": 0.7,
                "verification_score": _verification_score(row, outcome),
            },
            "freshness": 0.8,
            "tier": tier,
            "state": "active",
            "created_at": now,
            "updated_at": now,
        }
        claim = state_store.save_claim(claim)
        state_store.save_relationship(
            {
                "relationship_id": _stable_id("rel_corpus", f"{observation_id}:{claim['claim_id']}"),
                "from_id": observation_id,
                "to_id": claim["claim_id"],
                "type": "supports",
                "confidence": confidence,
                "supporting_observation_ids": [observation_id],
                "state": "active",
            }
        )
    return {
        "row_id": row_id,
        "observation_id": saved_observation["observation_id"],
        "claim_id": claim.get("claim_id") if claim else None,
    }


def project_database_to_memory(
    database: IncidentCorpusDatabase,
    state_store: Any,
    *,
    query: CorpusQuery | None = None,
) -> list[dict[str, Any]]:
    """Project corpus query results into the canonical memory substrate."""

    rows = database.query(query or CorpusQuery(limit=500))
    return [project_corpus_row_to_memory(row, state_store) for row in rows]


def _save_observation_once(state_store: Any, observation: dict[str, Any]) -> dict[str, Any]:
    observation_id = str(observation["observation_id"])
    service = observation.get("service")
    if hasattr(state_store, "list_observations"):
        try:
            existing = state_store.list_observations(
                {"service": service},
                {"kind": observation.get("kind"), "limit": 10000},
            )
            for record in existing:
                if record.get("observation_id") == observation_id:
                    return record
        except Exception:
            pass
    return state_store.append_observation(observation)


def _claim_statement(row: dict[str, Any], *, profile: str, outcome: str, decision_type: str) -> str:
    service = str(row.get("service") or "unknown")
    target = str(row.get("target_class") or "unknown")
    source = dict(row.get("source") or {})
    source_kind = str(source.get("kind") or "")
    labels = dict(row.get("labels") or {})
    source_name = str(labels.get("source_name") or service)
    if source_kind in {"public_dataset", "public_tooling"}:
        planes = ", ".join(str(item) for item in labels.get("telemetry_planes", ()) or ())
        uses = ", ".join(str(item) for item in labels.get("mesh_use", ()) or ())
        raw_count = len(source.get("raw_artifact_paths", ()) or ())
        clean_count = len(source.get("clean_artifact_paths", ()) or ())
        return (
            f"{source_name} is public {source_kind} bootstrap material for {target}; "
            f"telemetry_planes={planes or 'unknown'}; mesh_use={uses or 'evaluation'}; "
            f"raw_artifacts={raw_count}; clean_indexes={clean_count}. "
            "Use it for parser, retrieval, and benchmark grounding only; require internal corpus corroboration before policy or action promotion."
        )
    if outcome == "successful":
        return f"For {target} {service}, {profile} has recovered after {decision_type} in verified corpus evidence."
    if outcome == "human_hold":
        return f"For {target} {service}, {profile} requires human review in corpus evidence."
    return f"For {target} {service}, {profile} maps to {outcome} in corpus evidence."


def _should_project_claim(row: dict[str, Any], *, outcome: str) -> bool:
    source = dict(row.get("source") or {})
    fact = dict(row.get("training_fact") or {})
    if source.get("kind") in {"public_dataset", "public_tooling"}:
        return True
    return outcome in {"human_hold", "successful"} or fact.get("promotion_candidate") is True


def _claim_entity_refs(
    row: dict[str, Any],
    service: str,
    profile: str,
    outcome: str,
    decision_type: str,
) -> list[str]:
    labels = dict(row.get("labels") or {})
    refs = [
        service,
        str(row.get("target_class") or "unknown"),
        profile,
        outcome,
        decision_type,
        "incident_corpus",
    ]
    for key in ("source_name", "source_kind"):
        value = labels.get(key)
        if value:
            refs.append(str(value))
    for key in ("telemetry_planes", "mesh_use", "public_labels", "coverage"):
        value = labels.get(key)
        if isinstance(value, list | tuple | set):
            refs.extend(str(item) for item in value if item)
    return list(dict.fromkeys(refs))


def _verification_score(row: dict[str, Any], outcome: str) -> float:
    source = dict(row.get("source") or {})
    if source.get("kind") in {"public_dataset", "public_tooling"}:
        return 0.55
    return 0.9 if outcome == "successful" else 0.65


def _observation_content(
    row: dict[str, Any],
    *,
    service: str,
    profile: str,
    outcome: str,
    decision_type: str,
) -> str:
    source = dict(row.get("source") or {})
    labels = dict(row.get("labels") or {})
    if source.get("kind") in {"public_dataset", "public_tooling"}:
        source_name = str(labels.get("source_name") or service)
        return (
            f"{source_name} public bootstrap source; kind={source.get('kind')}; "
            f"service={service}; target={row.get('target_class')}; "
            f"planes={','.join(str(item) for item in labels.get('telemetry_planes', ()) or ())}; "
            f"raw_artifacts={len(source.get('raw_artifact_paths', ()) or ())}; "
            f"clean_artifacts={len(source.get('clean_artifact_paths', ()) or ())}; "
            "promotion_requires_internal_corroboration."
        )
    fact = dict(row.get("training_fact") or {})
    return (
        f"{service} {profile} ended as {outcome}; decision={decision_type}; "
        f"evaluation={fact.get('evaluation_recommendation')}; execution={fact.get('execution_status')}; "
        f"feedback={fact.get('feedback_outcome')}; "
        f"signatures={','.join(str(item) for item in labels.get('error_signatures', ()) or ())}."
    )


def _label_pairs(labels: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in labels.items():
        if isinstance(value, list | tuple | set):
            for item in value:
                pairs.append((str(key), str(item)))
        elif value is not None:
            pairs.append((str(key), str(value)))
    return pairs


def _fts_query(text: str) -> str:
    tokens = [token.replace('"', "") for token in str(text).split() if token.strip()]
    return " OR ".join(f'"{token}"' for token in tokens) if tokens else '""'


def _bounded_confidence(value: Any, *, default: float) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(float(value), 1.0))
    return default


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{uuid5(NAMESPACE_URL, value).hex[:16]}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
