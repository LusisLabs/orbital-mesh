from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, sentinel
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from services.decision.service import DecisionService
from services.evaluation.service import EvaluationService
from services.ingest.service import IngestService
from services.orchestrator.agent_mesh import AgentMeshService
from services.orchestrator.deepagents_adapter import DeepAgentsAdapter
from services.orchestrator import deepagents_adapter as deepagents_adapter_module
from services.trigger.service import TriggerService
from shared.mesh_runtime import (
    Decision,
    EvaluationResult,
    RuntimeConfig,
    RuntimeStateStore,
    Trigger,
    build_readiness,
    load_fixture,
)
from shared.mesh_runtime.agent_workers import build_agent_attempt, build_agent_task


class DeepAgentsAgentMeshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
            evo_command="/missing/evo",
            mesh_deepagents_workspace_root=str(Path(self.temp_dir.name) / "da-ws"),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _minimal_task_bundle(self):
        run_id = "run_da_test"
        task = build_agent_task(
            run_id=run_id,
            kind="root_cause",
            allowed_paths=[],
            test_commands=[],
            kubernetes_scope={},
        )
        trigger = Trigger(
            trigger_id="trg_da",
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
            related_context={
                "release_id": "rel_test",
                "active_incidents": 0,
                "similar_prior_cases": 0,
            },
        )
        decision = Decision(
            decision_id="dec_da",
            trigger_id="trg_da",
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
            evaluation_id="eval_da",
            decision_id="dec_da",
            passed=True,
            final_recommendation="execute",
            stage_results={},
            blocking_reasons=[],
        )
        return task, trigger, decision, evaluation

    def test_native_fabric_preserves_native_adapter(self) -> None:
        task, trigger, decision, evaluation = self._minimal_task_bundle()
        tasks = AgentMeshService(config=self.config).build_tasks(
            run_id=task.run_id,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
        )
        adapters = {a.agent: a.adapter for a in tasks[0].attempts}
        self.assertEqual(
            adapters,
            {
                "goose": "native_contract",
                "hermes": "native_contract",
                "codex": "native_contract",
                "claudecode": "native_contract",
                "openclaw": "native_contract",
                "evo": "native_contract",
            },
        )

    def test_deepagents_fabric_uses_deepagents_adapter(self) -> None:
        self.config.agent_fabric_mode = "deepagents"
        task, trigger, decision, evaluation = self._minimal_task_bundle()

        def stub_lane(_self, *, agent, task, trigger, decision, evaluation):
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent=agent,
                adapter="deepagents",
                status="completed",
                summary=f"stub-{agent}",
                risk_flags=[],
                recommended_action="human_review",
                output={"workspace_path": str(Path(self.config.mesh_deepagents_workspace_root)), "diff": ""},
            )
        with patch.object(DeepAgentsAdapter, "build_lane_attempt", stub_lane):
            tasks = AgentMeshService(config=self.config).build_tasks(
                run_id=task.run_id,
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )
        for attempt in tasks[0].attempts:
            self.assertEqual(attempt.adapter, "deepagents")

    def test_deepagents_collection_timeout_degrades_lane_without_blocking(self) -> None:
        self.config.agent_fabric_mode = "deepagents"
        self.config.agent_mesh_task_timeout_seconds = 0.05
        task, trigger, decision, evaluation = self._minimal_task_bundle()

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

        started = time.monotonic()
        with patch.object(DeepAgentsAdapter, "build_lane_attempt", slow_lane):
            tasks = AgentMeshService(config=self.config).build_tasks(
                run_id=task.run_id,
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.2)
        attempts = tasks[0].attempts
        self.assertEqual([attempt.agent for attempt in attempts], ["goose", "hermes", "codex", "claudecode", "openclaw", "evo"])
        for attempt in attempts:
            self.assertEqual(attempt.status, "failed")
            self.assertEqual(attempt.risk_flags, ["agent_mesh_timeout"])

    def test_deepagents_latentmas_still_prepended(self) -> None:
        self.config.agent_fabric_mode = "deepagents"
        self.config.latentmas_enabled = True
        self.config.latentmas_url = "http://127.0.0.1:9"
        self.config.latentmas_timeout_seconds = 0.1

        def stub_lane(_self, *, agent, task, trigger, decision, evaluation):
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent=agent,
                adapter="deepagents",
                status="completed",
                summary="stub",
                risk_flags=[],
                recommended_action="human_review",
                output={},
            )

        signal = load_fixture("signals", "search_latency_regression.json")
        normalized = IngestService().normalize_signal(signal)
        trigger = TriggerService().detect(normalized)
        assert trigger is not None
        decision = DecisionService().decide(trigger)
        evaluation = EvaluationService(
            config=self.config,
            state_store=RuntimeStateStore(self.temp_dir.name),
        ).evaluate(trigger, decision)
        task = build_agent_task(
            run_id="run_latent_da",
            kind="root_cause",
            allowed_paths=[],
            test_commands=[],
            kubernetes_scope={},
        )
        with patch.object(DeepAgentsAdapter, "build_lane_attempt", stub_lane):
            tasks = AgentMeshService(config=self.config).build_tasks(
                run_id=task.run_id,
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )
        agents = [a.agent for a in tasks[0].attempts]
        self.assertEqual(agents[0], "latentmas")
        self.assertEqual(agents[1], "goose")
        self.assertEqual(tasks[0].attempts[1].adapter, "deepagents")

    def test_deepagents_dependency_missing_records_failed_attempt(self) -> None:
        self.config.agent_fabric_mode = "deepagents"
        task, trigger, decision, evaluation = self._minimal_task_bundle()
        with patch.object(deepagents_adapter_module, "_import_deepagents", side_effect=ImportError("no deepagents")):
            attempt = DeepAgentsAdapter(self.config).build_lane_attempt(
                agent="goose",
                task=task,
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )
        self.assertEqual(attempt.adapter, "deepagents")
        self.assertEqual(attempt.status, "failed")
        self.assertIn("deepagents_dependency_missing", attempt.risk_flags)

    def test_copy_allowed_workspace_only_includes_existing_allowed_files(self) -> None:
        repo = Path(self.temp_dir.name) / "repo"
        allowed_dir = repo / "svc"
        allowed_dir.mkdir(parents=True)
        (allowed_dir / "ok.py").write_text("print(1)\n", encoding="utf-8")
        workspace = Path(self.temp_dir.name) / "ws"
        snap = deepagents_adapter_module._copy_allowed_workspace(
            repo_root=repo,
            allowed_paths=["svc/ok.py", "missing.py", "../escape.py"],
            workspace=workspace,
        )
        self.assertEqual(set(snap.keys()), {"svc/ok.py"})
        self.assertTrue((workspace / "svc" / "ok.py").is_file())
        self.assertFalse((workspace / "missing.py").exists())

    def test_disallowed_workspace_files_detects_strays(self) -> None:
        task = build_agent_task(
            run_id="run_x",
            kind="patch",
            allowed_paths=["a.txt"],
            test_commands=[],
            kubernetes_scope={},
        )
        ws = Path(self.temp_dir.name) / "w"
        ws.mkdir()
        (ws / "a.txt").write_text("x", encoding="utf-8")
        (ws / "evil.txt").write_text("y", encoding="utf-8")
        bad = deepagents_adapter_module._disallowed_workspace_files(task, ws)
        self.assertIn("evil.txt", bad)

    def test_artifact_truncation_on_outputs(self) -> None:
        self.config.mesh_deepagents_max_artifact_chars = 20
        adapter = DeepAgentsAdapter(self.config)
        long_text = "x" * 100
        self.assertTrue(len(adapter._cap_text(long_text)) <= 35)  # 20 + newline + [truncated]

    def test_readiness_deepagents_disabled_by_default(self) -> None:
        r = build_readiness(self.config)
        self.assertFalse(r.deepagents.ready)
        self.assertIn("not deepagents", r.deepagents.detail.lower())

    def test_readiness_deepagents_reports_package_when_enabled(self) -> None:
        self.config.agent_fabric_mode = "deepagents"
        r = build_readiness(self.config)
        self.assertTrue(r.deepagents.ready)
        self.assertIn("fabric=deepagents", r.deepagents.detail)

    def test_resolve_deepagents_model_uses_chat_completions_for_minimax_route(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"OPENAI_BASE_URL": "https://api.minimax.io/v1", "OPENAI_API_KEY": "sk-test"},
                clear=False,
            ),
            patch.object(deepagents_adapter_module, "init_chat_model", return_value=sentinel.model) as mock_init,
        ):
            model = deepagents_adapter_module._resolve_deepagents_model("openai:MiniMax-M2.7")
        self.assertIs(model, sentinel.model)
        mock_init.assert_called_once_with(
            "openai:MiniMax-M2.7",
            use_responses_api=False,
            base_url="https://api.minimax.io/v1",
            api_key="sk-test",
        )

    def test_resolve_deepagents_model_uses_minimax_api_key_fallback(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "OPENAI_BASE_URL": "https://api.minimax.io/v1",
                    "OPENAI_API_KEY": "",
                    "MINIMAX_API_KEY": "minimax-test",
                },
                clear=False,
            ),
            patch.object(deepagents_adapter_module, "init_chat_model", return_value=sentinel.model) as mock_init,
        ):
            model = deepagents_adapter_module._resolve_deepagents_model("openai:MiniMax-M2.7")
        self.assertIs(model, sentinel.model)
        mock_init.assert_called_once_with(
            "openai:MiniMax-M2.7",
            use_responses_api=False,
            base_url="https://api.minimax.io/v1",
            api_key="minimax-test",
        )

    def test_model_env_warnings_accept_minimax_api_key_fallback(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "", "MINIMAX_API_KEY": "minimax-test"},
            clear=False,
        ):
            warnings = deepagents_adapter_module._model_env_warnings("openai:MiniMax-M2.7")
        self.assertEqual(warnings, [])

    def test_resolve_deepagents_model_preserves_plain_openai_string_off_minimax_route(self) -> None:
        with (
            patch.dict("os.environ", {"OPENAI_BASE_URL": ""}, clear=False),
            patch.object(deepagents_adapter_module, "init_chat_model") as mock_init,
        ):
            model = deepagents_adapter_module._resolve_deepagents_model("openai:gpt-4o-mini")
        self.assertEqual(model, "openai:gpt-4o-mini")
        mock_init.assert_not_called()


