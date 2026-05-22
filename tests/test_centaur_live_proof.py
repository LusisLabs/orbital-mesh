from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from services.orchestrator.centaur_adapter import CentaurAdapter
from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig, Trigger
from shared.mesh_runtime.agent_workers import build_agent_task


class CentaurLiveProofTests(unittest.TestCase):
    def test_local_http_centaur_lifecycle_records_mesh_proposal_attempt(self) -> None:
        config = RuntimeConfig(
            state_directory="/tmp/mesh-centaur-live-proof",
            vault_path="/tmp/mesh-centaur-live-proof/vault",
            integrations_config_path="/tmp/mesh-centaur-live-proof/integrations.json",
        )
        task = build_agent_task(
            run_id="run_centaur_live",
            kind="root_cause",
            allowed_paths=[],
            test_commands=[],
            kubernetes_scope={},
            agents=["codex"],
        )
        trigger = Trigger(
            trigger_id="trg_centaur_live",
            trigger_type="feature_flag_performance_regression",
            triggered_at="2026-04-14T00:00:00Z",
            environment="staging",
            service="search",
            endpoint="/search",
            flag_key="semantic_search",
            current_rollout_pct=100,
            comparison_window={"baseline": "30m", "observed": "5m"},
            segment={"customer_tier": "enterprise", "region": "us-east-1"},
            metrics={
                "baseline_p95_latency_ms": 100,
                "observed_p95_latency_ms": 200,
                "baseline_error_rate": 0.01,
                "observed_error_rate": 0.02,
                "sample_size": 1000,
            },
            related_context={"release_id": "rel_test", "active_incidents": 0, "similar_prior_cases": 0},
        )
        decision = Decision(
            decision_id="dec_centaur_live",
            trigger_id="trg_centaur_live",
            summary="Investigate",
            decision_type="investigate",
            autonomy_tier="approval_required",
            reasoning={},
            expected_outcome={},
            risk={"level": "low"},
            confidence=0.7,
            execution_plan={"system": "noop", "action": "observe", "parameters": {}},
        )
        evaluation = EvaluationResult(
            evaluation_id="eval_centaur_live",
            decision_id="dec_centaur_live",
            passed=True,
            final_recommendation="execute",
            stage_results={},
            blocking_reasons=[],
        )
        requests: list[dict[str, object]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(body)
                requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "mesh_authority": self.headers.get("X-Mesh-Authority"),
                        "payload": payload,
                    }
                )
                if self.path == "/agent/execute":
                    self._send_json(
                        {
                            "execution_id": "exec_live_1",
                            "thread_key": payload["thread_key"],
                            "assignment_generation": 1,
                            "status": "queued",
                        }
                    )
                    return
                if self.path.endswith("/release"):
                    self._send_json({"ok": True, "released": True})
                    return
                self.send_error(404)

            def do_GET(self) -> None:  # noqa: N802
                requests.append(
                    {
                        "method": "GET",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "mesh_authority": self.headers.get("X-Mesh-Authority"),
                    }
                )
                if self.path == "/agent/executions/exec_live_1":
                    self._send_json(
                        {
                            "execution_id": "exec_live_1",
                            "thread_key": "mesh:run_centaur_live:task:codex",
                            "assignment_generation": 1,
                            "status": "completed",
                            "terminal_reason": "completed",
                            "result_text": "live local Centaur-compatible proposal",
                            "error_text": "",
                            "agent_thread_id": "agent_thread_live_1",
                        }
                    )
                    return
                self.send_error(404)

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _send_json(self, payload: dict[str, object]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config.centaur_endpoint = f"http://127.0.0.1:{server.server_port}"
            config.centaur_timeout_seconds = 2.0
            config.centaur_api_key_env_name = "TEST_CENTAUR_API_KEY"
            with patch.dict("os.environ", {"TEST_CENTAUR_API_KEY": "test-key"}):
                attempt = CentaurAdapter(config).build_lane_attempt(
                    agent="codex",
                    task=task,
                    trigger=trigger,
                    decision=decision,
                    evaluation=evaluation,
                )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(attempt.adapter, "centaur")
        self.assertEqual(attempt.status, "completed")
        self.assertEqual(attempt.output["authority"]["centaur_control_plane_authoritative"], False)
        self.assertEqual(attempt.output["thread"]["events"][1]["event_type"], "centaur_execution_terminal")
        self.assertEqual(attempt.output["thread"]["events"][2]["event_type"], "centaur_thread_released")
        self.assertEqual(attempt.output["centaur_output"]["release"]["released"], True)
        self.assertEqual(requests[0]["path"], "/agent/execute")
        self.assertEqual(requests[0]["authorization"], "Bearer test-key")
        self.assertEqual(requests[0]["mesh_authority"], "proposal-only")
        self.assertEqual(requests[1]["path"], "/agent/executions/exec_live_1")
        self.assertTrue(str(requests[2]["path"]).endswith("/release"))


if __name__ == "__main__":
    unittest.main()
