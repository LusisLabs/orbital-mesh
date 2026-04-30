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

    def test_session_summary_reports_breakthrough_probe_and_capability_gaps(self) -> None:
        path = compose_chaos_session.Path("/tmp/events.jsonl")
        events = [
            {
                "experiment": "crash_loop",
                "tags": [],
                "capability_axes": ["detect_crash_loop"],
                "expected_decisions": ["restart_deployment"],
                "mesh_run": {"timed_out": False},
                "score": {
                    "passed": True,
                    "trigger_fired": True,
                    "decision_type": "restart_deployment",
                },
            },
            {
                "experiment": "pod_kill_one",
                "tags": ["false_positive_probe"],
                "capability_axes": ["avoid_false_positive_remediation"],
                "expected_decisions": [],
                "mesh_run": {"timed_out": False},
                "score": {
                    "passed": True,
                    "trigger_fired": False,
                    "decision_type": None,
                },
            },
        ]

        summary = compose_chaos_session._session_summary(path, events)

        self.assertEqual(summary["schema_version"], "mesh.compose_chaos_summary.v1")
        self.assertEqual(summary["experiments_total"], 2)
        self.assertEqual(summary["experiments_passed"], 2)
        self.assertEqual(summary["metrics"]["detection_rate"], 1.0)
        self.assertEqual(summary["metrics"]["false_positive_rate"], 0.0)
        self.assertEqual(summary["breakthrough_probe"]["status"], "below_threshold")
        self.assertIn("failed_or_unproven_axes", summary["capabilities"])

    def test_session_summary_detection_rate_excludes_no_action_controls(self) -> None:
        path = compose_chaos_session.Path("/tmp/events.jsonl")
        events = [
            {
                "experiment": "scale_to_zero",
                "tags": [],
                "capability_axes": ["detect_intentional_zero_replicas"],
                "expected_decisions": ["escalate", "restart_deployment", "no_action"],
                "mesh_run": {"stage": "no_trigger", "timed_out": False},
                "score": {
                    "passed": True,
                    "trigger_fired": False,
                    "decision_type": None,
                },
            },
            {
                "experiment": "crash_loop",
                "tags": [],
                "capability_axes": ["detect_crash_loop"],
                "expected_decisions": ["restart_deployment"],
                "mesh_run": {"stage": "awaiting_operator", "timed_out": False},
                "score": {
                    "passed": True,
                    "trigger_fired": True,
                    "decision_type": "restart_deployment",
                },
            },
        ]

        summary = compose_chaos_session._session_summary(path, events)

        self.assertEqual(summary["metrics"]["detection_rate"], 1.0)

    def test_score_event_accepts_no_trigger_for_false_positive_probe(self) -> None:
        experiment = compose_chaos_session.ChaosExperiment(
            name="pod_kill_one",
            description="",
            weight=1.0,
            severity="low",
            expected_decisions=frozenset(),
            tags=frozenset({"false_positive_probe"}),
            capability_axes=frozenset({"avoid_false_positive_remediation"}),
        )
        event = {"mesh_run": {"stage": "no_trigger", "timed_out": False}}

        score = compose_chaos_session._score_event(experiment, event)

        self.assertTrue(score["passed"])
        self.assertFalse(score["trigger_fired"])

    def test_pick_uses_coverage_frontier_before_weighted_repeats(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")
        covered = compose_chaos_session.ChaosExperiment(
            name="covered",
            description="",
            weight=99.0,
            severity="low",
            expected_decisions=frozenset(),
            cooldown_seconds=0,
            capability_axes=frozenset({"axis_a"}),
        )
        uncovered = compose_chaos_session.ChaosExperiment(
            name="uncovered",
            description="",
            weight=1.0,
            severity="low",
            expected_decisions=frozenset(),
            cooldown_seconds=0,
            capability_axes=frozenset({"axis_b"}),
        )
        history = [
            compose_chaos_session.Prior(
                "covered",
                compose_chaos_session._target_key(target),
                "low",
                0.0,
                frozenset({"axis_a"}),
                True,
            )
        ]

        with mock.patch.object(compose_chaos_session, "DEFAULT_PORTFOLIO", (covered, uncovered)):
            pick = compose_chaos_session._pick(
                compose_chaos_session.random.Random(0),
                [target],
                history,
                now=1.0,
            )

        self.assertIsNotNone(pick)
        self.assertEqual(pick[0].name, "uncovered")

    def test_pick_can_disable_coverage_first_for_weighted_replay(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")
        covered = compose_chaos_session.ChaosExperiment(
            name="covered",
            description="",
            weight=99.0,
            severity="low",
            expected_decisions=frozenset(),
            cooldown_seconds=0,
            capability_axes=frozenset({"axis_a"}),
        )
        uncovered = compose_chaos_session.ChaosExperiment(
            name="uncovered",
            description="",
            weight=0.001,
            severity="low",
            expected_decisions=frozenset(),
            cooldown_seconds=0,
            capability_axes=frozenset({"axis_b"}),
        )
        history = [
            compose_chaos_session.Prior(
                "covered",
                compose_chaos_session._target_key(target),
                "low",
                0.0,
                frozenset({"axis_a"}),
                True,
            )
        ]

        with mock.patch.object(compose_chaos_session, "DEFAULT_PORTFOLIO", (covered, uncovered)):
            pick = compose_chaos_session._pick(
                compose_chaos_session.random.Random(0),
                [target],
                history,
                now=1.0,
                coverage_first=False,
            )

        self.assertIsNotNone(pick)
        self.assertEqual(pick[0].name, "covered")


if __name__ == "__main__":
    unittest.main()
