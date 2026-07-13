from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shared.mesh_runtime.repo_patch_authority_store import (
    AUTHORITY_STORE_VERSION,
    AuthorityConflictError,
    AuthorityStateError,
    AuthorityStoreError,
    FileRepoPatchAuthorityStore,
    PostgresRepoPatchAuthorityStore,
)


FIXED_NOW = datetime(2026, 7, 12, 16, 0, tzinfo=timezone.utc)


def _binding(*, replacement: str = "new") -> dict[str, Any]:
    return {
        "mesh_run_id": "run-authority-1",
        "mesh_action_id": "action-authority-1",
        "policy_digest": "sha256:" + ("a" * 64),
        "evidence_digest": "sha256:" + ("b" * 64),
        "actuation": {
            "repo_path": "/tmp/disposable-repo",
            "target_file": "app/search.py",
            "find": "old",
            "replace": replacement,
        },
    }


class FileRepoPatchAuthorityStoreTests(unittest.TestCase):
    def test_missing_reconciliation_read_does_not_materialize_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)

            self.assertIsNone(store.read_for_reconciliation("missing-authority"))
            self.assertFalse(store.path.exists())

    def test_issue_lease_dispatch_complete_and_reconcile_append_only_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)
            issued = store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="1" * 64,
                action_binding=_binding(),
            )
            leased = store.lease_for_dispatch(
                "authority-1",
                expected_version=issued["version"],
                lease_id="lease-1",
            )
            dispatched = store.mark_dispatched(
                "authority-1",
                expected_version=leased["version"],
                lease_id="lease-1",
            )
            terminal = store.complete_terminal(
                "authority-1",
                expected_version=dispatched["version"],
                lease_id="lease-1",
                outcome="succeeded",
                result={"postimage_digest": "sha256:" + ("c" * 64)},
            )

            reconciliation = store.read_for_reconciliation("authority-1")

        self.assertEqual((issued["state"], leased["state"], dispatched["state"]), ("issued", "leased", "dispatched"))
        self.assertEqual(terminal["state"], "terminal")
        self.assertEqual(terminal["terminal_outcome"], "succeeded")
        assert reconciliation is not None
        self.assertEqual(reconciliation["schema_version"], AUTHORITY_STORE_VERSION)
        self.assertTrue(reconciliation["event_chain_valid"])
        self.assertEqual([event["event_type"] for event in reconciliation["events"]], [
            "issued",
            "leased_for_dispatch",
            "marked_dispatched",
            "terminal_completed",
        ])
        self.assertEqual(reconciliation["record"]["event_sequence"], 4)

    def test_issue_or_get_is_idempotent_and_binds_the_complete_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)
            first = store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="2" * 64,
                action_binding=_binding(),
            )
            repeated = store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="2" * 64,
                action_binding=_binding(),
            )
            with self.assertRaises(AuthorityConflictError):
                store.issue_or_get(
                    authority_id="authority-1",
                    idempotency_key="decision-1:investigate_and_patch",
                    nonce="2" * 64,
                    action_binding=_binding(replacement="drifted"),
                )
            with self.assertRaises(AuthorityConflictError):
                store.issue_or_get(
                    authority_id="authority-2",
                    idempotency_key="decision-2:investigate_and_patch",
                    nonce="2" * 64,
                    action_binding=_binding(),
                )
            reconciliation = store.read_for_reconciliation("authority-1")

        self.assertEqual(first, repeated)
        assert reconciliation is not None
        self.assertEqual(len(reconciliation["events"]), 1)

    def test_compare_and_set_and_lease_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)
            store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="3" * 64,
                action_binding=_binding(),
            )
            leased = store.lease_for_dispatch("authority-1", expected_version=1, lease_id="lease-1")
            with self.assertRaises(AuthorityConflictError):
                store.mark_dispatched("authority-1", expected_version=1, lease_id="lease-1")
            with self.assertRaises(AuthorityConflictError):
                store.mark_dispatched("authority-1", expected_version=leased["version"], lease_id="wrong-lease")
            dispatched = store.mark_dispatched(
                "authority-1",
                expected_version=leased["version"],
                lease_id="lease-1",
            )
            with self.assertRaises(AuthorityStateError):
                store.lease_for_dispatch(
                    "authority-1",
                    expected_version=dispatched["version"],
                    lease_id="lease-2",
                )

    def test_pre_dispatch_lease_can_fail_terminal_but_cannot_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)
            store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="4" * 64,
                action_binding=_binding(),
            )
            leased = store.lease_for_dispatch("authority-1", expected_version=1, lease_id="lease-1")
            with self.assertRaises(AuthorityStateError):
                store.complete_terminal(
                    "authority-1",
                    expected_version=leased["version"],
                    lease_id="lease-1",
                    outcome="succeeded",
                    result={},
                )
            terminal = store.complete_terminal(
                "authority-1",
                expected_version=leased["version"],
                lease_id="lease-1",
                outcome="failed",
                result={"reason": "preflight_failed"},
            )

        self.assertEqual(terminal["terminal_outcome"], "failed")

    def test_expired_lease_cannot_be_marked_dispatched(self) -> None:
        now = [FIXED_NOW]
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: now[0])
            store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="9" * 64,
                action_binding=_binding(),
            )
            leased = store.lease_for_dispatch(
                "authority-1",
                expected_version=1,
                lease_id="lease-1",
                lease_seconds=1,
            )
            now[0] = FIXED_NOW + timedelta(seconds=2)

            with self.assertRaises(AuthorityStateError):
                store.mark_dispatched(
                    "authority-1",
                    expected_version=leased["version"],
                    lease_id="lease-1",
                )

    def test_sixteen_concurrent_lease_attempts_have_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)
            store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="5" * 64,
                action_binding=_binding(),
            )

            def attempt(index: int) -> str:
                try:
                    store.lease_for_dispatch(
                        "authority-1",
                        expected_version=1,
                        lease_id=f"lease-{index}",
                    )
                    return "leased"
                except (AuthorityConflictError, AuthorityStateError):
                    return "blocked"

            with ThreadPoolExecutor(max_workers=16) as pool:
                outcomes = list(pool.map(attempt, range(16)))

        self.assertEqual(outcomes.count("leased"), 1)
        self.assertEqual(outcomes.count("blocked"), 15)

    def test_invalid_nonce_and_non_json_binding_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)
            with self.assertRaises(AuthorityStoreError):
                store.issue_or_get(
                    authority_id="authority-1",
                    idempotency_key="decision-1:investigate_and_patch",
                    nonce="not-a-nonce",
                    action_binding=_binding(),
                )
            invalid = _binding()
            invalid["invalid"] = {1, 2, 3}
            with self.assertRaises(AuthorityStoreError):
                store.issue_or_get(
                    authority_id="authority-1",
                    idempotency_key="decision-1:investigate_and_patch",
                    nonce="6" * 64,
                    action_binding=invalid,
                )

    def test_reconciliation_rejects_action_binding_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRepoPatchAuthorityStore(tmp, clock=lambda: FIXED_NOW)
            store.issue_or_get(
                authority_id="authority-1",
                idempotency_key="decision-1:investigate_and_patch",
                nonce="8" * 64,
                action_binding=_binding(),
            )
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            payload["records"]["authority-1"]["action_binding"]["actuation"]["replace"] = "tampered"
            store.path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(AuthorityStoreError):
                store.read_for_reconciliation("authority-1")


