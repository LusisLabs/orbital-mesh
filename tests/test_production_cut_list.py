from __future__ import annotations

import json
import io
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from services.decision.service import DecisionService
from services.feedback.service import FeedbackService
from services.ingest.service import IngestService
from services.trigger.service import TriggerService
from services.control_plane import RunCoordinator
from shared.mesh_runtime import ExecutionRecord, RuntimeConfig, load_fixture
from shared.mesh_runtime.integrations import build_readiness


def _config(tmp: str, **overrides) -> RuntimeConfig:
    values = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


def _pilot_ready_config(tmp: str) -> RuntimeConfig:
    return _config(
        tmp,
        readiness_profile="pilot",
        operator_identity_required=True,
        state_backend="postgres",
        database_url="postgresql://mesh:mesh@localhost:5432/mesh",
        force_approval_gate=True,
        live_feedback_required=True,
        feedback_prometheus_enabled=True,
        prometheus_url="http://prometheus.local",
        mesh_brain_artifact_uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
        mesh_brain_serving_base_url="http://mesh-brain-serving.private:8000",
        mesh_brain_serving_model="nvidia/nemotron-3-nano-4b",
        run_export_retention_reviewed=True,
        feature_flag_credentials_available=False,
        incident_credentials_available=False,
    )


def _record_generic_pilot_evidence(coordinator: RunCoordinator) -> None:
    session = coordinator.state_store.create_run_session(
        goal_id=coordinator.state_store.ensure_default_goal().goal_id,
        scenario_key="search_latency_regression",
        steering_mode="approval_gate",
        auto_mode=False,
        pause_points=[],
        evaluation_mode="native",
        orchestration_mode="native",
        artifacts={
            "decision": {"execution_plan": {"rollback_plan": "roll back deployment revision"}},
            "evaluation": {"blocking_reasons": ["approval required before execution"]},
            "execution": {"external_refs": {"live_execution": True}},
        },
    )
    coordinator.state_store.append_run_event(
        session.run_id,
        stage="awaiting_operator",
        event_type="steering_command",
        payload={"command_type": "approve", "operator": {"operator_id": "approver@example.com"}},
        status="accepted",
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


def _record_mesh_brain_gate_evidence(coordinator: RunCoordinator) -> None:
    _record_completed_probe(
        coordinator,
        "mesh_brain_model_kernel_probe",
        {
            "mesh_brain_model_kernel_run_record": {
                "status": "completed",
                "final_release_decision": "pass",
                "artifact_refs": _hashed_refs("mesh_brain_model_kernel_probe_summary"),
            }
        },
    )
    _record_completed_probe(
        coordinator,
        "mesh_brain_live_serving_smoke",
        {
            "mesh_brain_live_serving_run_record": {
                "tenant_id": "tenant_a",
                "status": "completed",
                "final_release_decision": "canary",
                "artifact_refs": _hashed_refs("mesh_brain_live_serving_summary"),
                "summary_metrics": {
                    "task_type": "crops",
                    "live_smoke_gate": "pass",
                    "live_response_eval": "pass",
                    "live_judge_eval": "pass",
                },
            }
        },
    )
    _record_completed_probe(
        coordinator,
        "mesh_brain_rollback_drill",
        {
            "mesh_brain_rollback_drill_run_record": {
                "status": "completed",
                "final_release_decision": "pass",
                "artifact_refs": _hashed_refs("mesh_brain_rollback_drill_summary"),
                "summary_metrics": {"restored_previous_artifact": True},
            }
        },
    )


def _record_completed_probe(coordinator: RunCoordinator, scenario_key: str, artifacts: dict) -> None:
    session = coordinator.state_store.create_run_session(
        goal_id=coordinator.state_store.ensure_default_goal().goal_id,
        scenario_key=scenario_key,
        steering_mode="system_probe",
        auto_mode=False,
        pause_points=[],
        evaluation_mode=scenario_key,
        orchestration_mode="native",
        artifacts=artifacts,
    )
    coordinator.state_store.append_run_event(
        session.run_id,
        stage="completed",
        event_type="run_completed",
        payload={"status": "completed", "scenario_key": scenario_key},
        status="completed",
    )
    current = coordinator.state_store.get_run_session(session.run_id)
    assert current is not None
    current.stage = "completed"
    current.status = "completed"
    coordinator.state_store.save_run_session(current)


def _hashed_refs(key: str) -> dict[str, dict[str, str]]:
    return {
        key: {
            "artifact_key": key,
            "path": f"/tmp/{key}.json",
            "sha256": "a" * 64,
            "content_type": "application/json",
        }
    }


class ReadinessProfileTests(unittest.TestCase):
    def test_staging_profile_fails_required_identity_not_optional_clis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=False,
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["profile"], "staging")
        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("operator_identity_required", readiness["blockers"])
        self.assertNotIn("promptfoo", readiness["blockers"])

    def test_staging_profile_passes_with_optional_lanes_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    otel_receiver_enabled=True,
                    otel_receiver_token="token",
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "ready")
        self.assertFalse(readiness["promptfoo"]["ready"])
        self.assertEqual(readiness["promptfoo"]["certification"], "mock")

    def test_pilot_profile_requires_postgres_live_feedback_and_disabled_unfinished_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="pilot",
                    operator_identity_required=True,
                    state_backend="postgres",
                    database_url="postgresql://mesh:mesh@localhost:5432/mesh",
                    force_approval_gate=True,
                    live_feedback_required=True,
                    feedback_prometheus_enabled=True,
                    prometheus_url="http://prometheus.local",
                    mesh_brain_artifact_uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
                    mesh_brain_serving_base_url="http://mesh-brain-serving.private:8000",
                    mesh_brain_serving_model="nvidia/nemotron-3-nano-4b",
                    run_export_retention_reviewed=True,
                    feature_flag_credentials_available=False,
                    incident_credentials_available=False,
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["required_checks"]["mesh_brain_artifact_uri_prefix_configured"])
        self.assertTrue(readiness["required_checks"]["mesh_brain_serving_backend_configured"])
        self.assertTrue(readiness["required_checks"]["run_export_retention_reviewed"])
        self.assertEqual(readiness["connector_certification"]["feature_flag_adapter"]["state"], "disabled")
        self.assertEqual(readiness["connector_certification"]["incident_adapter"]["state"], "disabled")

    def test_pilot_profile_blocks_unreviewed_run_export_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="pilot",
                    operator_identity_required=True,
                    state_backend="postgres",
                    database_url="postgresql://mesh:mesh@localhost:5432/mesh",
                    force_approval_gate=True,
                    live_feedback_required=True,
                    feedback_prometheus_enabled=True,
                    prometheus_url="http://prometheus.local",
                    mesh_brain_artifact_uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
                    mesh_brain_serving_base_url="http://mesh-brain-serving.private:8000",
                    mesh_brain_serving_model="nvidia/nemotron-3-nano-4b",
                    feature_flag_credentials_available=False,
                    incident_credentials_available=False,
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("run_export_retention_reviewed", readiness["blockers"])

    def test_pilot_profile_blocks_local_mesh_brain_artifact_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="pilot",
                    operator_identity_required=True,
                    state_backend="postgres",
                    database_url="postgresql://mesh:mesh@localhost:5432/mesh",
                    force_approval_gate=True,
                    live_feedback_required=True,
                    feedback_prometheus_enabled=True,
                    prometheus_url="http://prometheus.local",
                    mesh_brain_artifact_uri_prefix=f"file://{tmp}/mesh-brain",
                    run_export_retention_reviewed=True,
                    feature_flag_credentials_available=False,
                    incident_credentials_available=False,
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("mesh_brain_artifact_uri_prefix_configured", readiness["blockers"])


