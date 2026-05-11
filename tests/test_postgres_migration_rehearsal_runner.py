from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.run_postgres_migration_rehearsal import RehearsalError, run_rehearsal
from shared.mesh_runtime.migration_rehearsal import verify_migration_rehearsal


class PostgresMigrationRehearsalRunnerTests(unittest.TestCase):
    def test_run_rehearsal_writes_verified_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "migration-rehearsal.json"
            connection = _FakeConnection()

            packet = run_rehearsal(
                database_url="postgresql://mesh:mesh@localhost:5432/mesh",
                output_path=output_path,
                operator_id="github-actions",
                environment="ci",
                migration_directory="migrations/postgres",
                rehearsal_id="postgres_migration_rehearsal_test",
                allow_existing_schema=False,
                allow_destructive_statements=False,
                connect=lambda _: connection,
            )
            verification = verify_migration_rehearsal(
                output_path,
                expected_migration_version=packet["migration_version"],
                expected_migration_combined_sha256=packet["migration_combined_sha256"],
            )
            self.assertTrue(output_path.exists())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["rehearsal_id"], "postgres_migration_rehearsal_test")

        self.assertEqual(packet["schema_version"], "mesh.migration_rehearsal.v1")
        self.assertEqual(packet["environment"], "ci")
        self.assertTrue(packet["rolled_back"])
        self.assertTrue(packet["destructive_changes_reviewed"])
        self.assertEqual(packet["applied_migration_count"], 5)
        self.assertTrue(packet["rollback_ref"].startswith("postgres://migration-rehearsal/postgres_migration_rehearsal_test/rollback/"))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(connection.rollback_count, 1)

    def test_run_rehearsal_rejects_existing_schema_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "migration-rehearsal.json"
            connection = _FakeConnection(existing_rows=[("function", "public", "existing_function", "f:")])

            with self.assertRaisesRegex(RehearsalError, "public schema is not empty"):
                run_rehearsal(
                    database_url="postgresql://mesh:mesh@localhost:5432/mesh",
                    output_path=output_path,
                    operator_id="github-actions",
                    environment="ci",
                    migration_directory="migrations/postgres",
                    rehearsal_id="postgres_migration_rehearsal_test",
                    allow_existing_schema=False,
                    allow_destructive_statements=False,
                    connect=lambda _: connection,
                )

        self.assertFalse(output_path.exists())

    def test_run_rehearsal_rejects_destructive_migration_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            migration_dir = Path(tmp) / "migrations"
            migration_dir.mkdir()
            (migration_dir / "001_drop.sql").write_text("DROP TABLE important;\n", encoding="utf-8")

            with self.assertRaisesRegex(RehearsalError, "destructive migration statements"):
                run_rehearsal(
                    database_url="postgresql://mesh:mesh@localhost:5432/mesh",
                    output_path=Path(tmp) / "migration-rehearsal.json",
                    operator_id="github-actions",
                    environment="ci",
                    migration_directory=str(migration_dir),
                    rehearsal_id="postgres_migration_rehearsal_test",
                    allow_existing_schema=False,
                    allow_destructive_statements=False,
                    connect=lambda _: _FakeConnection(),
                )

    def test_run_rehearsal_rejects_multiline_destructive_migration_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            migration_dir = Path(tmp) / "migrations"
            migration_dir.mkdir()
            (migration_dir / "001_drop.sql").write_text("DROP\nTABLE important;\n", encoding="utf-8")
            (migration_dir / "002_alter.sql").write_text(
                "ALTER TABLE users\nDROP COLUMN legacy_flag;\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RehearsalError, "destructive migration statements"):
                run_rehearsal(
                    database_url="postgresql://mesh:mesh@localhost:5432/mesh",
                    output_path=Path(tmp) / "migration-rehearsal.json",
                    operator_id="github-actions",
                    environment="ci",
                    migration_directory=str(migration_dir),
                    rehearsal_id="postgres_migration_rehearsal_test",
                    allow_existing_schema=False,
                    allow_destructive_statements=False,
                    connect=lambda _: _FakeConnection(),
                )


class _FakeConnection:
    def __init__(self, existing_rows: list[tuple[str, ...]] | None = None) -> None:
        self._initial_rows = list(existing_rows or [])
        self._rows = list(self._initial_rows)
        self.rollback_count = 0
        self.closed = False

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self)

    def rollback(self) -> None:
        self.rollback_count += 1
        self._rows = list(self._initial_rows)

    def close(self) -> None:
        self.closed = True


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection
        self._select_schema = False

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        del params
        normalized = query.strip().lower()
        self._select_schema = "from pg_class" in normalized and "pg_namespace" in normalized
        if normalized.startswith("create table"):
            table_name = normalized.split()[5]
            self._connection._rows.append(("relation", "public", table_name, "r"))
        if normalized.startswith("create index"):
            index_name = normalized.split()[5]
            self._connection._rows.append(("relation", "public", index_name, "i"))

    def fetchall(self) -> list[tuple[str, ...]]:
        if not self._select_schema:
            return []
        return sorted(self._connection._rows)


if __name__ == "__main__":
    unittest.main()