class PostgresRepoPatchAuthorityStoreTests(unittest.TestCase):
    def test_postgres_store_matches_file_state_machine_and_uses_cas(self) -> None:
        database = _FakePostgresDatabase()
        store = PostgresRepoPatchAuthorityStore(
            connection_factory=database.connect,
            json_adapter=lambda value: value,
            clock=lambda: FIXED_NOW,
        )
        issued = store.issue_or_get(
            authority_id="authority-pg-1",
            idempotency_key="decision-pg-1:investigate_and_patch",
            nonce="7" * 64,
            action_binding=_binding(),
        )
        repeated = store.issue_or_get(
            authority_id="authority-pg-1",
            idempotency_key="decision-pg-1:investigate_and_patch",
            nonce="7" * 64,
            action_binding=_binding(),
        )
        leased = store.lease_for_dispatch("authority-pg-1", expected_version=1, lease_id="lease-pg-1")
        dispatched = store.mark_dispatched(
            "authority-pg-1",
            expected_version=leased["version"],
            lease_id="lease-pg-1",
        )
        terminal = store.complete_terminal(
            "authority-pg-1",
            expected_version=dispatched["version"],
            lease_id="lease-pg-1",
            outcome="succeeded",
            result={"receipt": "ok"},
        )
        reconciliation = store.read_for_reconciliation("authority-pg-1")

        self.assertEqual(issued, repeated)
        self.assertEqual(terminal["version"], 4)
        assert reconciliation is not None
        self.assertTrue(reconciliation["event_chain_valid"])
        self.assertEqual(len(reconciliation["events"]), 4)
        self.assertGreaterEqual(database.advisory_locks, 3)
        self.assertEqual(database.cas_updates, 3)

    def test_postgres_migration_has_unique_nonce_cas_state_and_append_only_receipts(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "postgres"
            / "006_repo_patch_authority_store.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS repo_patch_authority_records", migration)
        self.assertIn("nonce TEXT NOT NULL UNIQUE", migration)
        self.assertIn("version BIGINT NOT NULL", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS repo_patch_authority_events", migration)
        self.assertIn("BEFORE UPDATE OR DELETE ON repo_patch_authority_events", migration)


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)


