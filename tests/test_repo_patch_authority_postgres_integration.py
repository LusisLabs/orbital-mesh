from __future__ import annotations

import os
import subprocess
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from shared.mesh_runtime.repo_patch_authority_store import (
    AuthorityConflictError,
    PostgresRepoPatchAuthorityStore,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "migrations" / "postgres" / "006_repo_patch_authority_store.sql"
RUN_POSTGRES_INTEGRATION = os.getenv("MESH_RUN_POSTGRES_AUTHORITY_INTEGRATION") == "1"
FIXED_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def _binding(*, action_id: str, replacement: str = "new") -> dict[str, Any]:
    return {
        "mesh_run_id": "run-postgres-authority-rehearsal",
        "mesh_action_id": action_id,
        "policy_digest": "sha256:" + ("a" * 64),
        "evidence_digest": "sha256:" + ("b" * 64),
        "actuation": {
            "repo_path": "/tmp/disposable-repo",
            "target_file": "app/search.py",
            "find": "old",
            "replace": replacement,
        },
    }


@unittest.skipUnless(
    RUN_POSTGRES_INTEGRATION,
    "set MESH_RUN_POSTGRES_AUTHORITY_INTEGRATION=1 to run the Docker-backed PostgreSQL rehearsal",
)
class RepoPatchAuthorityPostgresIntegrationTests(unittest.TestCase):
    """Real PostgreSQL rehearsal for mesh.repo_patch_authority_postgres_rehearsal.v1."""

    container_name: str
    database_url: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.container_name = f"mesh-authority-postgres-{uuid4().hex[:12]}"
        image = os.getenv("MESH_POSTGRES_TEST_IMAGE", "postgres:16-alpine")
        cls._docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            cls.container_name,
            "--env",
            "POSTGRES_USER=mesh",
            "--env",
            "POSTGRES_PASSWORD=mesh",
            "--env",
            "POSTGRES_DB=mesh",
            "--publish",
            "127.0.0.1::5432",
            image,
        )
        cls.addClassCleanup(cls._remove_container)
        cls._refresh_database_url()
        cls._wait_for_postgres()
        cls._apply_migration()
        cls._apply_migration()

    @classmethod
    def _remove_container(cls) -> None:
        subprocess.run(
            ["docker", "rm", "--force", cls.container_name],
            check=False,
            capture_output=True,
            text=True,
        )

    @classmethod
    def _docker(cls, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args],
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def _refresh_database_url(cls) -> None:
        port_output = cls._docker("port", cls.container_name, "5432/tcp").stdout.strip()
        port = port_output.rsplit(":", 1)[-1]
        cls.database_url = f"postgresql://mesh:mesh@127.0.0.1:{port}/mesh"

    @classmethod
    def _wait_for_postgres(cls) -> None:
        import psycopg

        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(cls.database_url, connect_timeout=2) as conn:
                    conn.execute("SELECT 1")
                return
            except psycopg.OperationalError as exc:
                last_error = exc
                time.sleep(0.1)
        raise AssertionError(f"PostgreSQL did not become ready: {last_error}")

    @classmethod
    def _apply_migration(cls) -> None:
        import psycopg

        with psycopg.connect(cls.database_url) as conn:
            conn.execute(MIGRATION_PATH.read_text(encoding="utf-8"))

    @classmethod
    @contextmanager
    def _connect(cls) -> Iterator[Any]:
        import psycopg

        with psycopg.connect(cls.database_url) as conn:
            yield conn

    def _store(self) -> PostgresRepoPatchAuthorityStore:
        return PostgresRepoPatchAuthorityStore(
            connection_factory=self._connect,
            clock=lambda: FIXED_NOW,
        )

    def _restart_postgres(self) -> None:
        self._docker("restart", self.container_name)
        self._refresh_database_url()
        self._wait_for_postgres()

    def test_migration_lifecycle_fencing_event_chain_and_restart_persistence(self) -> None:
        import psycopg

        with self._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name LIKE 'repo_patch_authority_%'
                    """
                ).fetchall()
            }
            append_only_trigger = conn.execute(
                """
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'repo_patch_authority_events_append_only' AND NOT tgisinternal
                """
            ).fetchone()

        self.assertEqual(
            tables,
            {"repo_patch_authority_records", "repo_patch_authority_events"},
        )
        self.assertIsNotNone(append_only_trigger)

        first_store = self._store()
        issued = first_store.issue_or_get(
            authority_id="authority-postgres-1",
            idempotency_key="decision-postgres-1:investigate_and_patch",
            nonce="1" * 64,
            action_binding=_binding(action_id="action-postgres-1"),
        )
        repeated = first_store.issue_or_get(
            authority_id="authority-postgres-1",
            idempotency_key="decision-postgres-1:investigate_and_patch",
            nonce="1" * 64,
            action_binding=_binding(action_id="action-postgres-1"),
        )
        self.assertEqual(issued, repeated)

        with self.assertRaises(AuthorityConflictError):
            first_store.issue_or_get(
                authority_id="authority-postgres-1",
                idempotency_key="decision-postgres-1:investigate_and_patch",
                nonce="1" * 64,
                action_binding=_binding(action_id="action-postgres-1", replacement="tampered"),
            )

        def attempt_lease(lease_id: str) -> tuple[str, dict[str, Any] | None]:
            try:
                return (
                    "leased",
                    self._store().lease_for_dispatch(
                        "authority-postgres-1",
                        expected_version=issued["version"],
                        lease_id=lease_id,
                    ),
                )
            except AuthorityConflictError:
                return "conflict", None

        with ThreadPoolExecutor(max_workers=2) as executor:
            lease_results = list(executor.map(attempt_lease, ("lease-postgres-a", "lease-postgres-b")))
        self.assertEqual([status for status, _ in lease_results].count("leased"), 1)
        self.assertEqual([status for status, _ in lease_results].count("conflict"), 1)
        leased = next(record for status, record in lease_results if status == "leased")
        assert leased is not None
        winning_lease_id = leased["lease_id"]

        with self.assertRaises(AuthorityConflictError):
            first_store.mark_dispatched(
                "authority-postgres-1",
                expected_version=leased["version"],
                lease_id="lease-wrong-fence",
            )

        dispatched = first_store.mark_dispatched(
            "authority-postgres-1",
            expected_version=leased["version"],
            lease_id=winning_lease_id,
        )
        self._restart_postgres()

        restarted_store = self._store()
        recovered_dispatched = restarted_store.read_for_reconciliation("authority-postgres-1")
        assert recovered_dispatched is not None
        self.assertEqual(recovered_dispatched["record"], dispatched)
        self.assertTrue(recovered_dispatched["event_chain_valid"])
        self.assertEqual(
            [event["event_type"] for event in recovered_dispatched["events"]],
            ["issued", "leased_for_dispatch", "marked_dispatched"],
        )

        terminal = restarted_store.complete_terminal(
            "authority-postgres-1",
            expected_version=dispatched["version"],
            lease_id=winning_lease_id,
            outcome="succeeded",
            result={"postimage_digest": "sha256:" + ("c" * 64)},
        )
        self.assertEqual(terminal["state"], "terminal")
        self.assertEqual(terminal["terminal_outcome"], "succeeded")

        second_issued = restarted_store.issue_or_get(
            authority_id="authority-postgres-2",
            idempotency_key="decision-postgres-2:investigate_and_patch",
            nonce="2" * 64,
            action_binding=_binding(action_id="action-postgres-2"),
        )
        second_leased = restarted_store.lease_for_dispatch(
            "authority-postgres-2",
            expected_version=second_issued["version"],
            lease_id="lease-postgres-2",
        )
        rejected = restarted_store.complete_terminal(
            "authority-postgres-2",
            expected_version=second_leased["version"],
            lease_id="lease-postgres-2",
            outcome="rejected",
            result={"reason": "policy_rejected_before_dispatch"},
        )
        self.assertEqual(rejected["terminal_outcome"], "rejected")

        with self._connect() as conn:
            with self.assertRaises(psycopg.Error):
                conn.execute(
                    """
                    UPDATE repo_patch_authority_events
                    SET event_type = 'tampered'
                    WHERE authority_id = %s AND sequence = 1
                    """,
                    ("authority-postgres-1",),
                )

        self._restart_postgres()
        final_store = self._store()
        reconciliation = final_store.read_for_reconciliation("authority-postgres-1")
        rejected_reconciliation = final_store.read_for_reconciliation("authority-postgres-2")
        assert reconciliation is not None
        assert rejected_reconciliation is not None
        self.assertTrue(reconciliation["event_chain_valid"])
        self.assertEqual(reconciliation["record"], terminal)
        self.assertEqual(reconciliation["record"]["event_sequence"], 4)
        self.assertEqual(
            [event["event_type"] for event in reconciliation["events"]],
            ["issued", "leased_for_dispatch", "marked_dispatched", "terminal_completed"],
        )
        self.assertTrue(rejected_reconciliation["event_chain_valid"])
        self.assertEqual(rejected_reconciliation["record"]["terminal_outcome"], "rejected")


if __name__ == "__main__":
    unittest.main()
