from __future__ import annotations

import json
import os
import unittest
from typing import Any
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

    def test_run_launch_and_poll_use_operator_headers(self) -> None:
        target = compose_chaos_session.Target(
            context="mesh-compose",
            namespace="search",
            deployment="semantic-search",
            substrate="container",
        )
        requests: list[Any] = []

        def fake_urlopen(request: Any, timeout: float) -> _Response:
            requests.append(request)
            if len(requests) == 1:
                return _Response({"run_id": "run-1"}, status=201)
            return _Response({
                "stage": "completed",
                "status": "completed",
                "artifacts": {"decision": {"decision_type": "restart_deployment"}},
            })

        env = {
            "MESH_STACK_CHAOS_OPERATOR_ID": "chaos-launcher@example.com",
            "MESH_STACK_CHAOS_OPERATOR_ROLES": "launcher,viewer",
            "MESH_STACK_CHAOS_RUN_WAIT_SECONDS": "5",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(compose_chaos_session.urllib.request, "urlopen", side_effect=fake_urlopen):
                with mock.patch.object(compose_chaos_session.time, "monotonic", side_effect=[0.0, 0.0]):
                    result = compose_chaos_session._launch_mesh_run("http://mesh:8787", target)

        self.assertEqual(result["run_id"], "run-1")
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request.get_header("X-mesh-operator"), "chaos-launcher@example.com")
            self.assertEqual(request.get_header("X-mesh-roles"), "launcher,viewer")

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

    def test_coverage_frontier_can_bypass_high_severity_spacing_for_unproven_axes(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")
        first_high = compose_chaos_session.ChaosExperiment(
            name="first_high",
            description="",
            weight=1.0,
            severity="high",
            expected_decisions=frozenset({"restart_deployment"}),
            cooldown_seconds=0,
            capability_axes=frozenset({"axis_a"}),
        )
        second_high = compose_chaos_session.ChaosExperiment(
            name="second_high",
            description="",
            weight=1.0,
            severity="high",
            expected_decisions=frozenset({"rollback_deployment"}),
            cooldown_seconds=0,
            capability_axes=frozenset({"axis_b"}),
        )
        history = [
            compose_chaos_session.Prior(
                "first_high",
                compose_chaos_session._target_key(target),
                "high",
                0.0,
                frozenset({"axis_a"}),
                True,
            )
        ]

        with mock.patch.object(compose_chaos_session, "DEFAULT_PORTFOLIO", (first_high, second_high)):
            pick = compose_chaos_session._pick(
                compose_chaos_session.random.Random(0),
                [target],
                history,
                now=10.0,
                coverage_first=True,
            )

        self.assertIsNotNone(pick)
        self.assertEqual(pick[0].name, "second_high")

    def test_high_severity_spacing_still_blocks_repeats_after_axes_are_proven(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")
        high = compose_chaos_session.ChaosExperiment(
            name="high",
            description="",
            weight=1.0,
            severity="high",
            expected_decisions=frozenset({"restart_deployment"}),
            cooldown_seconds=0,
            capability_axes=frozenset({"axis_a"}),
        )
        history = [
            compose_chaos_session.Prior(
                "high",
                compose_chaos_session._target_key(target),
                "high",
                0.0,
                frozenset({"axis_a"}),
                True,
            )
        ]

        with mock.patch.object(compose_chaos_session, "DEFAULT_PORTFOLIO", (high,)):
            pick = compose_chaos_session._pick(
                compose_chaos_session.random.Random(0),
                [target],
                history,
                now=10.0,
                coverage_first=True,
            )

        self.assertIsNone(pick)

    def test_sre_grade_kubernetes_decisions_score_against_updated_portfolio(self) -> None:
        expectations = {
            "readiness_failure": "defer_until",
            "memory_pressure": "patch_resources",
            "config_drift": "escalate",
        }
        by_name = {experiment.name: experiment for experiment in compose_chaos_session.DEFAULT_PORTFOLIO}

        for name, decision_type in expectations.items():
            with self.subTest(name=name):
                score = compose_chaos_session._score_event(
                    by_name[name],
                    {
                        "mesh_run": {
                            "stage": "awaiting_operator",
                            "timed_out": False,
                            "decision_type": decision_type,
                        }
                    },
                )

                self.assertTrue(score["passed"])

    def test_observation_delay_uses_primitive_override_for_transients(self) -> None:
        defaulted = compose_chaos_session.ChaosExperiment(
            name="defaulted",
            description="",
            weight=1.0,
            severity="high",
            expected_decisions=frozenset(),
        )
        transient = compose_chaos_session.ChaosExperiment(
            name="transient",
            description="",
            weight=1.0,
            severity="high",
            expected_decisions=frozenset(),
            observation_delay_seconds=0.0,
        )

        self.assertEqual(compose_chaos_session._observation_delay_seconds(defaulted, 30.0), 30.0)
        self.assertEqual(compose_chaos_session._observation_delay_seconds(transient, 30.0), 0.0)

    def test_launch_mesh_run_marks_chaos_probe(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({"run_id": "run-1"}).encode()

        captured: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            raise TimeoutError("stop after launch")

        with mock.patch.object(compose_chaos_session.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(TimeoutError):
                compose_chaos_session._launch_mesh_run("http://mesh:8787", target)

        self.assertTrue(captured["payload"]["chaos_probe"])  # type: ignore[index]

    def test_session_summary_breakthrough_ready_when_all_thresholds_pass(self) -> None:
        path = compose_chaos_session.Path("/tmp/events.jsonl")
        events = []
        for experiment in compose_chaos_session.DEFAULT_PORTFOLIO:
            trigger_expected = (
                "false_positive_probe" not in experiment.tags
                and "no_action" not in experiment.expected_decisions
            )
            decision_type = (
                next(iter(sorted(experiment.expected_decisions - {"escalate"})), "escalate")
                if experiment.expected_decisions and trigger_expected
                else None
            )
            events.append(
                {
                    "experiment": experiment.name,
                    "tags": sorted(experiment.tags),
                    "capability_axes": sorted(experiment.capability_axes),
                    "expected_decisions": sorted(experiment.expected_decisions),
                    "mesh_run": {
                        "stage": "awaiting_operator" if trigger_expected else "no_trigger",
                        "timed_out": False,
                    },
                    "score": {
                        "passed": True,
                        "trigger_fired": trigger_expected,
                        "decision_type": decision_type,
                    },
                }
            )

        summary = compose_chaos_session._session_summary(path, events)

        self.assertTrue(summary["breakthrough_probe"]["ready"])
        self.assertEqual(summary["breakthrough_probe"]["status"], "breakthrough_signal")

    def test_stop_on_breakthrough_can_require_complete_axis_coverage(self) -> None:
        summary = {
            "breakthrough_probe": {"ready": True},
            "capabilities": {
                "missing_axes": ["detect_configuration_drift"],
                "failed_or_unproven_axes": [],
            },
        }

        self.assertFalse(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=True,
                require_substrate_coverage=False,
                require_multi_fault_breadth=False,
            )
        )
        self.assertTrue(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=False,
                require_substrate_coverage=False,
                require_multi_fault_breadth=False,
            )
        )

    def test_stop_on_breakthrough_allows_complete_axis_coverage(self) -> None:
        summary = {
            "breakthrough_probe": {"ready": True},
            "capabilities": {
                "missing_axes": [],
                "failed_or_unproven_axes": [],
            },
            "substrate_coverage": {
                "container": {"attempted": 1, "passed": 1, "experiments": ["crash_loop"]},
            },
            "multi_fault_coverage": {"missing_experiments": []},
        }

        self.assertTrue(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=True,
                require_substrate_coverage=True,
                require_multi_fault_breadth=True,
            )
        )

    def test_session_summary_reports_configured_substrate_coverage(self) -> None:
        path = compose_chaos_session.Path("/tmp/events.jsonl")
        events = [
            {
                "experiment": "crash_loop",
                "target": {"substrate": "container"},
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
                "experiment": "bad_image",
                "target": {"substrate": "vm"},
                "tags": [],
                "capability_axes": ["detect_image_pull_failure"],
                "expected_decisions": ["rollback_deployment"],
                "mesh_run": {"timed_out": False},
                "score": {
                    "passed": False,
                    "trigger_fired": True,
                    "decision_type": "escalate",
                },
            },
        ]

        summary = compose_chaos_session._session_summary(
            path,
            events,
            configured_substrates={"container", "vm", "baremetal"},
        )

        self.assertEqual(summary["substrate_coverage"]["container"]["attempted"], 1)
        self.assertEqual(summary["substrate_coverage"]["container"]["passed"], 1)
        self.assertEqual(summary["substrate_coverage"]["container"]["experiments"], ["crash_loop"])
        self.assertEqual(summary["substrate_coverage"]["vm"]["attempted"], 1)
        self.assertEqual(summary["substrate_coverage"]["vm"]["passed"], 0)
        self.assertEqual(summary["substrate_coverage"]["baremetal"]["attempted"], 0)

    def test_stop_on_breakthrough_requires_substrate_coverage_when_enabled(self) -> None:
        summary = {
            "breakthrough_probe": {"ready": True},
            "capabilities": {
                "missing_axes": [],
                "failed_or_unproven_axes": [],
            },
            "substrate_coverage": {
                "container": {"attempted": 1, "passed": 1, "experiments": ["crash_loop"]},
                "vm": {"attempted": 1, "passed": 1, "experiments": ["bad_image"]},
                "baremetal": {"attempted": 0, "passed": 0, "experiments": []},
            },
        }

        self.assertFalse(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=True,
                require_substrate_coverage=True,
                require_multi_fault_breadth=False,
            )
        )
        self.assertFalse(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=False,
                require_substrate_coverage=True,
                require_multi_fault_breadth=False,
            )
        )
        self.assertTrue(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=True,
                require_substrate_coverage=False,
                require_multi_fault_breadth=False,
            )
        )

    def test_stop_on_breakthrough_requires_multi_fault_breadth_when_enabled(self) -> None:
        summary = {
            "breakthrough_probe": {"ready": True},
            "capabilities": {
                "missing_axes": [],
                "failed_or_unproven_axes": [],
            },
            "substrate_coverage": {
                "container": {"attempted": 1, "passed": 1, "experiments": ["crash_loop"]},
            },
            "multi_fault_coverage": {
                "missing_experiments": ["bad_image_untrusted_metric"],
            },
        }

        self.assertFalse(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=True,
                require_substrate_coverage=True,
                require_multi_fault_breadth=True,
            )
        )
        self.assertTrue(
            compose_chaos_session._should_stop_on_breakthrough(
                summary,
                require_full_axis_coverage=True,
                require_substrate_coverage=True,
                require_multi_fault_breadth=False,
            )
        )

    def test_coverage_frontier_prefers_uncovered_substrate_when_axes_match(self) -> None:
        container = compose_chaos_session.Target("ctx-container", "ns", "svc", "container")
        vm = compose_chaos_session.Target("ctx-vm", "ns", "svc", "vm")
        experiment = compose_chaos_session.ChaosExperiment(
            name="readiness_failure",
            description="",
            weight=1.0,
            severity="medium",
            expected_decisions=frozenset({"defer_until"}),
            cooldown_seconds=0,
            capability_axes=frozenset({"detect_readiness_degradation"}),
        )
        history = [
            compose_chaos_session.Prior(
                "crash_loop",
                compose_chaos_session._target_key(container),
                "high",
                0.0,
                frozenset({"detect_crash_loop"}),
                True,
                "container",
            )
        ]

        with mock.patch.object(compose_chaos_session, "DEFAULT_PORTFOLIO", (experiment,)):
            pick = compose_chaos_session._pick(
                compose_chaos_session.random.Random(0),
                [container, vm],
                history,
                now=120.0,
                coverage_first=True,
            )

        self.assertIsNotNone(pick)
        self.assertEqual(pick[1].substrate, "vm")

    def test_wait_for_target_ready_requires_desired_running_ready_pods(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")

        class FakeInjector:
            def _kubectl_json(self, *args: str) -> dict[str, object]:
                return {
                    "spec": {"replicas": 2},
                    "status": {
                        "replicas": 2,
                        "updatedReplicas": 2,
                        "readyReplicas": 2,
                        "availableReplicas": 2,
                    },
                }

            def _list_pods(self, deployment: str, namespace: str) -> list[dict[str, Any]]:
                return [
                    {
                        "name": "p1",
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                    {
                        "name": "p2",
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                ]

        result = compose_chaos_session._wait_for_target_ready(FakeInjector(), target, timeout_seconds=1)

        self.assertEqual(result["desired_replicas"], 2)
        self.assertEqual(result["updated_replicas"], 2)
        self.assertEqual(result["running_ready_pods"], 2)

    def test_wait_for_target_ready_rejects_dirty_rollout_with_ready_old_pods(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")

        class FakeInjector:
            def _kubectl_json(self, *args: str) -> dict[str, object]:
                return {
                    "spec": {"replicas": 3},
                    "status": {
                        "replicas": 4,
                        "updatedReplicas": 1,
                        "readyReplicas": 3,
                        "availableReplicas": 3,
                    },
                }

            def _list_pods(self, deployment: str, namespace: str) -> list[dict[str, Any]]:
                return [
                    {
                        "name": f"old-{index}",
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                    }
                    for index in range(3)
                ] + [
                    {
                        "name": "new-broken",
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "False"}],
                    }
                ]

        with mock.patch.object(compose_chaos_session.time, "sleep", return_value=None):
            with mock.patch.object(compose_chaos_session.time, "monotonic", side_effect=[0.0, 2.0]):
                with self.assertRaises(compose_chaos_session.ChaosError):
                    compose_chaos_session._wait_for_target_ready(
                        FakeInjector(),
                        target,
                        timeout_seconds=1,
                    )

    def test_wait_for_target_ready_rejects_extra_unready_pod_even_when_status_counts_match(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")

        class FakeInjector:
            def _kubectl_json(self, *args: str) -> dict[str, object]:
                return {
                    "spec": {"replicas": 3},
                    "status": {
                        "replicas": 3,
                        "updatedReplicas": 3,
                        "readyReplicas": 3,
                        "availableReplicas": 3,
                    },
                }

            def _list_pods(self, deployment: str, namespace: str) -> list[dict[str, Any]]:
                return [
                    {
                        "name": f"ready-{index}",
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                    }
                    for index in range(3)
                ] + [
                    {
                        "name": "extra-broken",
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "False"}],
                    }
                ]

        with mock.patch.object(compose_chaos_session.time, "sleep", return_value=None):
            with mock.patch.object(compose_chaos_session.time, "monotonic", side_effect=[0.0, 2.0]):
                with self.assertRaises(compose_chaos_session.ChaosError):
                    compose_chaos_session._wait_for_target_ready(
                        FakeInjector(),
                        target,
                        timeout_seconds=1,
                    )

    def test_wait_for_target_ready_rejects_zero_running_pods(self) -> None:
        target = compose_chaos_session.Target("ctx", "ns", "svc", "container")

        class FakeInjector:
            def _kubectl_json(self, *args: str) -> dict[str, object]:
                return {
                    "spec": {"replicas": 3},
                    "status": {
                        "replicas": 3,
                        "updatedReplicas": 3,
                        "readyReplicas": 0,
                        "availableReplicas": 0,
                    },
                }

            def _list_pods(self, deployment: str, namespace: str) -> list[dict[str, object]]:
                return []

        with mock.patch.object(compose_chaos_session.time, "sleep", return_value=None):
            with mock.patch.object(compose_chaos_session.time, "monotonic", side_effect=[0.0, 2.0]):
                with self.assertRaises(compose_chaos_session.ChaosError):
                    compose_chaos_session._wait_for_target_ready(
                        FakeInjector(),
                        target,
                        timeout_seconds=1,
                    )


if __name__ == "__main__":
    unittest.main()
