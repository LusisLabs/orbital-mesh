from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import FileStateStore, RuntimeConfig
from shared.mesh_runtime.halo import (
    OPTIMIZATION_ARTIFACT_KEY,
    TRACE_FORMAT,
    build_halo_patch_task,
    export_halo_traces,
    record_halo_optimization_cycle,
    run_halo_engine,
)
from shared.mesh_runtime.json_store import LockedJsonFile


class HaloOuterLoopTests(unittest.TestCase):
    def test_exports_run_history_as_halo_trace_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            run_id = _seed_run(store)
            output = Path(tmp) / "halo" / "traces.jsonl"

            result = export_halo_traces(store, output, limit=10)

            self.assertEqual(result.trace_count, 1)
            self.assertEqual(result.run_ids, [run_id])
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["trace_format"], TRACE_FORMAT)
            self.assertEqual(rows[0]["trace_id"], run_id)
            self.assertEqual(rows[0]["harness"]["evaluation_mode"], "native")
            self.assertEqual(rows[0]["artifacts"]["decision"]["decision_type"], "rollback_deployment")
            self.assertEqual(rows[0]["failure"]["blocking_reasons"], ["verifier_failed"])
            self.assertEqual(rows[0]["artifacts"]["input_signal"]["api_key"], "[REDACTED]")
            self.assertGreaterEqual(len(rows[0]["otel"]["spans"]), 1)

    def test_records_halo_report_as_bounded_patch_task_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            run_id = _seed_run(store)
            export = export_halo_traces(store, Path(tmp) / "traces.jsonl", limit=10)
            task = build_halo_patch_task(
                optimization_id="halo_test",
                report="Recurring verifier failures point to an evaluator threshold issue.",
                run_ids=[run_id],
                agents=["codex", "goose"],
            )

            artifact = record_halo_optimization_cycle(
                store,
                export=export,
                report="Recurring verifier failures point to an evaluator threshold issue.",
                task=task,
                metadata={"validated_by": "unit-test"},
            )

            self.assertEqual(artifact["artifact_key"], OPTIMIZATION_ARTIFACT_KEY)
            self.assertEqual(artifact["trace_count"], 1)
            self.assertEqual(artifact["patch_task"]["kind"], "halo_harness_optimization")
            self.assertIn("services/", artifact["patch_task"]["allowed_paths"])
            self.assertIn("npm --prefix web run lint", artifact["patch_task"]["test_commands"])
            self.assertEqual(artifact["patch_task"]["agents"], ["codex", "goose"])

            artifact_path = Path(tmp) / "artifacts.json"
            with LockedJsonFile(artifact_path) as payload:
                records = payload.get("artifacts", [])
            self.assertEqual(records[0]["optimization_id"], "halo_test")

    def test_missing_halo_binary_returns_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            _seed_run(store)

            result = run_halo_engine(
                store,
                Path(tmp) / "traces.jsonl",
                halo_command="definitely-not-a-real-halo-binary",
                timeout_seconds=1,
            )

            self.assertEqual(result.returncode, 127)
            self.assertEqual(result.export.trace_count, 1)
            self.assertIn("definitely-not-a-real-halo-binary", result.stderr)


def _store(tmp: str) -> FileStateStore:
    return FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))


def _seed_run(store: FileStateStore) -> str:
    session = store.create_run_session(
        goal_id="goal_default",
        scenario_key="simulation:k8s_crashloop_restart",
        steering_mode="approval_gate",
        auto_mode=False,
        pause_points=["evaluation_ready"],
        evaluation_mode="native",
        orchestration_mode="native",
        artifacts={
            "input_signal": {"service": "search", "api_key": "secret"},
            "decision": {"decision_type": "rollback_deployment"},
            "evaluation": {
                "final_recommendation": "block",
                "blocking_reasons": ["verifier_failed"],
            },
            "agent_tasks": [
                {
                    "task_id": "task_1",
                    "kind": "rollback_plan",
                    "status": "completed",
                    "agents": ["goose"],
                    "attempts": [
                        {
                            "agent": "goose",
                            "adapter": "native_contract",
                            "status": "completed",
                            "recommended_action": "human_review",
                            "risk_flags": ["low_confidence_patch"],
                            "summary": "Patch proposal lacks verifier proof.",
                        }
                    ],
                }
            ],
            "benchmark_score": {"passed": False, "score": 0.42},
        },
    )
    store.append_run_event(
        session.run_id,
        stage="evaluation_ready",
        event_type="evaluation_ready",
        payload={"blocking_reasons": ["verifier_failed"]},
        summary={"recommendation": "block"},
        artifact_key="evaluation",
        status="blocked",
    )
    updated = store.get_run_session(session.run_id)
    assert updated is not None
    updated.stage = "failed"
    updated.status = "failed"
    store.save_run_session(updated)
    return session.run_id


if __name__ == "__main__":
    unittest.main()
