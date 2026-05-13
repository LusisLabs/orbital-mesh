"""Tests for the process-wide Postgres connection pool.

These tests do NOT require a live Postgres. The pool factory and
``_connect`` boundary are exercised with ``psycopg_pool.ConnectionPool``
patched to a counting fake — that's the contract we care about: one
pool per DSN, reuse across stores, deterministic teardown.

The live-Postgres path (running queries) is covered by the existing
``test_mesh_state_store`` suite when a real DB is available; this file
focuses on the per-call handshake elimination that was the headline
performance fix.
"""

from __future__ import annotations

import threading
import unittest
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime import postgres_state as ps


# ---------------------------------------------------------------------------
# Fake pool: counts how many real pools the module would create and how
# many connection checkouts happen against each.
# ---------------------------------------------------------------------------


class _FakeConnection:
    """Minimal connection stand-in. The pool's ``connection()`` context
    manager hands one of these out; the existing store code only calls
    ``conn.execute`` so we don't need anything else."""

    def __init__(self, pool: "_FakePool") -> None:
        self._pool = pool

    def execute(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover — exercised by mocks only
        raise AssertionError("execute should not be called in pool-shape tests")


class _FakePool:
    """A counting fake of ``psycopg_pool.ConnectionPool``.

    Tracks how many connection checkouts have happened so a test can
    assert ``N store ops -> 1 pool, M checkouts``. ``open=True`` is
    accepted but ignored — we don't simulate background workers.
    """

    instances: list["_FakePool"] = []

    def __init__(self, *, conninfo: str, min_size: int, max_size: int, **kwargs: Any) -> None:
        self.conninfo = conninfo
        self.min_size = min_size
        self.max_size = max_size
        self.kwargs = kwargs
        self.checkouts = 0
        self.closed = False
        _FakePool.instances.append(self)

    @contextmanager
    def connection(self) -> Any:
        if self.closed:
            raise RuntimeError("pool is closed")
        self.checkouts += 1
        yield _FakeConnection(self)

    def close(self) -> None:
        self.closed = True


def _reset_module_state() -> None:
    """Tear down the module-level pool registry between tests.

    The module caches pools by DSN; tests that reuse the same DSN would
    otherwise observe state from a previous test. ``close_all_pools``
    handles the close + clear in one step.
    """
    ps.close_all_pools()
    _FakePool.instances.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class PostgresPoolFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()

    def test_pool_is_created_once_per_dsn(self) -> None:
        cfg = RuntimeConfig(
            state_backend="postgres",
            database_url="postgresql://test/db1",
            postgres_pool_min_size=2,
            postgres_pool_max_size=8,
        )
        with patch("psycopg_pool.ConnectionPool", _FakePool):
            pool1 = ps._get_or_create_pool(cfg)
            pool2 = ps._get_or_create_pool(cfg)
            pool3 = ps._get_or_create_pool(cfg)

        self.assertIs(pool1, pool2)
        self.assertIs(pool2, pool3)
        # Only ONE underlying pool was created across three factory calls;
        # this is the contract that turns 27 connect() sites into one
        # shared pool per DSN.
        self.assertEqual(len(_FakePool.instances), 1)
        self.assertEqual(pool1.min_size, 2)
        self.assertEqual(pool1.max_size, 8)

    def test_distinct_dsns_get_distinct_pools(self) -> None:
        cfg_a = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/a")
        cfg_b = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/b")

        with patch("psycopg_pool.ConnectionPool", _FakePool):
            pool_a = ps._get_or_create_pool(cfg_a)
            pool_b = ps._get_or_create_pool(cfg_b)

        self.assertIsNot(pool_a, pool_b)
        self.assertEqual(len(_FakePool.instances), 2)
        # And re-resolving each DSN returns the same pool, not a third one.
        with patch("psycopg_pool.ConnectionPool", _FakePool):
            self.assertIs(ps._get_or_create_pool(cfg_a), pool_a)
            self.assertIs(ps._get_or_create_pool(cfg_b), pool_b)
        self.assertEqual(len(_FakePool.instances), 2)

    def test_missing_database_url_raises_clear_error(self) -> None:
        cfg = RuntimeConfig(state_backend="postgres", database_url=None)
        with self.assertRaises(ValueError) as ctx:
            ps._get_or_create_pool(cfg)
        self.assertIn("MESH_DATABASE_URL", str(ctx.exception))

    def test_close_all_pools_closes_and_clears(self) -> None:
        cfg_a = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/a")
        cfg_b = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/b")

        with patch("psycopg_pool.ConnectionPool", _FakePool):
            ps._get_or_create_pool(cfg_a)
            ps._get_or_create_pool(cfg_b)

        self.assertEqual(len(_FakePool.instances), 2)
        ps.close_all_pools()

        # Every pool got close() called and the registry is empty.
        self.assertTrue(all(p.closed for p in _FakePool.instances))
        self.assertEqual(ps._POOLS, {})

    def test_close_failures_do_not_propagate(self) -> None:
        """Teardown is best-effort — one broken close() must not block
        the rest of the registry from clearing."""

        class _BrokenPool(_FakePool):
            def close(self) -> None:  # noqa: D401
                raise RuntimeError("simulated close failure")

        cfg_ok = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/ok")
        cfg_bad = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/bad")

        with patch("psycopg_pool.ConnectionPool", _FakePool):
            ps._get_or_create_pool(cfg_ok)
        with patch("psycopg_pool.ConnectionPool", _BrokenPool):
            ps._get_or_create_pool(cfg_bad)

        # Should not raise even though the broken pool's close() errors.
        ps.close_all_pools()
        self.assertEqual(ps._POOLS, {})


class PostgresConnectIntegrationTests(unittest.TestCase):
    """``PostgresStateStore._connect`` is the function 27 query sites
    call. It must return a context manager that yields a connection,
    and across N invocations it must reuse the shared pool — that's
    the per-call handshake elimination."""

    def setUp(self) -> None:
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()

    def test_connect_uses_pool_and_reuses_across_calls(self) -> None:
        cfg = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/x")

        # Patch BOTH psycopg (the import sanity check at the top of
        # _connect) and the pool factory so no real driver is needed.
        with (
            patch("psycopg_pool.ConnectionPool", _FakePool),
            # Schema bootstrap calls _initialize_schema on store init;
            # patch it so we don't need a real DB for the pool-shape test.
            patch.object(ps.PostgresStateStore, "_initialize_schema", lambda self: None),
        ):
            store = ps.PostgresStateStore(cfg)
            with store._connect() as _c1:
                pass
            with store._connect() as _c2:
                pass
            with store._connect() as _c3:
                pass

        # ONE pool was opened despite three _connect() calls.
        self.assertEqual(len(_FakePool.instances), 1)
        # And three checkouts happened (one per `with` block) — pool
        # reuse, not three handshakes.
        self.assertEqual(_FakePool.instances[0].checkouts, 3)

    def test_two_stores_same_dsn_share_one_pool(self) -> None:
        cfg = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/shared")
        with (
            patch("psycopg_pool.ConnectionPool", _FakePool),
            patch.object(ps.PostgresStateStore, "_initialize_schema", lambda self: None),
        ):
            store_a = ps.PostgresStateStore(cfg)
            store_b = ps.PostgresStateStore(cfg)
            with store_a._connect():
                pass
            with store_b._connect():
                pass

        # The control-plane spawns multiple stores (one per worker
        # thread, one per worktree). They must converge on one pool.
        self.assertEqual(len(_FakePool.instances), 1)
        self.assertEqual(_FakePool.instances[0].checkouts, 2)


class RedactDsnTests(unittest.TestCase):
    """``_redact_dsn`` runs on every pool open via the info-level log
    line. A bug here leaks credentials to logs at every fresh DSN."""

    def test_postgres_url_strips_password(self) -> None:
        self.assertEqual(
            ps._redact_dsn("postgres://mesh:supersecret@db.example.com/mesh"),
            "postgres://mesh:***@db.example.com/mesh",
        )

    def test_postgresql_scheme_also_redacted(self) -> None:
        self.assertEqual(
            ps._redact_dsn("postgresql://u:p@host:5432/db?sslmode=require"),
            "postgresql://u:***@host:5432/db?sslmode=require",
        )

    def test_passwordless_dsn_passes_through_untouched(self) -> None:
        # Some local dev setups use trust auth; nothing to redact.
        self.assertEqual(
            ps._redact_dsn("postgres://mesh@localhost/mesh"),
            "postgres://mesh@localhost/mesh",
        )

    def test_key_value_form_logged_verbatim(self) -> None:
        # Conservative: we don't try to parse key=value DSNs. Mesh
        # config writes URL form; if an operator passes key=value they
        # accept the verbatim log.
        raw = "host=localhost dbname=mesh user=mesh password=secret"
        self.assertEqual(ps._redact_dsn(raw), raw)


class ConcurrencySafetyTests(unittest.TestCase):
    """Pool creation is guarded by ``_POOLS_LOCK``. Without it, two
    threads racing on the first ``_get_or_create_pool`` for a fresh DSN
    could each construct a pool, leaking one. This test races N threads
    against a single DSN and asserts exactly one pool was constructed."""

    def setUp(self) -> None:
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()

    def test_concurrent_first_call_creates_only_one_pool(self) -> None:
        cfg = RuntimeConfig(state_backend="postgres", database_url="postgresql://test/race")
        results: list[Any] = []
        results_lock = threading.Lock()
        start = threading.Barrier(8)

        def worker() -> None:
            start.wait()
            pool = ps._get_or_create_pool(cfg)
            with results_lock:
                results.append(pool)

        with patch("psycopg_pool.ConnectionPool", _FakePool):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(len(results), 8)
        self.assertEqual(len(_FakePool.instances), 1, "race created multiple pools")
        # Every worker got the SAME pool back.
        for pool in results:
            self.assertIs(pool, _FakePool.instances[0])


if __name__ == "__main__":
    unittest.main()
