from __future__ import annotations

import json
import tempfile
import time
import unittest
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
                    feature_flag_credentials_available=False,
                    incident_credentials_available=False,
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(readiness["connector_certification"]["feature_flag_adapter"]["state"], "disabled")
        self.assertEqual(readiness["connector_certification"]["incident_adapter"]["state"], "disabled")


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
