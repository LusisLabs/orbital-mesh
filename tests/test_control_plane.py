from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

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
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
            evo_command="/missing/evo",
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

    def test_agent_mesh_tasks_are_recorded_and_exposed(self) -> None:
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
        tasks = completed["artifacts"]["agent_tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(
            [attempt["agent"] for attempt in tasks[0]["attempts"]],
            ["goose", "hermes", "codex", "claudecode", "openclaw", "evo"],
        )
        evo_attempt = tasks[0]["attempts"][-1]
        self.assertEqual(evo_attempt["adapter"], "native_contract")
        self.assertEqual(evo_attempt["recommended_action"], "human_review")
        self.assertIn("evo_cli_missing", evo_attempt["risk_flags"])
        self.assertTrue(tasks[0]["selected_attempt_id"])

        api_tasks = self._request("GET", f"/api/runs/{run['run_id']}/agent-tasks")["tasks"]
        self.assertEqual(api_tasks[0]["task_id"], tasks[0]["task_id"])

        agent_events = [event for event in completed["events"] if event["event_type"] == "agent_task_recorded"]
        self.assertTrue(agent_events)
        self.assertEqual(agent_events[-1]["integration_name"], "agent_mesh")

        agent_note_path = f"Agents/{run['run_id']}.md"
        document = self._request(
            "GET",
            f"/api/vault/document?{urlencode({'path': agent_note_path})}",
        )
        self.assertIn("Agent Mesh", document["content"])
        self.assertIn("native_contract", document["content"])
        self.assertIn("\"agent\": \"evo\"", document["content"])

    def test_latentmas_unavailable_does_not_block_control_plane_run(self) -> None:
        self.server.config.latentmas_enabled = True
        self.server.config.latentmas_url = "http://127.0.0.1:9"
        self.server.config.latentmas_timeout_seconds = 0.2
        self.server.coordinator.config.latentmas_enabled = True
        self.server.coordinator.config.latentmas_url = "http://127.0.0.1:9"
        self.server.coordinator.config.latentmas_timeout_seconds = 0.2
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
        attempts = completed["artifacts"]["agent_tasks"][0]["attempts"]
        self.assertEqual(attempts[0]["agent"], "latentmas")
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertEqual(attempts[0]["risk_flags"], ["latentmas_unavailable"])
        self.assertEqual(completed["artifacts"]["execution"]["status"], "succeeded")

    def test_slow_deepagents_proposal_lanes_do_not_block_run_execution(self) -> None:
        for cfg in (self.server.config, self.server.coordinator.config):
            cfg.agent_fabric_mode = "deepagents"
            cfg.agent_mesh_task_timeout_seconds = 0.05

        def slow_lane(_self, *, agent, task, trigger, decision, evaluation):
            time.sleep(0.2)
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent=agent,
                adapter="deepagents",
                status="completed",
                summary=f"slow-{agent}",
                risk_flags=[],
                recommended_action="human_review",
                output={},
            )

        with patch("services.orchestrator.deepagents_adapter.DeepAgentsAdapter.build_lane_attempt", slow_lane):
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
        attempts = completed["artifacts"]["agent_tasks"][0]["attempts"]
        self.assertEqual([attempt["agent"] for attempt in attempts], ["goose", "hermes", "codex", "claudecode", "openclaw", "evo"])
        for attempt in attempts:
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(attempt["risk_flags"], ["agent_mesh_timeout"])

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
        self.assertIn(paused["artifacts"]["decision"]["decision_type"], ("rollback_deployment", "restart_deployment"))

    def test_readiness_reports_missing_cli_integrations(self) -> None:
        readiness = self._request("GET", "/api/readiness")
        self.assertFalse(readiness["promptfoo"]["ready"])
        self.assertFalse(readiness["hermes"]["ready"])
        self.assertFalse(readiness["goose"]["ready"])
        self.assertFalse(readiness["evo"]["ready"])
        self.assertEqual(readiness["evo"]["detail"], "command not found")
        self.assertFalse(readiness["latentmas"]["ready"])
        self.assertEqual(readiness["latentmas"]["detail"], "disabled")
        self.assertFalse(readiness["deepagents"]["ready"])
        self.assertIn("not deepagents", readiness["deepagents"]["detail"].lower())
        self.assertEqual(readiness["state_path"], self.temp_dir.name)
        self.assertEqual(readiness["vault_path"], str(Path(self.temp_dir.name) / "vault"))

    def test_launch_evo_records_run_scoped_launch_artifact(self) -> None:
        repo = Path(self.temp_dir.name) / "evo-repo"
        (repo / "app").mkdir(parents=True)
        (repo / "tests").mkdir(parents=True)
        (repo / "app" / "search.py").write_text("PARSE_TIMEOUT_MS = 120\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "mesh@example.com"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Mesh"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

        fake_evo = Path(self.temp_dir.name) / "evo"
        fake_evo.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_evo.chmod(0o755)
        for cfg in (self.server.config, self.server.coordinator.config, self.server.coordinator.evo_launcher.config):
            cfg.evo_command = str(fake_evo)

        signal = load_fixture("signals", "kubernetes_crashloop_patch.json")
        signal["related_context"]["repo_path"] = str(repo)
        signal["related_context"]["allowed_paths"] = ["app/search.py"]
        signal["related_context"]["test_commands"] = ["python3 -m unittest discover -s tests"]

        def fake_run(
            args: list[str],
            cwd: Path | str | None = None,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
            timeout: int | float | None = None,
        ) -> subprocess.CompletedProcess[str]:
            if args == [str(fake_evo), "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="evo-hq-cli 0.2.0\n", stderr="")
            if len(args) >= 3 and args[1] == "-m":
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="command not found")
            if args == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            if args[:2] == [str(fake_evo), "init"]:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout="Dashboard live: http://127.0.0.1:8080 (pid 12345)\nInitialized evo workspace run_1\n",
                    stderr="",
                )
            if args[:2] == [str(fake_evo), "new"]:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout=json.dumps({"id": "exp_0000", "worktree": "/tmp/worktree", "target": str(repo / "app" / "search.py")}),
                    stderr="",
                )
            if args[:2] == [str(fake_evo), "run"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="COMMITTED exp_0000 0.73\n", stderr="")
            raise AssertionError(f"unexpected subprocess args: {args}")

        with patch("subprocess.run", side_effect=fake_run):
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
            self._request(
                "POST",
                f"/api/runs/{run['run_id']}/steer",
                {
                    "command": "launch_evo",
                    "target_path": "app/search.py",
                    "benchmark_command": "python3 benchmark.py --target {target}",
                    "instrumentation_mode": "inline",
                    "metric": "max",
                    "gate_command": "python3 -m unittest discover -s tests",
                },
            )
            updated = self._poll_run(
                run["run_id"],
                lambda payload: payload["artifacts"].get("evo_launches", {}).get("launches", [{}])[0].get("status") == "completed",
            )

        launch = updated["artifacts"]["evo_launches"]["launches"][0]
        self.assertEqual(launch["action"], "discover_bootstrap")
        self.assertEqual(launch["status"], "completed")
        self.assertEqual(launch["experiment_id"], "exp_0000")
        self.assertEqual(launch["dashboard_url"], "http://127.0.0.1:8080")
        self.assertEqual(len(launch["steps"]), 3)
        evo_events = [event for event in updated["events"] if event.get("integration_name") == "evo"]
        self.assertTrue(evo_events)
        evo_doc_path = f"Evo/{run['run_id']}.md"
        evo_doc = self._request("GET", f"/api/vault/document?{urlencode({'path': evo_doc_path})}")
        self.assertIn("discover_bootstrap", evo_doc["content"])

    def test_launch_evo_rejects_missing_benchmark_for_new_workspace(self) -> None:
        repo = Path(self.temp_dir.name) / "evo-repo-no-benchmark"
        (repo / "app").mkdir(parents=True)
        (repo / "app" / "search.py").write_text("PARSE_TIMEOUT_MS = 120\n", encoding="utf-8")
        fake_evo = Path(self.temp_dir.name) / "evo"
        fake_evo.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_evo.chmod(0o755)
        for cfg in (self.server.config, self.server.coordinator.config, self.server.coordinator.evo_launcher.config):
            cfg.evo_command = str(fake_evo)

        signal = load_fixture("signals", "kubernetes_crashloop_patch.json")
        signal["related_context"]["repo_path"] = str(repo)
        signal["related_context"]["allowed_paths"] = ["app/search.py"]
        signal["related_context"]["test_commands"] = ["python3 -m unittest discover -s tests"]

        def fake_run(
            args: list[str],
            cwd: Path | str | None = None,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
            timeout: int | float | None = None,
        ) -> subprocess.CompletedProcess[str]:
            if args == [str(fake_evo), "--version"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="evo-hq-cli 0.2.0\n", stderr="")
            if len(args) >= 3 and args[1] == "-m":
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="command not found")
            raise AssertionError(f"unexpected subprocess args: {args}")

        with patch("subprocess.run", side_effect=fake_run):
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
            bad = Request(
                f"{self.base_url}/api/runs/{run['run_id']}/steer",
                data=json.dumps({"command": "launch_evo", "target_path": "app/search.py"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(bad, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_unknown_scenario_key_returns_400_json(self) -> None:
        request = Request(
            f"{self.base_url}/api/runs",
            data=json.dumps(
                {
                    "scenario_key": "does_not_exist_fixture",
                    "evaluation_mode": "native",
                    "orchestration_mode": "native",
                    "steering_mode": "interruptible_auto",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request, timeout=10)
        err = ctx.exception
        self.assertEqual(err.code, 400)
        body = json.loads(err.read().decode("utf-8"))
        self.assertIn("error", body)
        self.assertIn("does_not_exist_fixture", body["error"])

    def test_steering_rejects_decision_override_before_evaluation_gate(self) -> None:
        run = self._request(
            "POST",
            "/api/runs",
            {
                "scenario_key": "search_latency_regression",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "approval_gate",
                "pause_points": ["trigger_ready", "evaluation_ready"],
            },
        )
        paused = self._poll_run(
            run["run_id"],
            lambda payload: payload["stage"] == "awaiting_operator"
            and payload.get("pending_pause_stage") == "trigger_ready",
        )
        self.assertEqual(paused["pending_pause_stage"], "trigger_ready")
        bad = Request(
            f"{self.base_url}/api/runs/{run['run_id']}/steer",
            data=json.dumps(
                {
                    "command": "override_decision",
                    "decision_type": "disable_flag",
                    "summary": "should not apply at trigger",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(bad, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

        cancel = Request(
            f"{self.base_url}/api/runs/{run['run_id']}/steer",
            data=json.dumps({"command": "cancel"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(cancel, timeout=10) as response:
            self.assertEqual(response.status, 200)
        cancelled = self._poll_run(
            run["run_id"],
            lambda payload: payload["stage"] == "cancelled",
            timeout_seconds=15.0,
        )
        self.assertEqual(cancelled["status"], "cancelled")

    def test_steering_rejects_commands_on_terminal_run(self) -> None:
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
        self._poll_run(run["run_id"], lambda payload: payload["stage"] == "completed")
        bad = Request(
            f"{self.base_url}/api/runs/{run['run_id']}/steer",
            data=json.dumps({"command": "approve"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(bad, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_rejects_oversized_json_payload(self) -> None:
        limited = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            server_host="127.0.0.1",
            server_port=0,
            max_json_body_bytes=32,
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
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