class ProductionComposeContractTests(unittest.TestCase):
    def test_prod_compose_defaults_to_private_boundary_and_required_durable_mesh_brain_config(self) -> None:
        compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")

        self.assertIn('${MESH_PUBLISH_HOST:-127.0.0.1}:${MESH_PUBLISH_PORT:-8787}:8787', compose)
        self.assertNotIn('- "${MESH_PUBLISH_PORT:-8787}:8787"', compose)
        for marker in (
            'MESH_READINESS_PROFILE: "${MESH_READINESS_PROFILE:-pilot}"',
            'MESH_STATE_BACKEND: "${MESH_STATE_BACKEND:-postgres}"',
            'MESH_DATABASE_URL: "${MESH_DATABASE_URL:?set Postgres database URL for production state}"',
            'MESH_OPERATOR_IDENTITY_REQUIRED: "${MESH_OPERATOR_IDENTITY_REQUIRED:-1}"',
            'MESH_FORCE_APPROVAL_GATE: "${MESH_FORCE_APPROVAL_GATE:-1}"',
            'MESH_LIVE_FEEDBACK_REQUIRED: "${MESH_LIVE_FEEDBACK_REQUIRED:-1}"',
            'MESH_FEEDBACK_PROMETHEUS_ENABLED: "${MESH_FEEDBACK_PROMETHEUS_ENABLED:-1}"',
            'MESH_PROMETHEUS_URL: "${MESH_PROMETHEUS_URL:?set production Prometheus URL for feedback and telemetry}"',
            'MESH_BRAIN_ARTIFACT_URI_PREFIX: "${MESH_BRAIN_ARTIFACT_URI_PREFIX:?set durable object-storage URI prefix for Mesh Brain artifacts}"',
            'MESH_BRAIN_SERVING_BASE_URL: "${MESH_BRAIN_SERVING_BASE_URL:?set OpenAI-compatible Mesh Brain serving backend URL}"',
            'MESH_BRAIN_SERVING_MODEL: "${MESH_BRAIN_SERVING_MODEL:?set Mesh Brain serving model name}"',
            'MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE: "${MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE:-false}"',
            'MESH_INCIDENT_CREDENTIALS_AVAILABLE: "${MESH_INCIDENT_CREDENTIALS_AVAILABLE:-false}"',
        ):
            self.assertIn(marker, compose)


