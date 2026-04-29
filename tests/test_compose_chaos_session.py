from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from scripts import compose_chaos_session


class _Response:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class ComposeChaosRunPollingTests(unittest.TestCase):
    def test_run_wait_timeout_returns_stage_and_elapsed_metadata(self) -> None:
        target = compose_chaos_session.Target(
            context="mesh-compose",
            namespace="search",
            deployment="semantic-search",
            substrate="container",
        )
        responses = [
            _Response({"run_id": "run-1"}),
            _Response({"stage": "evaluating", "status": "running"}),
            _Response({"stage": "evaluating", "status": "running"}),
        ]
        env = {
            "MESH_STACK_CHAOS_RUN_WAIT_SECONDS": "1",
            "MESH_STACK_CHAOS_RUN_PROGRESS_GRACE_SECONDS": "0",
            "MESH_STACK_CHAOS_RUN_MAX_WAIT_SECONDS": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(compose_chaos_session.urllib.request, "urlopen", side_effect=responses):
                with mock.patch.object(compose_chaos_session.time, "sleep", return_value=None):
                    with mock.patch.object(compose_chaos_session.time, "monotonic", side_effect=[0.0, 0.0, 2.0]):
                        result = compose_chaos_session._launch_mesh_run("http://mesh:8787", target)

        self.assertEqual(result["run_id"], "run-1")
        self.assertEqual(result["stage"], "evaluating")
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["wait_elapsed_seconds"], 2.0)
        self.assertEqual(result["seconds_since_progress"], 2.0)

    def test_long_running_stages_receive_extended_progress_grace(self) -> None:
        target = compose_chaos_session.Target(
            context="mesh-compose",
            namespace="search",
            deployment="semantic-search",
            substrate="container",
        )
        responses = [
            _Response({"run_id": "run-1"}),
            _Response({"stage": "evaluation_ready", "status": "running"}),
            _Response({
                "stage": "awaiting_operator",
                "status": "awaiting_operator",
                "artifacts": {"decision": {"decision_type": "rollback_deployment"}},
            }),
        ]
        env = {
            "MESH_STACK_CHAOS_RUN_WAIT_SECONDS": "1",
            "MESH_STACK_CHAOS_RUN_PROGRESS_GRACE_SECONDS": "0",
            "MESH_STACK_CHAOS_RUN_STAGE_GRACE_SECONDS": "10",
            "MESH_STACK_CHAOS_RUN_MAX_WAIT_SECONDS": "20",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(compose_chaos_session.urllib.request, "urlopen", side_effect=responses):
                with mock.patch.object(compose_chaos_session.time, "sleep", return_value=None):
                    with mock.patch.object(compose_chaos_session.time, "monotonic", side_effect=[0.0, 0.0, 2.0]):
                        result = compose_chaos_session._launch_mesh_run("http://mesh:8787", target)

        self.assertEqual(result["run_id"], "run-1")
        self.assertEqual(result["stage"], "awaiting_operator")
        self.assertEqual(result["status"], "awaiting_operator")
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["decision_type"], "rollback_deployment")


if __name__ == "__main__":
    unittest.main()
