from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig, load_fixture
from tests.test_kubernetes_live_execution import _write_fake_kubectl


class ControlPlaneApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            server_host="127.0.0.1",
            server_port=0,
            vault_ai_postprocess_enabled=True,
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

    def test_research_sessions_api_lists_manifest_sessions(self) -> None:
        empty = self._request("GET", "/api/research-sessions")
        self.assertEqual(empty["sessions"], [])
        research_root = Path(self.temp_dir.name) / "research"
        session_dir = research_root / "20260101T000000Z-test"
        session_dir.mkdir(parents=True)
        (session_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "session_id": "20260101T000000Z-test",
                    "question": "Hello?",
                    "status": "minimax_multiwave_complete",
                    "minimax_route": "openai",
                    "minimax_model": "MiniMax-M2.7",
                }
            )
        )
        (session_dir / "synthesis").mkdir()
        (session_dir / "synthesis" / "final-report.md").write_text("# Report\n\nBody")
        listed = self._request("GET", "/api/research-sessions")
        self.assertEqual(len(listed["sessions"]), 1)
        self.assertEqual(listed["sessions"][0]["session_id"], "20260101T000000Z-test")
        self.assertTrue(listed["sessions"][0]["has_final_report"])
        self.assertIn("research_intelligence", listed["sessions"][0])
        detail = self._request("GET", "/api/research-sessions/20260101T000000Z-test")
        self.assertIn("Body", detail["final_report_markdown"] or "")
        self.assertIn("research_intelligence", detail)

    def test_research_sessions_api_sanitizes_and_flags_drift(self) -> None:
        research_root = Path(self.temp_dir.name) / "research"
        session_dir = research_root / "20260101T000001Z-drift"
        session_dir.mkdir(parents=True)
        (session_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "session_id": "20260101T000001Z-drift",
                    "question": "Assess Mesh Intelligence from all research",
                    "status": "complete",
                }
            )
        )
        (session_dir / "synthesis").mkdir()
        (session_dir / "synthesis" / "final-report.md").write_text(
            "<think>internal scratch</think>\n"
            "# Report\n\n"
            "1. Coverage extension for Wi-Fi, cabling, Cisco, Aruba, and SD-WAN is the primary ROI path.\n"
        )

        detail = self._request("GET", "/api/research-sessions/20260101T000001Z-drift")
        self.assertNotIn("internal scratch", detail["final_report_markdown"] or "")
        intelligence = detail["research_intelligence"]
        self.assertEqual(intelligence["classification"], "off_domain")
        self.assertIn("off_domain_drift", intelligence["flags"])
        self.assertIn("reasoning_block_redacted", intelligence["flags"])

        corpus = self._request("GET", "/api/research-corpus")
        self.assertEqual(corpus["sessions_analyzed"], 1)
        self.assertEqual(corpus["classification_counts"]["off_domain"], 1)

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
        self.assertIn(f"Insights/{run['run_id']}.md", run_paths)
        self.assertIn(f"Visualizations/{run['run_id']}.md", run_paths)
        run_note_path = f"Runs/{run['run_id']}.md"
        document = self._request(
            "GET",
            f"/api/vault/document?{urlencode({'path': run_note_path})}",
        )
        self.assertIn(run["run_id"], document["content"])
        insight_note_path = f"Insights/{run['run_id']}.md"
        visualization_note_path = f"Visualizations/{run['run_id']}.md"
        insights = self._request(
            "GET",
            f"/api/vault/document?{urlencode({'path': insight_note_path})}",
        )
        visualization = self._request(
            "GET",
            f"/api/vault/document?{urlencode({'path': visualization_note_path})}",
        )
        self.assertIn("AI Run Insight", insights["content"])
        self.assertIn("```mermaid", visualization["content"])

    def test_interruptible_auto_executes_without_operator_pause(self) -> None:
        run = self._request(
            "POST",
            "/api/runs",
            {
                "scenario_key": "search_latency_regression",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "interruptible_auto",
            },
        )
        completed = self._poll_run(run["run_id"], lambda payload: payload["stage"] == "completed")
        self.assertEqual(completed["artifacts"]["execution"]["status"], "succeeded")
        self.assertNotEqual(completed["status"], "awaiting_operator")

    def test_kubernetes_fixture_repo_placeholder_resolves_before_evaluation(self) -> None:
        run = self._request(
            "POST",
            "/api/runs",
            {
                "scenario_key": "kubernetes_crashloop_patch",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "approval_gate",
            },
        )
        paused = self._poll_run(
            run["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator" and payload["pending_pause_stage"] == "evaluation_ready",
        )
        self.assertNotEqual(
            paused["artifacts"]["input_signal"]["related_context"]["repo_path"],
            "__FIXTURE_REPO__",
        )
        self.assertTrue(paused["artifacts"]["evaluation"]["passed"])

    def test_kubernetes_fixture_repo_placeholder_uses_isolated_copy_per_run(self) -> None:
        source_repo = str(Path(__file__).resolve().parents[1] / "fixtures" / "codebases" / "search_service")
        first = self._request(
            "POST",
            "/api/runs",
            {
                "scenario_key": "kubernetes_crashloop_patch",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "approval_gate",
            },
        )
        second = self._request(
            "POST",
            "/api/runs",
            {
                "scenario_key": "kubernetes_crashloop_patch",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "approval_gate",
            },
        )
        first_paused = self._poll_run(
            first["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator" and payload["pending_pause_stage"] == "evaluation_ready",
        )
        second_paused = self._poll_run(
            second["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator" and payload["pending_pause_stage"] == "evaluation_ready",
        )
        first_repo = first_paused["artifacts"]["input_signal"]["related_context"]["repo_path"]
        second_repo = second_paused["artifacts"]["input_signal"]["related_context"]["repo_path"]

        self.assertNotEqual(first_repo, source_repo)
        self.assertNotEqual(second_repo, source_repo)
        self.assertNotEqual(first_repo, second_repo)
        self.assertTrue(Path(first_repo).exists())
        self.assertTrue(Path(second_repo).exists())

    def test_blocked_approval_includes_evaluation_reasons(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        signal["related_context"]["high_business_impact"] = True
        run = self._request(
            "POST",
            "/api/runs",
            {
                "signal_payload": signal,
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "approval_gate",
            },
        )
        self._poll_run(
            run["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator" and payload["pending_pause_stage"] == "evaluation_ready",
        )
        self._request("POST", f"/api/runs/{run['run_id']}/steer", {"command": "approve"})
        blocked = self._poll_run(
            run["run_id"],
            lambda payload: any(event["event_type"] == "approval_blocked" for event in payload["events"]),
        )
        blocked_events = [event for event in blocked["events"] if event["event_type"] == "approval_blocked"]
        self.assertTrue(blocked_events)
        self.assertEqual(blocked_events[-1]["payload"]["reason"], "evaluation did not pass")
        self.assertEqual(blocked_events[-1]["payload"]["final_recommendation"], "human_review")
        self.assertTrue(blocked_events[-1]["payload"]["blocking_reasons"])

    def test_live_kubernetes_signal_can_be_launched_via_api(self) -> None:
        fake_state_dir = Path(self.temp_dir.name) / "fake-kubectl"
        fake_state_dir.mkdir(parents=True, exist_ok=True)
        _, fake_command = _write_fake_kubectl(fake_state_dir)
        self.server.config.kubectl_command = fake_command
        self.server.coordinator.config.kubectl_command = fake_command
        run = self._request(
            "POST",
            "/api/runs",
            {
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "approval_gate",
                "live_signal": {
                    "source": "kubernetes",
                    "deployment_name": "semantic-search",
                    "namespace": "search",
                    "kube_context": "k3d-mesh-e2e",
                    "environment": "staging",
                },
            },
        )
        paused = self._poll_run(
            run["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator" and payload["pending_pause_stage"] == "evaluation_ready",
        )
        self.assertEqual(paused["scenario_key"], "live_kubernetes:search/semantic-search")
        self.assertEqual(paused["artifacts"]["input_signal"]["signal_type"], "kubernetes_deployment_issue")
        self.assertEqual(paused["artifacts"]["input_signal"]["related_context"]["kube_context"], "k3d-mesh-e2e")
        self.assertEqual(paused["artifacts"]["decision"]["decision_type"], "rollback_deployment")

    def test_readiness_reports_missing_cli_integrations(self) -> None:
        readiness = self._request("GET", "/api/readiness")
        self.assertFalse(readiness["promptfoo"]["ready"])
        self.assertFalse(readiness["goose"]["ready"])
        self.assertEqual(readiness["state_path"], self.temp_dir.name)
        self.assertEqual(readiness["vault_path"], str(Path(self.temp_dir.name) / "vault"))

    def test_rejects_oversized_json_payload(self) -> None:
        limited = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            server_host="127.0.0.1",
            server_port=0,
            max_json_body_bytes=32,
            promptfoo_command="/missing/promptfoo",
            goose_command="/missing/goose",
            gitnexus_sidecar_url="http://127.0.0.1:65535",
        )
        server, thread = start_server_in_thread(limited, start_sidecar=False)
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            payload = {"title": "x" * 200}
            request = Request(
                f"{base}/api/goals",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 413)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

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
