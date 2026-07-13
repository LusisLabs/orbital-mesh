from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.actuators.repo_patch_authority_service import _authority_store_from_environment
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.repo_patch_authority_store import (
    AuthorityStateError,
    FileRepoPatchAuthorityStore,
)


FIXED_NOW = datetime(2026, 7, 12, 16, 0, tzinfo=timezone.utc)


class RepoPatchAuthorityLifecycleTests(unittest.TestCase):
    def test_expired_pre_dispatch_lease_reclaims_with_fresh_fence_and_event(self) -> None:
        now = [FIXED_NOW]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileRepoPatchAuthorityStore(temp_dir, clock=lambda: now[0])
            issued = store.issue_or_get(
                authority_id="authority-expired-lease",
                idempotency_key="decision:execute",
                nonce="a" * 64,
                action_binding={"operation": "execute", "decision_digest": "sha256:" + ("b" * 64)},
            )
            leased = store.lease_for_dispatch(
                str(issued["authority_id"]),
                expected_version=int(issued["version"]),
                lease_id="lease-before-crash",
                lease_seconds=1,
            )
            with self.assertRaises(AuthorityStateError):
                store.lease_for_dispatch(
                    str(leased["authority_id"]),
                    expected_version=int(leased["version"]),
                    lease_id="lease-too-early",
                )
            now[0] = FIXED_NOW + timedelta(seconds=2)

            reclaimed = store.lease_for_dispatch(
                str(leased["authority_id"]),
                expected_version=int(leased["version"]),
                lease_id="lease-after-crash",
            )
            reconciliation = store.read_for_reconciliation(str(issued["authority_id"]))

        self.assertEqual(reclaimed["state"], "leased")
        self.assertEqual(reclaimed["lease_id"], "lease-after-crash")
        self.assertEqual(reclaimed["version"], 3)
        assert reconciliation is not None
        self.assertEqual(
            [event["event_type"] for event in reconciliation["events"]],
            ["issued", "leased_for_dispatch", "expired_pre_dispatch_lease_reclaimed"],
        )
        self.assertTrue(reconciliation["event_chain_valid"])

    def test_authority_store_backend_is_explicit_and_postgres_requires_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_directory = Path(temp_dir)
            with patch.dict(os.environ, {"MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND": "file"}):
                file_store = _authority_store_from_environment(state_directory, RuntimeConfig())
            self.assertIsInstance(file_store, FileRepoPatchAuthorityStore)

            with patch.dict(os.environ, {"MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND": "postgres"}):
                with self.assertRaisesRegex(RuntimeError, "MESH_DATABASE_URL"):
                    _authority_store_from_environment(state_directory, RuntimeConfig(database_url=None))

            sentinel = object()
            with (
                patch.dict(os.environ, {"MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND": "postgres"}),
                patch(
                    "services.actuators.repo_patch_authority_service.PostgresRepoPatchAuthorityStore",
                    return_value=sentinel,
                ) as postgres_store,
            ):
                selected = _authority_store_from_environment(
                    state_directory,
                    RuntimeConfig(database_url="postgresql://mesh.invalid/mesh"),
                )
            self.assertIs(selected, sentinel)
            postgres_store.assert_called_once()

            with patch.dict(os.environ, {"MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND": "unknown"}):
                with self.assertRaisesRegex(RuntimeError, "file.*postgres"):
                    _authority_store_from_environment(state_directory, RuntimeConfig())


if __name__ == "__main__":
    unittest.main()