class PilotGoNoGoMeshBrainGateTests(unittest.TestCase):
    def test_pilot_go_no_go_requires_mesh_brain_kernel_live_canary_and_rollback_drill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)

                blocked = coordinator.generate_pilot_go_no_go()

                self.assertEqual(blocked["status"], "blocked")
                self.assertIn("mesh_brain_model_kernel_gate_observed", blocked["missing_evidence"])
                self.assertIn("mesh_brain_live_canary_smoke_observed", blocked["missing_evidence"])
                self.assertIn("mesh_brain_single_crops_canary_lane_observed", blocked["missing_evidence"])
                self.assertIn("mesh_brain_rollback_drill_observed", blocked["missing_evidence"])

                _record_mesh_brain_gate_evidence(coordinator)
                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "go")
                self.assertEqual(packet["missing_evidence"], [])
                self.assertEqual(packet["observed"]["mesh_brain_canary_lanes"], [{"tenant_id": "tenant_a", "task_type": "crops"}])
                self.assertEqual(len(packet["observed"]["mesh_brain_model_kernel_run_ids"]), 1)
                self.assertEqual(len(packet["observed"]["mesh_brain_live_canary_smoke_run_ids"]), 1)
                self.assertEqual(len(packet["observed"]["mesh_brain_rollback_drill_run_ids"]), 1)
            finally:
                coordinator.stop_background_workers()


class OperatorRoleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = _config(
            self.temp_dir.name,
            server_host="127.0.0.1",
            server_port=0,
            operator_identity_required=True,
        )
        self.server, self.thread = start_server_in_thread(self.config, start_sidecar=False)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.coordinator._lock:
                active_workers = list(self.server.coordinator._threads.values())
            if not any(worker.is_alive() for worker in active_workers):
                break
            time.sleep(0.05)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_run_creation_and_approval_require_roles_and_stamp_operator(self) -> None:
        payload = {
            "scenario_key": "search_latency_regression",
            "evaluation_mode": "native",
            "orchestration_mode": "native",
            "steering_mode": "approval_gate",
        }
        with self.assertRaises(HTTPError) as missing:
            self._request("POST", "/api/runs", payload)
        self.assertEqual(missing.exception.code, 401)

        with self.assertRaises(HTTPError) as forbidden:
            self._request(
                "POST",
                "/api/runs",
                payload,
                headers={"X-Mesh-Operator": "viewer@example.com", "X-Mesh-Roles": "viewer"},
            )
        self.assertEqual(forbidden.exception.code, 403)

        run = self._request(
            "POST",
            "/api/runs",
            payload,
            headers={"X-Mesh-Operator": "launcher@example.com", "X-Mesh-Roles": "launcher"},
        )
        self.assertEqual(run["artifacts"]["operator"]["operator_id"], "launcher@example.com")
        paused = self._poll_run(run["run_id"], lambda item: item["stage"] == "awaiting_operator")

        with self.assertRaises(HTTPError) as steering_forbidden:
            self._request(
                "POST",
                f"/api/runs/{paused['run_id']}/steer",
                {"command": "approve"},
                headers={"X-Mesh-Operator": "launcher@example.com", "X-Mesh-Roles": "launcher"},
            )
        self.assertEqual(steering_forbidden.exception.code, 403)

        approved = self._request(
            "POST",
            f"/api/runs/{paused['run_id']}/steer",
            {"command": "approve"},
            headers={"X-Mesh-Operator": "approver@example.com", "X-Mesh-Roles": "approver"},
        )
        command_events = [event for event in approved["events"] if event["event_type"] == "steering_command"]
        self.assertEqual(command_events[-1]["payload"]["operator"]["operator_id"], "approver@example.com")

        with self.assertRaises(HTTPError) as export_forbidden:
            self._request(
                "POST",
                f"/api/runs/{paused['run_id']}/export",
                {},
                headers={"X-Mesh-Operator": "anonymous@example.com", "X-Mesh-Roles": ""},
            )
        self.assertEqual(export_forbidden.exception.code, 403)

        exported = self._request(
            "POST",
            f"/api/runs/{paused['run_id']}/export",
            {},
            headers={"X-Mesh-Operator": "viewer@example.com", "X-Mesh-Roles": "viewer"},
        )
        self.assertEqual(exported["run_id"], paused["run_id"])
        self.assertRegex(exported["package_sha256"], r"^[0-9a-f]{64}$")

        archive_headers, archive_body = self._request_bytes(
            "POST",
            f"/api/runs/{paused['run_id']}/export/archive",
            {},
            headers={"X-Mesh-Operator": "viewer@example.com", "X-Mesh-Roles": "viewer"},
        )
        self.assertEqual(archive_headers["Content-Type"], "application/zip")
        self.assertIn(f'{paused["run_id"]}.zip', archive_headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("package.json", archive.namelist())
            self.assertIn("postmortem.md", archive.namelist())

    def _poll_run(self, run_id: str, predicate, timeout_seconds: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = self._request("GET", f"/api/runs/{run_id}")
            if predicate(payload):
                return payload
            time.sleep(0.1)
        raise AssertionError(f"run {run_id} did not satisfy predicate before timeout")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict:
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=request_headers, method=method)
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _request_bytes(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], bytes]:
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=request_headers, method=method)
        with urlopen(request, timeout=10) as response:
            return dict(response.headers.items()), response.read()


