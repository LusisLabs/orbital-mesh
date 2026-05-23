#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.backup_restore import BACKUP_RESTORE_COMPONENTS, BACKUP_RESTORE_REHEARSAL_VERSION


DEFAULT_OUTPUT = ".mesh-runtime-state/backup-restore-rehearsal.json"
DEFAULT_ARTIFACT_DIR = ".mesh-runtime-state/backup-restore-rehearsal"
EXPECTED_BACKUP_RESTORE_REHEARSAL_SCHEMA = "mesh.backup_restore_rehearsal.v1"
assert EXPECTED_BACKUP_RESTORE_REHEARSAL_SCHEMA == BACKUP_RESTORE_REHEARSAL_VERSION


@dataclass(frozen=True)
class ComponentSnapshot:
    component: str
    backup_uri: str
    restored: bool
    sha256_before: str
    sha256_after: str
    record_count: int


@dataclass(frozen=True)
class BackupRestoreMeasurements:
    rehearsal_id: str
    generated_at: str
    environment: str
    operator_id: str
    backup_ref: str
    restore_ref: str
    rpo_seconds: int
    rto_seconds: int
    measured_restore_seconds: float
    components: list[ComponentSnapshot]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Postgres-backed Mesh backup/restore rehearsal.")
    parser.add_argument("--database-url", default=os.getenv("MESH_DATABASE_URL") or "")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--artifact-dir", default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--environment", default=os.getenv("MESH_ENVIRONMENT") or "pilot")
    parser.add_argument("--operator-id", default=os.getenv("MESH_OPERATOR_ID") or "platform@example.com")
    parser.add_argument("--rehearsal-id", default="")
    parser.add_argument("--rpo-seconds", type=int, default=2)
    parser.add_argument("--rto-seconds", type=int, default=900)
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
            artifact_dir=Path(args.artifact_dir),
            environment=args.environment,
            operator_id=args.operator_id,
            rehearsal_id=args.rehearsal_id,
            rpo_seconds=args.rpo_seconds,
            rto_seconds=args.rto_seconds,
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
    artifact_dir: Path,
    environment: str,
    operator_id: str,
    rehearsal_id: str = "",
    rpo_seconds: int = 2,
    rto_seconds: int = 900,
    connect: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if rpo_seconds < 0:
        raise ValueError("rpo_seconds must be non-negative")
    if rto_seconds <= 0:
        raise ValueError("rto_seconds must be positive")

    resolved_id = rehearsal_id or f"backup_restore_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    connect_fn = connect or _psycopg_connect()
    generated_at = _timestamp()
    started = time.perf_counter()
    run_dir = artifact_dir / resolved_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _initialize_schema(connect_fn, database_url)
    _seed_components(connect_fn, database_url, resolved_id)
    before = _read_components(connect_fn, database_url, resolved_id)
    backup_paths = _write_backup_files(run_dir, before)
    _delete_components(connect_fn, database_url, resolved_id)
    _restore_components(connect_fn, database_url, resolved_id, backup_paths)
    after = _read_components(connect_fn, database_url, resolved_id)
    measured_restore_seconds = time.perf_counter() - started
    components = _component_snapshots(before=before, after=after, backup_paths=backup_paths)

    proof = build_proof(
        BackupRestoreMeasurements(
            rehearsal_id=resolved_id,
            generated_at=generated_at,
            environment=environment,
            operator_id=operator_id,
            backup_ref=f"file://{run_dir.resolve()}",
            restore_ref=f"postgres://backup-restore/{resolved_id}/restore",
            rpo_seconds=rpo_seconds,
            rto_seconds=rto_seconds,
            measured_restore_seconds=measured_restore_seconds,
            components=components,
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof


def build_proof(measurements: BackupRestoreMeasurements) -> dict[str, Any]:
    return {
        "schema_version": EXPECTED_BACKUP_RESTORE_REHEARSAL_SCHEMA,
        "rehearsal_id": measurements.rehearsal_id,
        "generated_at": measurements.generated_at,
        "environment": measurements.environment,
        "operator_id": measurements.operator_id,
        "state_backend": "postgres",
        "backup_ref": measurements.backup_ref,
        "restore_ref": measurements.restore_ref,
        "rpo_seconds": measurements.rpo_seconds,
        "rto_seconds": measurements.rto_seconds,
        "measured_restore_seconds": round(measurements.measured_restore_seconds, 3),
        "components": [
            {
                "component": item.component,
                "backup_uri": item.backup_uri,
                "restored": item.restored,
                "sha256_before": item.sha256_before,
                "sha256_after": item.sha256_after,
                "record_count": item.record_count,
            }
            for item in measurements.components
        ],
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
            CREATE TABLE IF NOT EXISTS mesh_backup_restore_rehearsal_components (
              rehearsal_id text NOT NULL,
              component text NOT NULL,
              payload jsonb NOT NULL,
              updated_at timestamptz NOT NULL DEFAULT now(),
              PRIMARY KEY (rehearsal_id, component)
            )
            """
        )


def _seed_components(connect: Callable[..., Any], database_url: str, rehearsal_id: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM mesh_backup_restore_rehearsal_components WHERE rehearsal_id = %s",
            (rehearsal_id,),
        )
        for component in sorted(BACKUP_RESTORE_COMPONENTS):
            payload = {
                "component": component,
                "rehearsal_id": rehearsal_id,
                "records": [
                    {
                        "id": f"{component}-record-1",
                        "kind": "backup_restore_rehearsal",
                        "value": f"{component}:{rehearsal_id}",
                    }
                ],
            }
            conn.execute(
                """
                INSERT INTO mesh_backup_restore_rehearsal_components (rehearsal_id, component, payload)
                VALUES (%s, %s, %s::jsonb)
                """,
                (rehearsal_id, component, json.dumps(payload, sort_keys=True)),
            )


def _read_components(connect: Callable[..., Any], database_url: str, rehearsal_id: str) -> dict[str, dict[str, Any]]:
    with connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT component, payload::text
            FROM mesh_backup_restore_rehearsal_components
            WHERE rehearsal_id = %s
            ORDER BY component
            """,
            (rehearsal_id,),
        ).fetchall()
    return {component: json.loads(payload) for component, payload in rows}


def _write_backup_files(run_dir: Path, components: dict[str, dict[str, Any]]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for component, payload in components.items():
        path = run_dir / f"{component}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths[component] = path
    return paths


def _delete_components(connect: Callable[..., Any], database_url: str, rehearsal_id: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM mesh_backup_restore_rehearsal_components WHERE rehearsal_id = %s",
            (rehearsal_id,),
        )


def _restore_components(
    connect: Callable[..., Any],
    database_url: str,
    rehearsal_id: str,
    backup_paths: dict[str, Path],
) -> None:
    with connect(database_url, autocommit=True) as conn:
        for component, path in sorted(backup_paths.items()):
            payload = json.loads(path.read_text(encoding="utf-8"))
            conn.execute(
                """
                INSERT INTO mesh_backup_restore_rehearsal_components (rehearsal_id, component, payload)
                VALUES (%s, %s, %s::jsonb)
                """,
                (rehearsal_id, component, json.dumps(payload, sort_keys=True)),
            )


def _component_snapshots(
    *,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    backup_paths: dict[str, Path],
) -> list[ComponentSnapshot]:
    snapshots: list[ComponentSnapshot] = []
    for component in sorted(BACKUP_RESTORE_COMPONENTS):
        before_payload = before.get(component)
        after_payload = after.get(component)
        before_hash = _payload_hash(before_payload)
        after_hash = _payload_hash(after_payload)
        records = before_payload.get("records", []) if isinstance(before_payload, dict) else []
        snapshots.append(
            ComponentSnapshot(
                component=component,
                backup_uri=f"file://{backup_paths[component].resolve()}",
                restored=before_payload == after_payload,
                sha256_before=before_hash,
                sha256_after=after_hash,
                record_count=len(records) if isinstance(records, list) else 0,
            )
        )
    return snapshots


def _payload_hash(payload: dict[str, Any] | None) -> str:
    encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
