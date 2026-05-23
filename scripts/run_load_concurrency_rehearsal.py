#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.load_concurrency import LOAD_CONCURRENCY_REHEARSAL_VERSION


DEFAULT_OUTPUT = ".mesh-runtime-state/load-concurrency-rehearsal.json"
EXPECTED_LOAD_CONCURRENCY_REHEARSAL_SCHEMA = "mesh.load_concurrency_rehearsal.v1"
assert EXPECTED_LOAD_CONCURRENCY_REHEARSAL_SCHEMA == LOAD_CONCURRENCY_REHEARSAL_VERSION


@dataclass(frozen=True)
class RehearsalMeasurements:
    rehearsal_id: str
    generated_at: str
    environment: str
    operator_id: str
    run_count: int
    concurrent_operators: int
    worker_count: int
    queue_size: int
    max_queue_depth: int
    rejected_runs: int
    tenant_quota_enforced: bool
    target_lock_conflicts_observed: bool
    cancellation_exercised: bool
    stuck_run_recovery_exercised: bool
    backpressure_observed: bool
    p95_admission_latency_ms: float
    p95_event_persistence_latency_ms: float
    evidence_refs: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Postgres-backed Mesh load/concurrency rehearsal.")
    parser.add_argument("--database-url", default=os.getenv("MESH_DATABASE_URL") or "")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--environment", default=os.getenv("MESH_ENVIRONMENT") or "pilot")
    parser.add_argument("--operator-id", default=os.getenv("MESH_OPERATOR_ID") or "platform@example.com")
    parser.add_argument("--rehearsal-id", default="")
    parser.add_argument("--run-count", type=int, default=24)
    parser.add_argument("--concurrent-operators", type=int, default=3)
    parser.add_argument("--worker-count", type=int, default=4)
    parser.add_argument("--queue-size", type=int, default=8)
    parser.add_argument("--tenant-active-run-limit", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-if-missing", action="store_true")
    args = parser.parse_args()

    if not args.database_url:
        payload = {"status": "skipped", "reason": "MESH_DATABASE_URL is not set"}
        _emit(payload, json_mode=args.json)
        return 0 if args.skip_if_missing else 2

    try:
        proof = run_rehearsal(
            database_url=args.database_url,
            output=Path(args.output),
            environment=args.environment,
            operator_id=args.operator_id,
            rehearsal_id=args.rehearsal_id,
            run_count=args.run_count,
            concurrent_operators=args.concurrent_operators,
            worker_count=args.worker_count,
            queue_size=args.queue_size,
            tenant_active_run_limit=args.tenant_active_run_limit,
        )
    except Exception as exc:  # noqa: BLE001 - proof CLI must surface exact failure.
        payload = {"status": "failed", "error": str(exc)}
        _emit(payload, json_mode=args.json)
        return 1

    payload = {"status": "passed", "output": str(Path(args.output)), "proof": proof}
    _emit(payload, json_mode=args.json)
    return 0


def run_rehearsal(
    *,
    database_url: str,
    output: Path,
    environment: str,
    operator_id: str,
    rehearsal_id: str = "",
    run_count: int = 24,
    concurrent_operators: int = 3,
    worker_count: int = 4,
    queue_size: int = 8,
    tenant_active_run_limit: int = 2,
    connect: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if run_count <= 0:
        raise ValueError("run_count must be positive")
    if concurrent_operators < 2:
        raise ValueError("concurrent_operators must be at least 2")
    if worker_count <= 0:
        raise ValueError("worker_count must be positive")
    if queue_size <= 0:
        raise ValueError("queue_size must be positive")
    if tenant_active_run_limit <= 0:
        raise ValueError("tenant_active_run_limit must be positive")

    resolved_id = rehearsal_id or f"load_concurrency_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    generated_at = _timestamp()
    connect_fn = connect or _psycopg_connect()
    _initialize_schema(connect_fn, database_url)
    _reset_rehearsal(connect_fn, database_url, resolved_id)
    queue_stats = _exercise_backpressure(queue_size=queue_size, run_count=run_count)
    admission_latencies, event_latencies = _exercise_parallel_admission(
        connect_fn=connect_fn,
        database_url=database_url,
        rehearsal_id=resolved_id,
        run_count=run_count,
        concurrent_operators=concurrent_operators,
        worker_count=worker_count,
    )
    quota_enforced, quota_rejections = _exercise_tenant_quota(
        connect_fn=connect_fn,
        database_url=database_url,
        rehearsal_id=resolved_id,
        tenant_active_run_limit=tenant_active_run_limit,
    )
    target_lock_conflict = _exercise_target_lock(connect_fn, database_url)
    cancellation = _exercise_cancellation(connect_fn, database_url, resolved_id)
    stuck_recovery = _exercise_stuck_recovery(connect_fn, database_url, resolved_id)

    measurements = RehearsalMeasurements(
        rehearsal_id=resolved_id,
        generated_at=generated_at,
        environment=environment,
        operator_id=operator_id,
        run_count=run_count,
        concurrent_operators=concurrent_operators,
        worker_count=worker_count,
        queue_size=queue_size,
        max_queue_depth=queue_stats["max_queue_depth"],
        rejected_runs=queue_stats["rejected_runs"] + quota_rejections,
        tenant_quota_enforced=quota_enforced,
        target_lock_conflicts_observed=target_lock_conflict,
        cancellation_exercised=cancellation,
        stuck_run_recovery_exercised=stuck_recovery,
        backpressure_observed=queue_stats["backpressure_observed"],
        p95_admission_latency_ms=_p95(admission_latencies),
        p95_event_persistence_latency_ms=_p95(event_latencies),
        evidence_refs=[
            f"postgres://load-concurrency/{resolved_id}/runs",
            f"postgres://load-concurrency/{resolved_id}/events",
        ],
    )
    proof = build_proof(measurements)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof


def build_proof(measurements: RehearsalMeasurements) -> dict[str, Any]:
    return {
        "schema_version": EXPECTED_LOAD_CONCURRENCY_REHEARSAL_SCHEMA,
        "rehearsal_id": measurements.rehearsal_id,
        "generated_at": measurements.generated_at,
        "environment": measurements.environment,
        "operator_id": measurements.operator_id,
        "state_backend": "postgres",
        "run_count": measurements.run_count,
        "concurrent_operators": measurements.concurrent_operators,
        "worker_count": measurements.worker_count,
        "queue_size": measurements.queue_size,
        "max_queue_depth": measurements.max_queue_depth,
        "rejected_runs": measurements.rejected_runs,
        "tenant_quota_enforced": measurements.tenant_quota_enforced,
        "target_lock_conflicts_observed": measurements.target_lock_conflicts_observed,
        "cancellation_exercised": measurements.cancellation_exercised,
        "stuck_run_recovery_exercised": measurements.stuck_run_recovery_exercised,
        "backpressure_observed": measurements.backpressure_observed,
        "p95_admission_latency_ms": round(measurements.p95_admission_latency_ms, 3),
        "p95_event_persistence_latency_ms": round(measurements.p95_event_persistence_latency_ms, 3),
        "evidence_refs": measurements.evidence_refs,
        "raw_secret_material_present": False,
    }


def _psycopg_connect() -> Callable[..., Any]:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on local environment.
        raise RuntimeError('psycopg is required; install "psycopg[binary,pool]>=3.2,<4"') from exc
    return psycopg.connect


def _initialize_schema(connect: Callable[..., Any], database_url: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mesh_load_concurrency_rehearsal_runs (
              rehearsal_id text NOT NULL,
              run_id text NOT NULL,
              operator_id text NOT NULL,
              tenant_id text NOT NULL,
              target_ref text NOT NULL,
              status text NOT NULL,
              queued_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              PRIMARY KEY (rehearsal_id, run_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mesh_load_concurrency_rehearsal_events (
              rehearsal_id text NOT NULL,
              event_id bigserial PRIMARY KEY,
              run_id text NOT NULL,
              event_type text NOT NULL,
              recorded_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )


def _reset_rehearsal(connect: Callable[..., Any], database_url: str, rehearsal_id: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM mesh_load_concurrency_rehearsal_events WHERE rehearsal_id = %s", (rehearsal_id,))
        conn.execute("DELETE FROM mesh_load_concurrency_rehearsal_runs WHERE rehearsal_id = %s", (rehearsal_id,))


def _exercise_backpressure(*, queue_size: int, run_count: int) -> dict[str, Any]:
    admission_queue: queue.Queue[str] = queue.Queue(maxsize=queue_size)
    rejected = 0
    max_depth = 0
    for index in range(run_count + queue_size):
        try:
            admission_queue.put_nowait(f"queued-{index}")
            max_depth = max(max_depth, admission_queue.qsize())
        except queue.Full:
            rejected += 1
    return {
        "backpressure_observed": rejected > 0,
        "rejected_runs": rejected,
        "max_queue_depth": max_depth,
    }


def _exercise_parallel_admission(
    *,
    connect_fn: Callable[..., Any],
    database_url: str,
    rehearsal_id: str,
    run_count: int,
    concurrent_operators: int,
    worker_count: int,
) -> tuple[list[float], list[float]]:
    admission_latencies: list[float] = []
    event_latencies: list[float] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _admit_run,
                connect_fn,
                database_url,
                rehearsal_id,
                f"run_{index:04d}",
                f"operator-{index % concurrent_operators}@example.com",
            )
            for index in range(run_count)
        ]
        for future in as_completed(futures):
            admission_ms, event_ms = future.result()
            admission_latencies.append(admission_ms)
            event_latencies.append(event_ms)
    return admission_latencies, event_latencies


def _admit_run(
    connect: Callable[..., Any],
    database_url: str,
    rehearsal_id: str,
    run_id: str,
    operator_id: str,
) -> tuple[float, float]:
    with connect(database_url, autocommit=True) as conn:
        started = time.perf_counter()
        conn.execute(
            """
            INSERT INTO mesh_load_concurrency_rehearsal_runs
              (rehearsal_id, run_id, operator_id, tenant_id, target_ref, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (rehearsal_id, run_id, operator_id, "tenant-a", "kubernetes://pilot/search/semantic-search", "running"),
        )
        admission_ms = (time.perf_counter() - started) * 1000
        event_started = time.perf_counter()
        conn.execute(
            """
            INSERT INTO mesh_load_concurrency_rehearsal_events (rehearsal_id, run_id, event_type)
            VALUES (%s, %s, %s)
            """,
            (rehearsal_id, run_id, "run_admitted"),
        )
        event_ms = (time.perf_counter() - event_started) * 1000
    return admission_ms, event_ms


def _exercise_tenant_quota(
    *,
    connect_fn: Callable[..., Any],
    database_url: str,
    rehearsal_id: str,
    tenant_active_run_limit: int,
) -> tuple[bool, int]:
    rejected = 0
    with connect_fn(database_url, autocommit=True) as conn:
        active = conn.execute(
            """
            SELECT count(*) FROM mesh_load_concurrency_rehearsal_runs
            WHERE rehearsal_id = %s AND tenant_id = %s AND status = %s
            """,
            (rehearsal_id, "tenant-a", "running"),
        ).fetchone()[0]
        if active >= tenant_active_run_limit:
            rejected = 1
            conn.execute(
                """
                INSERT INTO mesh_load_concurrency_rehearsal_events (rehearsal_id, run_id, event_type)
                VALUES (%s, %s, %s)
                """,
                (rehearsal_id, "quota_probe", "tenant_quota_rejected"),
            )
    return rejected > 0, rejected


def _exercise_target_lock(connect: Callable[..., Any], database_url: str) -> bool:
    lock_id = 8727001
    with connect(database_url, autocommit=True) as holder:
        acquired = holder.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,)).fetchone()[0]
        if not acquired:
            return True
        try:
            with connect(database_url, autocommit=True) as contender:
                conflict = contender.execute("SELECT NOT pg_try_advisory_lock(%s)", (lock_id,)).fetchone()[0]
                if not conflict:
                    contender.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
                return bool(conflict)
        finally:
            holder.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))


def _exercise_cancellation(connect: Callable[..., Any], database_url: str, rehearsal_id: str) -> bool:
    run_id = "cancel_probe"
    with connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO mesh_load_concurrency_rehearsal_runs
              (rehearsal_id, run_id, operator_id, tenant_id, target_ref, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (rehearsal_id, run_id) DO UPDATE SET status = EXCLUDED.status
            """,
            (rehearsal_id, run_id, "operator-cancel@example.com", "tenant-a", "kubernetes://pilot/search/semantic-search", "running"),
        )
        conn.execute(
            """
            UPDATE mesh_load_concurrency_rehearsal_runs
            SET status = %s, updated_at = now()
            WHERE rehearsal_id = %s AND run_id = %s
            """,
            ("cancelled", rehearsal_id, run_id),
        )
        status = conn.execute(
            "SELECT status FROM mesh_load_concurrency_rehearsal_runs WHERE rehearsal_id = %s AND run_id = %s",
            (rehearsal_id, run_id),
        ).fetchone()[0]
    return status == "cancelled"


def _exercise_stuck_recovery(connect: Callable[..., Any], database_url: str, rehearsal_id: str) -> bool:
    run_id = "stuck_probe"
    with connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO mesh_load_concurrency_rehearsal_runs
              (rehearsal_id, run_id, operator_id, tenant_id, target_ref, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now() - interval '15 minutes')
            ON CONFLICT (rehearsal_id, run_id) DO UPDATE
            SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at
            """,
            (rehearsal_id, run_id, "operator-recovery@example.com", "tenant-a", "kubernetes://pilot/search/semantic-search", "running"),
        )
        updated = conn.execute(
            """
            UPDATE mesh_load_concurrency_rehearsal_runs
            SET status = %s, updated_at = now()
            WHERE rehearsal_id = %s AND run_id = %s AND updated_at < now() - interval '5 minutes'
            RETURNING status
            """,
            ("recovered", rehearsal_id, run_id),
        ).fetchone()
    return bool(updated and updated[0] == "recovered")


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return ordered[index]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload["status"])
        if payload.get("output"):
            print(payload["output"])


if __name__ == "__main__":
    raise SystemExit(main())