class PolicySimulationAndKillSwitchTests(unittest.TestCase):
    def test_policy_simulator_does_not_create_runs_or_evaluation_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                result = coordinator.simulate_policy({"scenario_key": "search_latency_regression"})
                self.assertFalse(result["mutates"])
                self.assertTrue(result["triggered"])
                self.assertIn("decision_type", result["decision"])
                self.assertEqual(coordinator.list_runs(), [])
                self.assertFalse((Path(tmp) / "evaluated_triggers.json").exists())
            finally:
                coordinator.stop_background_workers()

    def test_kill_switch_disables_live_execution_and_forces_approval_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    kubernetes_live_execution_enabled=True,
                    kubernetes_allowed_contexts=("ctx",),
                    kubernetes_allowed_namespaces=("default",),
                    default_steering_mode="interruptible_auto",
                )
            )
            try:
                status = coordinator.apply_kill_switch(
                    {
                        "stop_watchers": True,
                        "disable_live_execution": True,
                        "force_approval_gate": True,
                        "_operator": {"operator_id": "admin@example.com", "roles": ["admin"]},
                    }
                )
                self.assertIn("watchers_stopped", status["actions"])
                self.assertFalse(status["live_execution_enabled"])
                self.assertTrue(status["force_approval_gate"])

                run = coordinator.create_run(
                    {
                        "scenario_key": "search_latency_regression",
                        "evaluation_mode": "native",
                        "orchestration_mode": "native",
                        "steering_mode": "interruptible_auto",
                    }
                )
                self.assertEqual(run["steering_mode"], "approval_gate")
            finally:
                coordinator.stop_background_workers()


