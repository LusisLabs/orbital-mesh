from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_simulation_matrix import _ingest_override_replay, _randomize_signal, _summarize, _write_override_replay
from services.orchestrator.reconciliation import reconcile_agent_tasks
from services.orchestrator.service_agents import ServiceAgentRegistry
from services.simulation import SimulationService
from shared.mesh_runtime import RuntimeConfig, validate_payload
from shared.mesh_runtime.agent_workers import build_agent_attempt, build_agent_task
from shared.mesh_runtime.benchmarking import dataset_row, score_run
from shared.mesh_runtime.rule_suggestions import OverrideLearningStore


class AiSrePlatformSliceTests(unittest.TestCase):
    def test_simulation_catalog_is_schema_valid_and_allowlist_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfig(
                state_directory=tmp,
                simulation_enabled=True,
                simulation_context_allowlist=("mesh-compose",),
            )
            svc = SimulationService(config)
            scenarios = svc.list_scenarios()
            self.assertGreaterEqual(len(scenarios), 10)
            validate_payload("simulation-scenario.schema.json", scenarios[0])
            _scenario, payload = svc.build_run_payload("k8s_crashloop_restart", {})
            self.assertEqual(payload["scenario_key"], "simulation:k8s_crashloop_restart")
            self.assertEqual(payload["simulation_context"]["sandbox"]["kube_context"], "mesh-compose")
            families = {scenario["scenario_family"] for scenario in scenarios}
            self.assertIn("kubernetes", families)
            self.assertIn("networking", families)
            self.assertIn("database", families)

    def test_simulation_run_rejects_missing_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = SimulationService(RuntimeConfig(state_directory=tmp, simulation_enabled=True))
            with self.assertRaises(PermissionError):
                svc.build_run_payload("k8s_crashloop_restart", {})

    def test_service_agent_registry_routes_by_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.json"
            path.write_text(
                json.dumps(
                    {
                        "agents": [
                            {
                                "service": "search",
                                "scope": {"deployments": ["semantic-*"], "namespaces": ["search"]},
                                "preferred_lanes": ["hermes", "goose"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = ServiceAgentRegistry(str(path))
            routed = registry.route({"related_context": {"deployment_name": "semantic-search", "namespace": "search"}})
            self.assertTrue(routed["matched"])
            self.assertEqual(routed["agent"]["service"], "search")
            self.assertEqual(routed["agent"]["preferred_lanes"], ["hermes", "goose"])

    def test_reconciliation_preserves_losing_attempts(self) -> None:
        task = build_agent_task(run_id="run_1", kind="review", agents=["hermes", "goose"])
        a1 = build_agent_attempt(
            task_id=task.task_id,
            run_id="run_1",
            agent="hermes",
            adapter="native_contract",
            status="completed",
            summary="review",
            recommended_action="execute",
        )
        a2 = build_agent_attempt(
            task_id=task.task_id,
            run_id="run_1",
            agent="goose",
            adapter="native_contract",
            status="completed",
            summary="review",
            recommended_action="human_review",
            risk_flags=["policy_gap"],
        )
        task.attempts = [a1, a2]
        result = reconcile_agent_tasks([task])
        validate_payload("reconciliation.schema.json", result)
        self.assertTrue(result["disagreement"])
        self.assertIn(a2.attempt_id, result["losing_attempt_ids"])
        self.assertEqual(set(result["all_attempt_ids"]), {a1.attempt_id, a2.attempt_id})

    def test_benchmark_score_and_dataset_row_are_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = SimulationService(
                RuntimeConfig(
                    state_directory=tmp,
                    simulation_enabled=True,
                    simulation_context_allowlist=("mesh-compose",),
                )
            ).get_scenario("k8s_crashloop_restart")
            assert scenario is not None
            session = {
                "run_id": "run_1",
                "scenario_key": "simulation:k8s_crashloop_restart",
                "stage": "completed",
                "status": "completed",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "artifacts": {
                    "simulation_context": {"scenario_id": "k8s_crashloop_restart"},
                    "decision": {"decision_type": "investigate_and_patch"},
                    "evaluation": {"final_recommendation": "execute", "blocking_reasons": []},
                    "feedback": {"outcome": "successful"},
                    "agent_tasks": [],
                },
            }
            events = [{"event_type": "trigger_ready"}]
            record = score_run(scenario=scenario, session=session, events=events)
            validate_payload("benchmark-record.schema.json", record.to_dict())
            row = dataset_row(scenario=scenario, session=session, events=events, merkle={}, record=record)
            self.assertTrue(record.passed)
            self.assertEqual(row["decision"]["decision_type"], "investigate_and_patch")
            self.assertEqual(record.dimensions["scenario_family"], "kubernetes")
            self.assertIn("model_profile", record.dimensions)

    def test_benchmark_wrong_expected_decision_is_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenario = SimulationService(
                RuntimeConfig(
                    state_directory=tmp,
                    simulation_enabled=True,
                    simulation_context_allowlist=("mesh-compose",),
                )
            ).get_scenario("k8s_crashloop_restart")
            assert scenario is not None
            session = {
                "run_id": "run_2",
                "stage": "completed",
                "status": "completed",
                "artifacts": {
                    "decision": {"decision_type": "restart_deployment"},
                    "evaluation": {"final_recommendation": "execute", "blocking_reasons": []},
                    "feedback": {"outcome": "successful"},
                    "agent_tasks": [],
                },
            }
            record = score_run(scenario=scenario, session=session, events=[{"event_type": "trigger_ready"}])
            self.assertFalse(record.passed)
            self.assertIn("decision_mismatch", record.dimensions["hard_failures"])

    def test_benchmark_no_trigger_satisfies_no_action_control(self) -> None:
        scenario = SimulationService(
            RuntimeConfig(
                simulation_enabled=True,
                simulation_context_allowlist=("mesh-compose",),
            )
        ).get_scenario("feature_flag_low_confidence_no_action")
        assert scenario is not None
        session = {
            "run_id": "run_3",
            "stage": "no_trigger",
            "status": "completed",
            "artifacts": {"agent_tasks": []},
        }
        record = score_run(scenario=scenario, session=session, events=[{"event_type": "no_trigger"}])
        self.assertTrue(record.passed)
        self.assertTrue(record.dimensions["decision_match"])
        self.assertTrue(record.dimensions["outcome_match"])

    def test_benchmark_approval_pause_counts_as_correct_pause(self) -> None:
        scenario = SimulationService(
            RuntimeConfig(
                simulation_enabled=True,
                simulation_context_allowlist=("mesh-compose",),
            )
        ).get_scenario("feature_flag_missing_credentials_escalate")
        assert scenario is not None
        session = {
            "run_id": "run_4",
            "stage": "awaiting_operator",
            "status": "awaiting_operator",
            "artifacts": {
                "decision": {"decision_type": "escalate"},
                "evaluation": {
                    "final_recommendation": "needs_human",
                    "blocking_reasons": ["decision routes to human review", "risk level is high"],
                },
                "agent_tasks": [{"task_id": "task_1"}],
                "reconciliation": {"disagreement": False},
            },
        }
        record = score_run(scenario=scenario, session=session, events=[{"event_type": "trigger_ready"}])
        self.assertTrue(record.passed)
        self.assertTrue(record.dimensions["correct_pause_pass"])
        self.assertEqual(record.dimensions["blocker_classes"], ["human_review", "risk"])

    def test_randomized_signal_is_seed_deterministic(self) -> None:
        signal_a = {
            "signal_type": "otel_metric_regression",
            "metric_regression": {"baseline_value": 10.0, "observed_value": 20.0},
            "resource_attributes": {},
        }
        signal_b = json.loads(json.dumps(signal_a))
        _randomize_signal(signal_a, seed=7)
        _randomize_signal(signal_b, seed=7)
        self.assertEqual(signal_a, signal_b)
        self.assertNotEqual(signal_a["metric_regression"]["observed_value"], 20.0)
        self.assertGreaterEqual(signal_a["metric_regression"]["delta_pct"], 25.0)

    def test_override_replay_written_for_blocked_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_override_replay(
                out,
                [
                    {
                        "run_id": "run_5",
                        "scenario_id": "scenario",
                        "decision_type": "escalate",
                        "stage": "awaiting_operator",
                        "benchmark": {"dimensions": {"blocker_classes": ["risk"]}},
                    }
                ],
            )
            lines = out.joinpath("override-replay.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["operator_action"], "reject_or_escalate")

    def test_override_replay_ingests_rule_learning_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = [
                {
                    "run_id": f"run_{idx}",
                    "scenario_id": "otel_queue_lag_scale",
                    "scenario_family": "queue",
                    "decision_type": "scale_deployment",
                    "stage": "awaiting_operator",
                    "benchmark": {
                        "dimensions": {
                            "blocker_classes": ["confidence"],
                            "blocker_gate_tuning": {"operator_replay": "approve_with_evidence"},
                        }
                    },
                }
                for idx in range(2)
            ]
            _write_override_replay(out, rows)
            payload = _ingest_override_replay(out, out / "learning-state")
            store = OverrideLearningStore(out / "learning-state")
            self.assertEqual(payload["imported_overrides"], 2)
            self.assertEqual(len(store.list_overrides(max_age_days=None)), 2)
            self.assertGreaterEqual(payload["suggestion_count"], 1)

    def test_summary_reports_scenario_family_and_model_profile(self) -> None:
        summary = _summarize(
            [
                {
                    "scenario_id": "otel_queue_lag_scale",
                    "scenario_family": "queue",
                    "stage": "completed",
                    "decision_type": "scale_deployment",
                    "elapsed_ms": 10,
                    "benchmark": {
                        "passed": True,
                        "score": 0.9,
                        "dimensions": {
                            "blocker_classes": [],
                            "model_profile": {
                                "evaluation_mode": "native",
                                "orchestration_mode": "native",
                                "agent_fabric_mode": "native",
                            },
                        },
                    },
                    "reconciliation": {},
                }
            ]
        )
        self.assertEqual(summary["scenario_family_report"]["queue"]["pass_rate"], 1.0)
        self.assertEqual(next(iter(summary["model_profile_matrix"].values()))["avg_score"], 0.9)


if __name__ == "__main__":
    unittest.main()
