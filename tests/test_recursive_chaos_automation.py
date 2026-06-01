from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from scripts import run_recursive_chaos_automation as automation
from scripts import run_recursive_chaos_sandbox_execution as sandbox_execution
from shared.mesh_runtime.recursive_chaos_intelligence import (
    build_recursive_chaos_feedback_gate,
    build_recursive_chaos_intelligence_score,
    validate_recursive_chaos_automation_summary,
)


class RecursiveChaosAutomationTests(unittest.TestCase):
    def test_intelligence_score_prioritizes_uncovered_profiles_without_authority(self) -> None:
        record = {
            "profiles_executed": ["kubernetes_service_platform"],
            "cycles_total": 1,
            "learning_packet_count": 1,
            "execute": False,
            "advisory_hash": "sha256:current",
        }
        registry = [
            {"profile_id": "kubernetes_service_platform", "priority_phase": "p0", "proof_gates": ["a", "b"]},
            {"profile_id": "hardened_image_supply_chain", "priority_phase": "p0", "proof_gates": ["a", "b", "c"]},
            {"profile_id": "multi_region_provider_plane", "priority_phase": "p2", "proof_gates": ["a"]},
        ]

        score = build_recursive_chaos_intelligence_score(
            automation_record=record,
            registry_profiles=registry,
            prior_records=[],
        )

        self.assertEqual(score["schema_version"], "mesh.recursive_chaos.intelligence_score.v1")
        self.assertFalse(score["training_allowed"])
        self.assertFalse(score["production_authority"])
        self.assertEqual(score["repeated_advisory_hash_rate"], 0.0)
        self.assertIn("hardened_image_supply_chain", score["recommended_next_profiles"][:2])

    def test_intelligence_score_marks_repeated_advisory_hash(self) -> None:
        score = build_recursive_chaos_intelligence_score(
            automation_record={
                "profiles_executed": ["kubernetes_service_platform"],
                "cycles_total": 1,
                "learning_packet_count": 1,
                "execute": False,
                "advisory_hash": "sha256:repeat",
            },
            registry_profiles=[{"profile_id": "kubernetes_service_platform", "priority_phase": "p0"}],
            prior_records=[{"advisory_hash": "sha256:repeat"}],
        )

        self.assertEqual(score["repeated_advisory_hash_rate"], 1.0)
        self.assertEqual(score["novelty_score"], 0.0)

    def test_feedback_gate_keeps_meshmodel_and_production_blocked(self) -> None:
        gate = build_recursive_chaos_feedback_gate(
            run_id="run_feedback",
            summary={
                "status": "pass",
                "profiles": ["kubernetes_service_platform"],
                "learning_packet_refs": ["learning_a"],
            },
            advisory={"sealed_source_packet_refs": ["cycle_a", "learning_a"]},
            intelligence_score={
                "scheduler_weights": [
                    {
                        "profile_id": "kubernetes_service_platform",
                        "priority_phase": "p0",
                        "weight": 1.5,
                        "reason": "high_proof_gate_surface",
                    }
                ],
                "recommended_next_profiles": ["kubernetes_service_platform"],
            },
        )

        self.assertEqual(gate["schema_version"], "mesh.recursive_chaos.feedback_gate.v1")
        self.assertEqual(gate["mesh_brain_mode"], "recommend_only")
        self.assertEqual(gate["mesh_model_mode"], "recommend_only")
        self.assertFalse(gate["mesh_model_training_allowed"])
        self.assertFalse(gate["production_authority"])

    def test_runner_discovers_profiles_posts_session_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "last-run.json"
            history_dir = Path(tmp) / "runs"
            env = {
                "MESH_RECURSIVE_CHAOS_SUMMARY_PATH": str(summary_path),
                "MESH_RECURSIVE_CHAOS_HISTORY_DIR": str(history_dir),
                "MESH_RECURSIVE_CHAOS_SEED": "42",
                "MESH_RECURSIVE_CHAOS_MAX_CYCLES": "auto",
                "MESH_RECURSIVE_CHAOS_OPERATOR_EMAIL": "operator@example.com",
            }
            registry = {
                "profiles": [
                    {"profile_id": "kubernetes_service_platform", "priority_phase": "p0", "proof_gates": ["safety"]},
                    {"profile_id": "ai_agent_tool_execution", "priority_phase": "p1", "proof_gates": ["safety"]},
                ]
            }
            run = {
                "run_id": "run_test",
                "stage": "completed",
                "status": "completed",
                "artifacts": {
                    "operator": {"operator_id": "operator@example.com"},
                    "recursive_chaos_session_summary": {
                        "status": "pass",
                        "cycles_total": 2,
                        "profiles": ["ai_agent_tool_execution", "kubernetes_service_platform"],
                        "learning_packet_refs": ["learning_a", "learning_b"],
                        "output_dir": "/tmp/recursive-chaos/run_test",
                    },
                    "mesh_brain_recursive_chaos_advisory": {"advisory_hash": "sha256:test"},
                },
            }

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(automation, "_fetch_json", return_value=registry):
                    with mock.patch.object(automation, "_post_json", return_value=run) as post_json:
                        with redirect_stdout(StringIO()):
                            exit_code = automation.main([])

            self.assertEqual(exit_code, 0)
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            validate_recursive_chaos_automation_summary(payload)
            self.assertEqual(payload["run_id"], "run_test")
            self.assertEqual(payload["profile_source"], "registry")
            self.assertEqual(payload["seed"], 42)
            self.assertEqual(payload["learning_packet_count"], 2)
            self.assertTrue((history_dir / "run_test.json").exists())
            posted_payload = post_json.call_args.args[1]
            self.assertEqual(posted_payload["profile_ids"], ["kubernetes_service_platform", "ai_agent_tool_execution"])
            self.assertEqual(posted_payload["max_cycles"], 2)
            self.assertFalse(posted_payload["execute"])

    def test_sandbox_execution_posts_compose_sandbox_execute_true(self) -> None:
        run = {
            "run_id": "run_sandbox",
            "stage": "completed",
            "status": "completed",
            "artifacts": {
                "operator": {"operator_id": "operator@example.com"},
                "decision": {"decision_type": "no_action", "autonomy_tier": "approval_required"},
                "recursive_chaos_session_summary": {
                    "status": "pass",
                    "cycles_total": 1,
                    "learning_packet_refs": ["learning_a"],
                    "output_dir": "/tmp/recursive-chaos/run_sandbox",
                },
                "mesh_brain_recursive_chaos_feedback_gate": {
                    "feedback_hash": "sha256:" + "a" * 64,
                    "mesh_model_training_allowed": False,
                    "production_authority": False,
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "MESH_RECURSIVE_CHAOS_SANDBOX_SUMMARY_PATH": str(Path(tmp) / "last-run.json"),
                "MESH_RECURSIVE_CHAOS_SANDBOX_HISTORY_DIR": str(Path(tmp) / "runs"),
                "MESH_RECURSIVE_CHAOS_OPERATOR_EMAIL": "operator@example.com",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(sandbox_execution, "_post_json", return_value=run) as post_json:
                    with redirect_stdout(StringIO()):
                        exit_code = sandbox_execution.main([])

        self.assertEqual(exit_code, 0)
        payload = post_json.call_args.args[1]
        self.assertTrue(payload["execute"])
        self.assertEqual(payload["targets"][0]["substrate"], "compose_sandbox")
        self.assertEqual(payload["targets"][0]["environment"], "local_disposable")


if __name__ == "__main__":
    unittest.main()