class RunExportPackageTests(unittest.TestCase):
    def test_run_export_package_contains_postmortem_records_merkle_and_vault_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp, vault_mirror_mode="sync"))
            try:
                goal_id = coordinator.state_store.ensure_default_goal().goal_id
                session = coordinator.state_store.create_run_session(
                    goal_id=goal_id,
                    scenario_key="search_latency_regression",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "input_signal": {
                            "signal_type": "latency_regression",
                            "service": "search",
                            "api_key": "sk-test-secret",
                        },
                        "decision": {"decision_type": "reduce_rollout", "risk_level": "medium", "requires_approval": True},
                        "evaluation": {"status": "passed", "passed": True},
                        "execution": {"status": "succeeded", "executor": "native"},
                        "feedback": {"outcome": "recovered"},
                        "evidence_graph": {"nodes": [{"id": "signal"}], "edges": []},
                        "approvals": [{"operator_id": "approver@example.com", "command": "approve"}],
                    },
                )
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="trigger_ready",
                    event_type="trigger_ready",
                    payload={"trigger_id": "trigger_test", "authorization": "Bearer live-token"},
                    artifact_key="trigger",
                    status="ready",
                )
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="completed",
                    event_type="run_completed",
                    payload={"status": "completed"},
                    status="completed",
                )
                session = coordinator.state_store.get_run_session(session.run_id)
                assert session is not None
                session.stage = "completed"
                session.status = "completed"
                coordinator.state_store.save_run_session(session)

                package = coordinator.export_run_package(session.run_id)

                self.assertIsNotNone(package)
                assert package is not None
                self.assertEqual(package["package_version"], "mesh.run_export.v1")
                self.assertEqual(package["run_id"], session.run_id)
                self.assertEqual(package["decision_record"]["decision_type"], "reduce_rollout")
                self.assertTrue(package["evaluation_record"]["passed"])
                self.assertEqual(package["execution_record"]["status"], "succeeded")
                self.assertEqual(package["feedback_record"]["outcome"], "recovered")
                self.assertEqual(package["evidence_artifacts"]["input_signal"]["api_key"], "<redacted>")
                self.assertEqual(package["timeline_json"][0]["payload"]["authorization"], "<redacted>")
                self.assertEqual(package["evidence_artifacts"]["evidence_graph"]["nodes"][0]["id"], "signal")
                self.assertTrue(package["merkle"]["latest_event_proof"]["valid"])
                self.assertEqual(package["retention"]["retention_days"], 30)
                self.assertFalse(package["retention"]["reviewed"])
                self.assertIn("delete_after", package["retention"])
                self.assertFalse(package["size_control"]["truncated"])
                self.assertRegex(package["package_sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(Path(package["path"]).is_file())
                self.assertIn(f"# Mesh Run Export {session.run_id}", package["postmortem_markdown"])
                self.assertIn(f"Runs/{session.run_id}.md", {doc["path"] for doc in package["vault_documents"]})
                exported = json.loads(Path(package["path"]).read_text(encoding="utf-8"))
                self.assertEqual(exported["package_sha256"], package["package_sha256"])
                current = coordinator.state_store.get_run_session(session.run_id)
                assert current is not None
                self.assertIn("run_export_package", current.artifacts)

                archive = coordinator.export_run_archive(session.run_id)
                self.assertIsNotNone(archive)
                assert archive is not None
                self.assertTrue(Path(archive["path"]).is_file())
                self.assertRegex(archive["sha256"], r"^[0-9a-f]{64}$")
                with zipfile.ZipFile(archive["path"]) as zipped:
                    names = set(zipped.namelist())
                    self.assertIn("manifest.json", names)
                    self.assertIn("package.json", names)
                    self.assertIn("timeline.json", names)
                    self.assertIn("postmortem.md", names)
                    self.assertIn("records/decision.json", names)
                    manifest = json.loads(zipped.read("manifest.json").decode("utf-8"))
                    self.assertEqual(manifest["archive_version"], "mesh.run_export_archive.v1")
                    self.assertEqual(manifest["run_id"], session.run_id)
                    self.assertEqual(manifest["retention"]["retention_days"], 30)
            finally:
                coordinator.stop_background_workers()

    def test_run_export_package_compacts_large_payloads_under_size_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp, vault_mirror_mode="sync", run_export_max_bytes=12000))
            try:
                session = coordinator.state_store.create_run_session(
                    goal_id=coordinator.state_store.ensure_default_goal().goal_id,
                    scenario_key="large_export",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "input_signal": {"service": "search", "payload": "x" * 20_000},
                        "decision": {"decision_type": "noop"},
                        "evaluation": {"passed": True},
                        "execution": {"status": "skipped"},
                        "feedback": {"outcome": "not_applicable"},
                    },
                )
                session.operator_notes.append("operator note " + ("y" * 20_000))
                coordinator.state_store.save_run_session(session)
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="completed",
                    event_type="run_completed",
                    payload={"blob": "z" * 20_000, "token": "secret-token"},
                    status="completed",
                )
                session = coordinator.state_store.get_run_session(session.run_id)
                assert session is not None
                session.stage = "completed"
                session.status = "completed"
                coordinator.state_store.save_run_session(session)

                package = coordinator.export_run_package(session.run_id)

                self.assertIsNotNone(package)
                assert package is not None
                encoded = json.dumps(package, sort_keys=True, default=str).encode("utf-8")
                self.assertLessEqual(len(encoded), 12000)
                self.assertTrue(package["size_control"]["truncated"])
                self.assertIn("vault_documents", package["size_control"]["omitted_fields"])
                self.assertIn("timeline_json", package["size_control"]["omitted_fields"])
                self.assertEqual(package["timeline_json"][0]["payload"], {"omitted": "run export size cap"})
                self.assertTrue(Path(package["path"]).is_file())
            finally:
                coordinator.stop_background_workers()


class PilotFeedbackGateTests(unittest.TestCase):
    def test_live_feedback_required_escalates_when_only_stub_observations_exist(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        normalized = IngestService().normalize_signal(signal)
        trigger = TriggerService().detect(normalized)
        self.assertIsNotNone(trigger)
        assert trigger is not None
        decision = DecisionService().decide(trigger)
        execution = ExecutionRecord(
            execution_id="exec_test",
            decision_id=decision.decision_id,
            started_at=signal["observed_at"],
            completed_at=signal["observed_at"],
            executor="native",
            status="succeeded",
            idempotency_key="exec_test",
            applied_action=decision.execution_plan,
            external_refs={"flag_change_id": "ffchg_test"},
        )

        feedback = FeedbackService(require_live_observations=True).record(
            trigger,
            decision,
            execution,
            normalized,
        )

        self.assertEqual(feedback.outcome, "escalated")
        self.assertTrue(feedback.metric_comparison["live_feedback_required"])
        self.assertFalse(feedback.metric_comparison["live_feedback_source_present"])


if __name__ == "__main__":
    unittest.main()