class _FakePostgresDatabase:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.advisory_locks = 0
        self.cas_updates = 0

    @contextmanager
    def connect(self):
        yield _FakeConnection(self)


class _FakeConnection:
    def __init__(self, database: _FakePostgresDatabase) -> None:
        self.database = database

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _FakeResult:
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT pg_advisory_xact_lock"):
            self.database.advisory_locks += 1
            return _FakeResult([(None,)])
        if "WHERE authority_id = %s OR idempotency_key = %s OR nonce = %s" in normalized:
            authority_id, idempotency_key, nonce = params
            for record in self.database.records.values():
                if (
                    record["authority_id"] == authority_id
                    or record["idempotency_key"] == idempotency_key
                    or record["nonce"] == nonce
                ):
                    return _FakeResult([(record,)])
            return _FakeResult()
        if normalized.startswith("INSERT INTO repo_patch_authority_records"):
            record = params[8]
            self.database.records[str(params[0])] = record
            return _FakeResult()
        if normalized.startswith("SELECT record FROM repo_patch_authority_records WHERE authority_id = %s"):
            record = self.database.records.get(str(params[0]))
            return _FakeResult([(record,)]) if record is not None else _FakeResult()
        if normalized.startswith("UPDATE repo_patch_authority_records"):
            authority_id = str(params[6])
            expected_version = params[7]
            expected_state = params[8]
            current = self.database.records.get(authority_id)
            if current is None or current["version"] != expected_version or current["state"] != expected_state:
                return _FakeResult()
            self.database.records[authority_id] = params[4]
            self.database.cas_updates += 1
            return _FakeResult([(authority_id,)])
        if normalized.startswith("INSERT INTO repo_patch_authority_events"):
            receipt = params[8]
            self.database.events.setdefault(str(params[0]), []).append(receipt)
            return _FakeResult()
        if normalized.startswith("SELECT receipt FROM repo_patch_authority_events"):
            return _FakeResult([(event,) for event in self.database.events.get(str(params[0]), [])])
        raise AssertionError(f"unexpected SQL: {normalized}")


if __name__ == "__main__":
    unittest.main()
