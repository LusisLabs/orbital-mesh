from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig, load_schema, validate_payload
from shared.mesh_runtime.run_export_retrieval import verify_run_export_retrieval


def _config(tmp: str, **overrides) -> RuntimeConfig:
    values = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
        "vault_mirror_mode": "sync",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


class RunExportRetrievalTests(unittest.TestCase):
    def test_run_export_retrieval_schema_is_loadable(self) -> None:
        schema = load_schema("run-export-retrieval.schema.json")
        self.assertEqual(schema["title"], "RunExportRetrieval")

    def test_run_export_package_and_archive_pass_retrieval_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp, run_export_retention_reviewed=True))
            try:
                session = coordinator.state_store.create_run_session(
                    goal_id=coordinator.state_store.ensure_default_goal().goal_id,
                    scenario_key="search_latency_regression",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "input_signal": {"service": "search", "api_key": "secret-value"},
                        "decision": {"decision_type": "reduce_rollout"},
                        "evaluation": {"passed": True},
                        "execution": {"status": "succeeded"},
                        "feedback": {"outcome": "recovered"},
                    },
                )
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="completed",
                    event_type="run_completed",
                    payload={"authorization": "Bearer should-redact"},
                    status="completed",
                )
                current = coordinator.state_store.get_run_session(session.run_id)
                assert current is not None
                current.stage = "completed"
                current.status = "completed"
                coordinator.state_store.save_run_session(current)

                package = coordinator.export_run_package(session.run_id)
                archive = coordinator.export_run_archive(session.run_id)

                assert package is not None
                assert archive is not None
                result = verify_run_export_retrieval(
                    package_path=package["path"],
                    archive_path=archive["path"],
                )

                with zipfile.ZipFile(archive["path"]) as zipped:
                    names = set(zipped.namelist())

            finally:
                coordinator.stop_background_workers()

        self.assertEqual(result["schema_version"], "mesh.run_export_retrieval.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checks"]["archive_vault_documents_present"])
        self.assertTrue(any(name.startswith("vault/") for name in names))
        validate_payload("run-export-retrieval.schema.json", result)

    def test_run_export_retrieval_blocks_unredacted_secret_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                session = coordinator.state_store.create_run_session(
                    goal_id=coordinator.state_store.ensure_default_goal().goal_id,
                    scenario_key="search_latency_regression",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "input_signal": {"service": "search"},
                        "decision": {"decision_type": "reduce_rollout"},
                        "evaluation": {"passed": True},
                        "execution": {"status": "succeeded"},
                        "feedback": {"outcome": "recovered"},
                    },
                )
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="completed",
                    event_type="run_completed",
                    payload={"status": "completed"},
                    status="completed",
                )
                current = coordinator.state_store.get_run_session(session.run_id)
                assert current is not None
                current.stage = "completed"
                current.status = "completed"
                coordinator.state_store.save_run_session(current)
                package = coordinator.export_run_package(session.run_id)
                assert package is not None
                package_path = Path(package["path"])
                raw = json.loads(package_path.read_text(encoding="utf-8"))
                raw["evidence_artifacts"]["input_signal"]["api_key"] = "leaked-secret"
                package_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                result = verify_run_export_retrieval(package_path=package_path)
            finally:
                coordinator.stop_background_workers()

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["secret_fields_redacted"])


if __name__ == "__main__":
    unittest.main()