class DeepAgentsControlPlaneHttpTests(unittest.TestCase):
    def test_completed_run_records_deepagents_attempts_when_mocked(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        try:
            config = RuntimeConfig(
                state_directory=temp_dir.name,
                vault_path=str(Path(temp_dir.name) / "vault"),
                integrations_config_path=str(Path(temp_dir.name) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                vault_ai_postprocess_enabled=False,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
                agent_fabric_mode="deepagents",
            )

            def stub_lane(_self, *, agent, task, trigger, decision, evaluation):
                return build_agent_attempt(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    agent=agent,
                    adapter="deepagents",
                    status="completed",
                    summary=f"stub-{agent}",
                    risk_flags=[],
                    recommended_action="human_review",
                    output={"diff": "", "workspace_path": "/tmp/mesh-da", "deepagents_final_message": "{}"},
                )

            with patch.object(DeepAgentsAdapter, "build_lane_attempt", stub_lane):
                server, thread = start_server_in_thread(config, start_sidecar=False)
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                req = Request(
                    f"{base}/api/runs",
                    data=json.dumps(
                        {
                            "scenario_key": "search_latency_regression",
                            "evaluation_mode": "native",
                            "orchestration_mode": "native",
                            "steering_mode": "interruptible_auto",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=30) as resp:
                    run = json.loads(resp.read().decode("utf-8"))
                run_id = run["run_id"]
                for _ in range(120):
                    with urlopen(f"{base}/api/runs/{run_id}", timeout=10) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                    if payload.get("stage") == "completed":
                        completed = payload
                        break
                    time.sleep(0.25)
                else:
                    raise AssertionError("run did not complete")

                attempts = completed["artifacts"]["agent_tasks"][0]["attempts"]
                self.assertTrue(all(a["adapter"] == "deepagents" for a in attempts))
                api_tasks = json.loads(
                    urlopen(f"{base}/api/runs/{run_id}/agent-tasks", timeout=10).read().decode("utf-8")
                )["tasks"]
                self.assertEqual(
                    [a["adapter"] for a in api_tasks[0]["attempts"]],
                    ["deepagents"] * 6,
                )

                agent_note = json.loads(
                    urlopen(
                        f"{base}/api/vault/document?{urlencode({'path': f'Agents/{run_id}.md'})}",
                        timeout=10,
                    )
                    .read()
                    .decode("utf-8")
                )
                self.assertIn("deepagents", agent_note["content"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            temp_dir.cleanup()
