from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from services.decision.service import DecisionService
from services.evaluation.service import EvaluationService
from services.ingest.service import IngestService
from services.orchestrator.agent_mesh import AgentMeshService
from services.trigger.service import TriggerService
from shared.mesh_runtime import RuntimeConfig, RuntimeStateStore, build_readiness, load_fixture


class LatentMasAgentMeshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_latentmas_disabled_preserves_native_worker_attempts(self) -> None:
        trigger, decision, evaluation = self._build_runtime_artifacts()
        tasks = AgentMeshService(config=self.config).build_tasks(
            run_id="run_disabled",
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
        )
        self.assertEqual(
            [attempt.agent for attempt in tasks[0].attempts],
            ["goose", "hermes", "codex", "claudecode", "openclaw", "evo"],
        )

    def test_latentmas_enabled_prepends_completed_attempt(self) -> None:
        server, thread = _start_fake_latentmas(
            {
                "summary": "LatentMAS recommends the gated execution path.",
                "recommended_action": "execute",
                "risk_flags": [],
                "confidence": 0.91,
                "raw_prediction": "{\"summary\":\"ok\"}",
                "agent_traces": [{"role": "judger", "output": "{\"summary\":\"ok\"}"}],
                "metrics": {"model_name": "fake-qwen", "elapsed_time_sec": 0.01},
            }
        )
        try:
            self.config.latentmas_enabled = True
            self.config.latentmas_url = f"http://127.0.0.1:{server.server_address[1]}"
            trigger, decision, evaluation = self._build_runtime_artifacts()
            tasks = AgentMeshService(config=self.config).build_tasks(
                run_id="run_enabled",
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )
            task = tasks[0]
            self.assertEqual(task.attempts[0].agent, "latentmas")
            self.assertEqual(task.attempts[0].adapter, "latentmas_http")
            self.assertEqual(task.attempts[0].output["metrics"]["model_name"], "fake-qwen")
            self.assertEqual(task.selected_attempt_id, task.attempts[0].attempt_id)
            self.assertEqual(_FakeLatentMasHandler.last_payload["task"]["task_id"], task.task_id)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_latentmas_unavailable_records_failed_attempt(self) -> None:
        self.config.latentmas_enabled = True
        self.config.latentmas_url = "http://127.0.0.1:9"
        self.config.latentmas_timeout_seconds = 0.2
        trigger, decision, evaluation = self._build_runtime_artifacts()
        task = AgentMeshService(config=self.config).build_tasks(
            run_id="run_unavailable",
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
        )[0]
        self.assertEqual(task.attempts[0].agent, "latentmas")
        self.assertEqual(task.attempts[0].status, "failed")
        self.assertEqual(task.attempts[0].risk_flags, ["latentmas_unavailable"])
        self.assertNotEqual(task.selected_attempt_id, task.attempts[0].attempt_id)

    def test_latentmas_invalid_json_adds_unparseable_flag(self) -> None:
        server, thread = _start_fake_latentmas("not json", raw=True)
        try:
            self.config.latentmas_enabled = True
            self.config.latentmas_url = f"http://127.0.0.1:{server.server_address[1]}"
            trigger, decision, evaluation = self._build_runtime_artifacts()
            task = AgentMeshService(config=self.config).build_tasks(
                run_id="run_invalid_json",
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )[0]
            self.assertEqual(task.attempts[0].risk_flags, ["latentmas_output_unparseable"])
            self.assertIn("raw_response", task.attempts[0].output)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_latentmas_health_not_ready_skips_infer(self) -> None:
        server, thread = _start_fake_latentmas(
            {"summary": "should not run"},
            health_payload={"ready": False, "detail": "requested device `cuda` unavailable; falling back to cpu"},
        )
        try:
            self.config.latentmas_enabled = True
            self.config.latentmas_url = f"http://127.0.0.1:{server.server_address[1]}"
            trigger, decision, evaluation = self._build_runtime_artifacts()
            task = AgentMeshService(config=self.config).build_tasks(
                run_id="run_not_ready",
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )[0]
            self.assertEqual(task.attempts[0].status, "failed")
            self.assertIn("LatentMAS sidecar not ready", task.attempts[0].summary)
            self.assertEqual(_FakeLatentMasHandler.last_payload, {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_latentmas_http_error_surfaces_server_reason(self) -> None:
        server, thread = _start_fake_latentmas(
            {"error": "model load failed: CUDA driver not available"},
            response_status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        try:
            self.config.latentmas_enabled = True
            self.config.latentmas_url = f"http://127.0.0.1:{server.server_address[1]}"
            trigger, decision, evaluation = self._build_runtime_artifacts()
            task = AgentMeshService(config=self.config).build_tasks(
                run_id="run_http_error",
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )[0]
            self.assertEqual(task.attempts[0].status, "failed")
            self.assertIn("CUDA driver not available", task.attempts[0].summary)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_latentmas_output_is_capped(self) -> None:
        server, thread = _start_fake_latentmas(
            {
                "summary": "ok",
                "recommended_action": "human_review",
                "risk_flags": [],
                "raw_prediction": "x" * 100,
                "agent_traces": [{"role": "judger", "output": "y" * 100}],
                "metrics": {},
            }
        )
        try:
            self.config.latentmas_enabled = True
            self.config.latentmas_url = f"http://127.0.0.1:{server.server_address[1]}"
            self.config.latentmas_max_artifact_chars = 10
            trigger, decision, evaluation = self._build_runtime_artifacts()
            attempt = AgentMeshService(config=self.config).build_tasks(
                run_id="run_capped",
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )[0].attempts[0]
            self.assertEqual(attempt.output["raw_prediction"], "x" * 10 + "\n[truncated]")
            self.assertEqual(attempt.output["agent_traces"][0]["output"], "y" * 10 + "\n[truncated]")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_readiness_reports_latentmas_health(self) -> None:
        unhealthy = build_readiness(self.config).to_dict()
        self.assertFalse(unhealthy["latentmas"]["ready"])
        self.assertEqual(unhealthy["latentmas"]["detail"], "disabled")

        server, thread = _start_fake_latentmas({"ok": True})
        try:
            self.config.latentmas_enabled = True
            self.config.latentmas_url = f"http://127.0.0.1:{server.server_address[1]}"
            healthy = build_readiness(self.config).to_dict()
            self.assertTrue(healthy["latentmas"]["ready"])
            self.assertEqual(healthy["latentmas"]["url"], self.config.latentmas_url)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def _build_runtime_artifacts(self):
        signal = load_fixture("signals", "search_latency_regression.json")
        normalized = IngestService().normalize_signal(signal)
        trigger = TriggerService().detect(normalized)
        self.assertIsNotNone(trigger)
        decision = DecisionService().decide(trigger)
        evaluation = EvaluationService(config=self.config, state_store=RuntimeStateStore(self.temp_dir.name)).evaluate(
            trigger,
            decision,
        )
        return trigger, decision, evaluation


class _FakeLatentMasHandler(BaseHTTPRequestHandler):
    response_payload: Any = {}
    health_payload: dict[str, Any] = {"ready": True}
    response_status = HTTPStatus.OK
    raw_response = False
    last_payload: dict[str, Any] = {}

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(self.health_payload)
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/infer":
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        _FakeLatentMasHandler.last_payload = json.loads(body.decode("utf-8"))
        if self.raw_response:
            data = str(self.response_payload).encode("utf-8")
            self.send_response(self.response_status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_json(self.response_payload, status=self.response_status)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _start_fake_latentmas(
    payload: Any,
    raw: bool = False,
    *,
    health_payload: dict[str, Any] | None = None,
    response_status: HTTPStatus = HTTPStatus.OK,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    _FakeLatentMasHandler.response_payload = payload
    _FakeLatentMasHandler.health_payload = health_payload or {"ready": True}
    _FakeLatentMasHandler.response_status = response_status
    _FakeLatentMasHandler.raw_response = raw
    _FakeLatentMasHandler.last_payload = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLatentMasHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    unittest.main()
