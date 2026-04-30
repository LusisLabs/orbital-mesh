from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import breakthrough_evidence_bundle as bundle


class BreakthroughEvidenceBundleTests(unittest.TestCase):
    def test_compose_replay_matches_recorded_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            event = {
                "experiment": "config_drift",
                "mesh_run": {"stage": "awaiting_operator", "decision_type": "escalate"},
                "score": {
                    "passed": True,
                    "reason": None,
                    "trigger_fired": True,
                    "decision_type": "escalate",
                },
            }
            events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

            report = bundle.replay_compose_events(events_path)

        self.assertTrue(report["passed"])
        self.assertEqual(report["events_total"], 1)
        self.assertEqual(report["events_passed"], 1)

    def test_config_drift_replay_rejects_wrong_proof_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "proof.json"
            proof_path.write_text(json.dumps({"experiment": "crash_loop"}), encoding="utf-8")

            report = bundle.replay_config_drift_proof(proof_path)

        self.assertFalse(report["passed"])
        self.assertEqual(report["reason"], "proof_is_not_config_drift")

    def test_node_replay_compares_recorded_pipeline_signature(self) -> None:
        probe = bundle.node_session.NodeProbe(
            name="probe",
            description="",
            signal_payload={"signal_type": "synthetic"},
            expected_decisions=frozenset({"escalate"}),
            capability_axes=frozenset({"axis"}),
        )
        event = {
            "probe": "probe",
            "capability_axes": ["axis"],
            "mesh_run": {
                "trigger_type": "synthetic_trigger",
                "decision_type": "escalate",
                "execution_system": "incident_service",
                "execution_action": "open_incident",
                "autonomy_tier": "escalated",
            },
            "score": {
                "passed": True,
                "reason": None,
                "decision_type": "escalate",
            },
        }
        pipeline_result = {
            "trigger": {"trigger_type": "synthetic_trigger"},
            "decision": {
                "decision_type": "escalate",
                "execution_plan": {
                    "system": "incident_service",
                    "action": "open_incident",
                },
                "autonomy_tier": "escalated",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            with mock.patch.object(bundle.node_session, "default_probes", return_value=(probe,)):
                with mock.patch.object(bundle.FirstSlicePipeline, "run", return_value=pipeline_result):
                    report = bundle.replay_node_events(events_path)

        self.assertTrue(report["passed"])
        self.assertEqual(report["events_total"], 1)
        self.assertEqual(report["events_passed"], 1)

    def test_build_bundle_marks_ready_when_summaries_and_replays_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            compose_events = repo / "compose-events.jsonl"
            compose_summary = repo / "compose-summary.json"
            config_proof = repo / "config-proof.json"
            node_events = repo / "node-events.jsonl"
            node_summary = repo / "node-summary.json"
            for path in (compose_events, node_events):
                path.write_text("{}\n", encoding="utf-8")
            for path, schema in (
                (compose_summary, "mesh.compose_chaos_summary.v1"),
                (node_summary, "mesh.production_node_breakthrough_summary.v1"),
            ):
                path.write_text(
                    json.dumps({
                        "schema_version": schema,
                        "breakthrough_probe": {"ready": True, "status": "breakthrough_signal"},
                        "metrics": {"correct_decision_rate": 1.0},
                    }),
                    encoding="utf-8",
                )
            config_proof.write_text(
                json.dumps({"experiment": "config_drift", "score": {"passed": True}}),
                encoding="utf-8",
            )
            evidence = [
                bundle.EvidenceInput("compose_summary", compose_summary),
                bundle.EvidenceInput("compose_events", compose_events),
                bundle.EvidenceInput("config_drift_proof", config_proof),
                bundle.EvidenceInput("node_summary", node_summary),
                bundle.EvidenceInput("node_events", node_events),
            ]
            passing_report = {"passed": True}
            with mock.patch.object(bundle, "replay_compose_events", return_value=passing_report):
                with mock.patch.object(bundle, "replay_config_drift_proof", return_value=passing_report):
                    with mock.patch.object(bundle, "replay_node_events", return_value=passing_report):
                        result = bundle.build_bundle(repo, evidence)

        self.assertTrue(result["breakthrough_proof"]["ready"])
        self.assertEqual(result["breakthrough_proof"]["status"], "regression_protected_breakthrough")
        self.assertRegex(result["bundle_sha256"], r"^[0-9a-f]{64}$")

    def test_validation_command_failure_blocks_ready_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            compose_events = repo / "compose-events.jsonl"
            compose_summary = repo / "compose-summary.json"
            config_proof = repo / "config-proof.json"
            node_events = repo / "node-events.jsonl"
            node_summary = repo / "node-summary.json"
            compose_events.write_text("{}\n", encoding="utf-8")
            node_events.write_text("{}\n", encoding="utf-8")
            for path, schema in (
                (compose_summary, "mesh.compose_chaos_summary.v1"),
                (node_summary, "mesh.production_node_breakthrough_summary.v1"),
            ):
                path.write_text(
                    json.dumps({
                        "schema_version": schema,
                        "breakthrough_probe": {"ready": True, "status": "breakthrough_signal"},
                        "metrics": {},
                    }),
                    encoding="utf-8",
                )
            config_proof.write_text(json.dumps({"experiment": "config_drift"}), encoding="utf-8")
            evidence = [
                bundle.EvidenceInput("compose_summary", compose_summary),
                bundle.EvidenceInput("compose_events", compose_events),
                bundle.EvidenceInput("config_drift_proof", config_proof),
                bundle.EvidenceInput("node_summary", node_summary),
                bundle.EvidenceInput("node_events", node_events),
            ]
            passing_report = {"passed": True}
            with mock.patch.object(bundle, "replay_compose_events", return_value=passing_report):
                with mock.patch.object(bundle, "replay_config_drift_proof", return_value=passing_report):
                    with mock.patch.object(bundle, "replay_node_events", return_value=passing_report):
                        result = bundle.build_bundle(
                            repo,
                            evidence,
                            validation_commands=[["python3", "-c", "raise SystemExit(7)"]],
                        )

        self.assertFalse(result["breakthrough_proof"]["ready"])
        self.assertEqual(result["validation_commands"][0]["exit_code"], 7)

    def test_default_validation_commands_include_focused_strict_mypy(self) -> None:
        commands = bundle._validation_commands([])  # noqa: SLF001 - validates CLI defaults.

        mypy_commands = [command for command in commands if "mypy" in command]
        self.assertEqual(len(mypy_commands), 1)
        self.assertIn("--strict", mypy_commands[0])
        self.assertIn("scripts/breakthrough_evidence_bundle.py", mypy_commands[0])
        self.assertIn("scripts/production_node_breakthrough_session.py", mypy_commands[0])
        self.assertIn("tests/test_breakthrough_evidence_bundle.py", mypy_commands[0])
        self.assertIn("tests/test_production_node_breakthrough_session.py", mypy_commands[0])


if __name__ == "__main__":
    unittest.main()
