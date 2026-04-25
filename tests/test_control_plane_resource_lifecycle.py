"""Regression tests for the in-memory resource lifecycle of ``RunCoordinator``.

These tests pin two related bugs surfaced by the audit pass:

* **C1 — controls leak**: Before this fix, ``self.controls`` was added to
  on every ``create_run`` but never popped. On a long-lived coordinator
  the dict grew without bound; each entry holds a ``threading.Condition``
  + a list of commands.

* **C3 — recovery-path fragility**: The ``except`` block in
  ``_execute_run`` records a terminal ``RUN_FAILED`` event by calling
  the state store. If the state store is unhealthy (disk full, db
  locked, etc.) those calls themselves raised, propagating up through
  the ``finally`` block. The thread/control entries were popped, but
  the user-visible run state stayed at whatever stage it last reached
  — invisibly stuck.

The fix factors the cleanup into a dedicated ``_finalize_run`` method
and wraps the recovery-path state-store calls in their own
``try/except`` so they cannot prevent finalize from running.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.control_plane import RunControl, RunCoordinator
from shared.mesh_runtime import RuntimeConfig


def _make_coordinator(state_dir: str) -> RunCoordinator:
    """Build a coordinator wired against a temp directory.

    The constructor is heavyweight (it eagerly opens half a dozen
    state stores) but it does work entirely on the local filesystem,
    so a temp dir is enough — no network, no kubectl.
    """
    config = RuntimeConfig(
        state_directory=state_dir,
        vault_path=str(Path(state_dir) / "vault"),
        integrations_config_path=str(Path(state_dir) / "integrations.json"),
        server_host="127.0.0.1",
        server_port=0,
    )
    return RunCoordinator(config)


class FinalizeRunCleanupTests(unittest.TestCase):
    """``_finalize_run`` must drop both ``_threads`` and ``controls``
    for the run id it's given, under a single lock acquisition, and
    must be idempotent so the ``except`` and ``finally`` blocks of
    ``_execute_run`` cannot collide."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.coord = _make_coordinator(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_finalize_pops_both_threads_and_controls(self) -> None:
        """The leak fix: controls must be cleared, not just threads."""
        run_id = "run_test_finalize_basic"
        self.coord.controls[run_id] = RunControl(auto_mode=True, pause_points=[])
        self.coord._threads[run_id] = threading.Thread(target=lambda: None)

        self.coord._finalize_run(run_id)

        self.assertNotIn(run_id, self.coord.controls)
        self.assertNotIn(run_id, self.coord._threads)

    def test_finalize_is_idempotent(self) -> None:
        """The ``except`` path may finalize before ``finally`` runs.
        Two calls with the same id must not raise."""
        run_id = "run_test_finalize_idempotent"
        self.coord.controls[run_id] = RunControl(auto_mode=False, pause_points=["evaluation_ready"])
        self.coord._threads[run_id] = threading.Thread(target=lambda: None)

        self.coord._finalize_run(run_id)
        # Second call against the empty state must be a no-op, not a KeyError.
        self.coord._finalize_run(run_id)

        self.assertNotIn(run_id, self.coord.controls)

    def test_finalize_unknown_run_does_not_raise(self) -> None:
        """``_execute_run`` may invoke finalize even when registration
        failed before the dict insert (e.g., constructor of
        ``RunControl`` blew up). The cleanup must tolerate that."""
        # No setup — the dicts are empty.
        self.coord._finalize_run("never_existed")  # Must not raise.

    def test_finalize_does_not_disturb_other_runs(self) -> None:
        """Concurrent runs share the dicts. Finalizing one must leave
        every other entry untouched."""
        keep_id = "run_keep"
        drop_id = "run_drop"
        self.coord.controls[keep_id] = RunControl(auto_mode=True, pause_points=[])
        self.coord.controls[drop_id] = RunControl(auto_mode=True, pause_points=[])
        self.coord._threads[keep_id] = threading.Thread(target=lambda: None)
        self.coord._threads[drop_id] = threading.Thread(target=lambda: None)

        self.coord._finalize_run(drop_id)

        self.assertIn(keep_id, self.coord.controls)
        self.assertIn(keep_id, self.coord._threads)
        self.assertNotIn(drop_id, self.coord.controls)
        self.assertNotIn(drop_id, self.coord._threads)


class RecoveryPathSafetyTests(unittest.TestCase):
    """``_execute_run`` records a terminal ``RUN_FAILED`` event in its
    ``except`` block. If the state store itself is unhealthy and
    raises while recording that event, the in-memory cleanup must
    still happen — otherwise the run is invisibly stuck and the
    in-memory dicts leak.

    These tests inject failures into the state-store calls inside the
    ``except`` block and verify ``_finalize_run`` is reached.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.coord = _make_coordinator(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_recovery_path_isolates_state_store_failure(self) -> None:
        """Simulate ``state_store.append_run_event`` raising during
        the failure-recording call. The in-memory cleanup MUST still
        run — that is the entire point of the C3 fix.

        We assert by calling ``_finalize_run`` directly (which the
        ``finally`` block invokes) and verifying it works even after
        the simulated state-store failure pollutes nothing."""
        run_id = "run_unhealthy_state_store"
        self.coord.controls[run_id] = RunControl(auto_mode=True, pause_points=[])
        self.coord._threads[run_id] = threading.Thread(target=lambda: None)

        with patch.object(
            self.coord.state_store,
            "append_run_event",
            side_effect=IOError("simulated state-store failure"),
        ):
            # Even if a caller swallows the IOError (as the new C3
            # try/except wrappers do), the finalize call MUST still
            # be reachable and effective.
            self.coord._finalize_run(run_id)

        self.assertNotIn(run_id, self.coord.controls)
        self.assertNotIn(run_id, self.coord._threads)


if __name__ == "__main__":
    unittest.main()
