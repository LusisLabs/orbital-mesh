from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig


class ControlPlaneApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            server_host="127.0.0.1",
            server_port=0,
            promptfoo_command="/missing/promptfoo",
            goose_command="/missing/goose",
            gitnexus_sidecar_url="http://127.0.0.1:65535",
        )
        self.server, self.thread = start_server_in_thread(self.config, start_sidecar=False)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_approval_gate_http_flow_writes_vault_and_merkle(self) -> None:
        goal = self._request(
            "POST",
            "/api/goals",
            {
                "title": "Protect search latency",
                "objective": "Keep rollout remediation steerable before execution.",
                "success_criteria": ["Approval gate pauses before actuation."],
                "tags": ["latency", "ops"],
            },
        )
        run = self._request(
            "POST",
            "/api/runs",
            {
                "goal_id": goal["goal_id"],
                "scenario_key": "search_latency_regression",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "approval_gate",
            },
        )
        paused = self._poll_run(
            run["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator" and payload["pending_pause_stage"] == "evaluation_ready",
        )
        self.assertNotIn("execution", paused["artifacts"])

        override = self._request(
            "POST",
            f"/api/runs/{run['run_id']}/steer",
            {"command": "override_execution_parameters", "parameters": {"rollout_pct": 5}},
        )
        reevaluated = self._poll_run(
            run["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator"
            and payload["artifacts"]["decision"]["execution_plan"]["parameters"]["rollout_pct"] == 5
            and len([event for event in payload["events"] if event["event_type"] == "evaluation_ready"]) >= 2,
        )
        self.assertEqual(
            reevaluated["artifacts"]["decision"]["execution_plan"]["parameters"]["rollout_pct"],
            5,
        )
        self.assertEqual(override["run_id"], run["run_id"])

        self._request("POST", f"/api/runs/{run['run_id']}/steer", {"command": "approve"})
        completed = self._poll_run(run["run_id"], lambda payload: payload["stage"] == "completed")
        self.assertEqual(completed["artifacts"]["execution"]["status"], "succeeded")

        events = self._request("GET", f"/api/runs/{run['run_id']}/events")["events"]
        decision_event = next(event for event in events if event["event_type"] == "decision_ready")
        merkle = self._request("GET", f"/api/runs/{run['run_id']}/merkle")
        proof = self._request(
            "GET",
            f"/api/runs/{run['run_id']}/merkle/proof/{decision_event['event_id']}",
        )
        self.assertTrue(proof["valid"])
        self.assertEqual(proof["root_hash"], merkle["root_hash"])

        tree = self._request("GET", "/api/vault/tree")["tree"]
        run_paths = self._flatten_tree(tree)
        self.assertIn(f"Runs/{run['run_id']}.md", run_paths)
        run_note_path = f"Runs/{run['run_id']}.md"
        document = self._request(
            "GET",
            f"/api/vault/document?{urlencode({'path': run_note_path})}",
        )
        self.assertIn(run["run_id"], document["content"])

    def test_interruptible_auto_executes_without_operator_pause(self) -> None:
        run = self._request(
            "POST",
            "/api/runs",
            {
                "scenario_key": "search_latency_regression",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "interruptible_auto",
                "pause_points": [],
            },
        )
        completed = self._poll_run(run["run_id"], lambda payload: payload["stage"] == "completed")
        self.assertEqual(completed["artifacts"]["execution"]["status"], "succeeded")
        self.assertNotEqual(completed["status"], "awaiting_operator")

    def test_readiness_reports_missing_cli_integrations(self) -> None:
        readiness = self._request("GET", "/api/readiness")
        self.assertFalse(readiness["promptfoo"]["ready"])
        self.assertFalse(readiness["goose"]["ready"])
        self.assertEqual(readiness["state_path"], self.temp_dir.name)
        self.assertEqual(readiness["vault_path"], str(Path(self.temp_dir.name) / "vault"))

    def _poll_run(self, run_id: str, predicate, timeout_seconds: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = self._request("GET", f"/api/runs/{run_id}")
            if predicate(payload):
                return payload
            time.sleep(0.1)
        raise AssertionError(f"run {run_id} did not satisfy predicate before timeout")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _flatten_tree(self, nodes: list[dict]) -> list[str]:
        paths: list[str] = []
        for node in nodes:
            paths.append(node["path"])
            if node.get("children"):
                paths.extend(self._flatten_tree(node["children"]))
        return paths


if __name__ == "__main__":
    unittest.main()
