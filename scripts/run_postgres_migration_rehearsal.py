#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.migration_rehearsal import (  # noqa: E402
    build_migration_rehearsal_packet,
    verify_migration_rehearsal,
)

DESTRUCTIVE_STATEMENT_RE = re.compile(
    r"\b(drop\s+(table|schema|database|index|view|materialized\s+view|sequence|function|procedure|type|domain|extension)"
    r"|truncate\s+table|alter\s+table\s+(if\s+exists\s+)?(only\s+)?\S+\s+drop)\b",
    re.IGNORECASE,
)


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> Any: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def __enter__(self) -> "Cursor": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a real Postgres migration rehearsal and write a mesh.migration_rehearsal.v1 proof."
    )
    parser.add_argument("--database-url", default=os.getenv("MESH_MIGRATION_REHEARSAL_DATABASE_URL") or os.getenv("MESH_DATABASE_URL") or "")
    parser.add_argument("--output", required=True, help="Write the generated mesh.migration_rehearsal.v1 proof JSON.")
    parser.add_argument("--operator-id", default=os.getenv("GITHUB_ACTOR") or os.getenv("USER") or "local-operator")
    parser.add_argument("--environment", default=os.getenv("MESH_ENVIRONMENT") or "ci")
    parser.add_argument("--migration-directory", default="migrations/postgres")
    parser.add_argument("--rehearsal-id", default="")
    parser.add_argument(
        "--allow-existing-schema",
        action="store_true",
        help="Allow rehearsal against a database with existing public schema objects. Default requires an empty disposable database.",
    )
    parser.add_argument(
        "--allow-destructive-statements",
        action="store_true",
        help="Allow destructive migration statements after external review. Default fails closed when destructive statements are found.",
    )
    parser.add_argument("--json", action="store_true", help="Print the generated proof packet.")
    args = parser.parse_args()

    if not args.database_url.strip():
        parser.error("--database-url or MESH_MIGRATION_REHEARSAL_DATABASE_URL is required")

    try:
        import psycopg
    except ImportError:
        print('psycopg is required; install "psycopg[binary]>=3.2,<4"', file=sys.stderr)
        return 1

    try:
        packet = run_rehearsal(
            database_url=args.database_url,
            output_path=Path(args.output),
            operator_id=args.operator_id,
            environment=args.environment,
            migration_directory=args.migration_directory,
            rehearsal_id=args.rehearsal_id or None,
            allow_existing_schema=args.allow_existing_schema,
            allow_destructive_statements=args.allow_destructive_statements,
            connect=psycopg.connect,
        )
    except RehearsalError as exc:
        print(f"migration rehearsal failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(packet, indent=2, sort_keys=True))
    else:
        print(f"pass: {args.output} {packet['migration_version']} {packet['migration_combined_sha256']}")
    return 0


class RehearsalError(RuntimeError):
    pass


def run_rehearsal(
    *,
    database_url: str,
    output_path: Path,
    operator_id: str,
    environment: str,
    migration_directory: str,
    rehearsal_id: str | None,
    allow_existing_schema: bool,
    allow_destructive_statements: bool,
    connect: Callable[[str], Connection],
) -> dict[str, Any]:
    migration_paths = _migration_paths(migration_directory)
    destructive_matches = _destructive_statement_matches(migration_paths)
    if destructive_matches and not allow_destructive_statements:
        joined = ", ".join(destructive_matches)
        raise RehearsalError(f"destructive migration statements require --allow-destructive-statements: {joined}")

    conn = connect(database_url)
    try:
        pre_hash, pre_count = _schema_snapshot(conn)
        if pre_count and not allow_existing_schema:
            raise RehearsalError(
                f"database public schema is not empty ({pre_count} objects); use a disposable database or --allow-existing-schema"
            )

        started = time.monotonic()
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '60s'")
            cur.execute("SET lock_timeout = '10s'")
            for path in migration_paths:
                cur.execute(path.read_text(encoding="utf-8"))
        apply_seconds = time.monotonic() - started
        post_hash, post_count = _schema_snapshot(conn)
        if post_count <= pre_count:
            raise RehearsalError("migrations did not create additional schema objects")

        rollback_started = time.monotonic()
        conn.rollback()
        rollback_seconds = time.monotonic() - rollback_started
        rollback_hash, rollback_count = _schema_snapshot(conn)
    finally:
        conn.close()

    if rollback_hash != pre_hash or rollback_count != pre_count:
        raise RehearsalError("rollback did not restore the pre-migration schema snapshot")

    resolved_rehearsal_id = rehearsal_id or f"postgres_migration_rehearsal_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    packet = build_migration_rehearsal_packet(
        operator_id=operator_id,
        environment=environment,
        migration_directory=migration_directory,
        applied_migration_count=len(migration_paths),
        rolled_back=True,
        rollback_ref=f"postgres://migration-rehearsal/{resolved_rehearsal_id}/rollback/{rollback_hash}",
        pre_migration_snapshot_ref=f"postgres://migration-rehearsal/{resolved_rehearsal_id}/pre-schema/{pre_hash}",
        post_migration_validation_ref=f"postgres://migration-rehearsal/{resolved_rehearsal_id}/post-schema/{post_hash}",
        destructive_changes_reviewed=not destructive_matches or allow_destructive_statements,
        measured_apply_seconds=round(apply_seconds, 6),
        measured_rollback_seconds=round(rollback_seconds, 6),
        rehearsal_id=resolved_rehearsal_id,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verification = verify_migration_rehearsal(
        output_path,
        expected_migration_version=packet["migration_version"],
        expected_migration_combined_sha256=packet["migration_combined_sha256"],
    )
    if verification["status"] != "pass":
        raise RehearsalError(f"generated proof failed verification: {verification}")
    return packet


def _migration_paths(migration_directory: str) -> list[Path]:
    directory = Path(migration_directory)
    if not directory.is_absolute():
        directory = REPO_ROOT / directory
    paths = sorted(directory.glob("*.sql"))
    if not paths:
        raise RehearsalError(f"no migration SQL files found in {directory}")
    return paths


def _destructive_statement_matches(paths: list[Path]) -> list[str]:
    matches: list[str] = []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        for match in DESTRUCTIVE_STATEMENT_RE.finditer(content):
            line_number = content.count("\n", 0, match.start()) + 1
            matches.append(f"{_display_path(path)}:{line_number}")
    return matches


def _schema_snapshot(conn: Connection) -> tuple[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 'relation' AS object_type, n.nspname, c.relname, c.relkind::text
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'i', 'S', 'v', 'm')
            UNION ALL
            SELECT 'function' AS object_type, n.nspname, p.proname, p.prokind::text || ':' || pg_get_function_identity_arguments(p.oid)
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
            UNION ALL
            SELECT 'type' AS object_type, n.nspname, t.typname, t.typtype::text
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
              AND t.typtype IN ('b', 'c', 'd', 'e', 'r')
            UNION ALL
            SELECT 'extension' AS object_type, n.nspname, e.extname, e.extversion
            FROM pg_extension e
            JOIN pg_namespace n ON n.oid = e.extnamespace
            WHERE n.nspname = 'public'
            ORDER BY 1, 2, 3, 4
            """
        )
        rows = [tuple(str(part) for part in row) for row in cur.fetchall()]
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(rows)


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
