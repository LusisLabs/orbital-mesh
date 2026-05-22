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
from services.orchestrator.centaur_adapter import CentaurAdapter, HttpCentaurClient
from services.orchestrator.deepagents_adapter import DeepAgentsAdapter
from services.orchestrator import deepagents_adapter as deepagents_adapter_module
from services.trigger.service import TriggerService
from shared.mesh_runtime import (
    Decision,
    EvaluationResult,
    FileStateStore,
    RuntimeConfig,
    RuntimeStateStore,
    Trigger,
    build_readiness,
    load_fixture,
)
from shared.mesh_runtime.agent_workers import DEFAULT_AGENT_WORKERS, build_agent_attempt, build_agent_task


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
        self.assertEqual(adapters["goose"], "native_contract")
        self.assertEqual(adapters["hermes"], "native_contract")
        self.assertEqual(adapters["codex"], "native_contract")
        self.assertEqual(adapters["claudecode"], "native_contract")
        self.assertEqual(adapters["openclaw"], "native_contract")
        self.assertEqual(adapters["temporal"], "native_orchestration_contract")
        self.assertEqual(set(adapters), set(DEFAULT_AGENT_WORKERS))

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

    def test_agent_attempts_include_durable_thread_metadata(self) -> None:
        task, trigger, decision, evaluation = self._minimal_task_bundle()

        tasks = AgentMeshService(config=self.config).build_tasks(
            run_id=task.run_id,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
        )

        first_attempt = tasks[0].attempts[0]
        thread = first_attempt.output["thread"]
        self.assertEqual(thread["run_id"], task.run_id)
        self.assertEqual(thread["task_id"], tasks[0].task_id)
        self.assertEqual(thread["attempt_id"], first_attempt.attempt_id)
        self.assertEqual(thread["authority"]["mesh_control_plane_authoritative"], True)
        self.assertEqual(thread["authority"]["agent_thread_authoritative"], False)
        self.assertIn("stream_or_replay_events", thread["lifecycle"])
        self.assertEqual(thread["events"][0]["event_type"], "agent_attempt_terminal")
        self.assertEqual(thread["request"], {})
        self.assertEqual(thread["tool_calls"], [])
        self.assertEqual(thread["output"], {})
        self.assertEqual(thread["risk_flags"], first_attempt.risk_flags)
        self.assertEqual(thread["test_results"], first_attempt.test_results)
        self.assertEqual(thread["release_status"], {})

    def test_centaur_fabric_routes_proposal_lanes_through_sandbox_adapter(self) -> None:
        self.config.agent_fabric_mode = "centaur"
        self.config.agent_mesh_agents = ("codex",)
        task, trigger, decision, evaluation = self._minimal_task_bundle()
        requests: list[dict[str, object]] = []

        class FakeCentaurClient:
            def run_sandbox(self, request, *, timeout_seconds):
                requests.append(request)
                return {
                    "status": "completed",
                    "summary": "fake Centaur sandbox produced a bounded proposal.",
                    "recommended_action": "human_review",
                    "events": [
                        {
                            "event_id": "evt_centaur_spawn",
                            "event_type": "sandbox_spawned",
                            "recorded_at": "2026-05-21T00:00:00+00:00",
                            "status": "running",
                            "summary": {"harness": request["harness"]},
                        },
                        {
                            "event_id": "evt_centaur_result",
                            "event_type": "sandbox_completed",
                            "recorded_at": "2026-05-21T00:00:01+00:00",
                            "status": "completed",
                            "summary": {"proposal": "recorded"},
                        },
                    ],
                    "tool_calls": [{"tool_name": "mesh.lookup_run", "status": "completed"}],
                    "test_results": [{"command": "pytest", "status": "passed"}],
                    "output": {"proposal": "inspect run evidence"},
                    "citations": [{"source_type": "fake_centaur", "ref": "evt_centaur_result"}],
                }

        service = AgentMeshService(
            config=self.config,
            centaur_adapter=CentaurAdapter(self.config, client=FakeCentaurClient()),
        )
        tasks = service.build_tasks(
            run_id=task.run_id,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
        )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["mode"], "proposal_only")
        self.assertEqual(requests[0]["harness"], "codex")
        self.assertEqual(requests[0]["credential_policy"]["raw_secret_in_sandbox"], False)
        attempt = tasks[0].attempts[0]
        self.assertEqual(attempt.adapter, "centaur")
        self.assertEqual(attempt.status, "completed")
        self.assertEqual(attempt.output["authority"]["centaur_control_plane_authoritative"], False)
        self.assertEqual(attempt.output["thread"]["events"][1]["event_type"], "sandbox_completed")
        self.assertEqual(attempt.output["thread"]["request"]["run_id"], task.run_id)
        self.assertEqual(attempt.output["thread"]["tool_calls"][0]["tool_name"], "mesh.lookup_run")
        self.assertEqual(attempt.output["thread"]["output"]["proposal"], "inspect run evidence")
        self.assertEqual(attempt.output["thread"]["test_results"][0]["command"], "pytest")

    def test_http_centaur_client_uses_real_durable_lifecycle_endpoints(self) -> None:
        self.config.centaur_endpoint = "http://centaur.test"
        self.config.centaur_timeout_seconds = 3.0
        self.config.centaur_api_key_env_name = "TEST_CENTAUR_API_KEY"
        calls: list[tuple[str, str, dict[str, object] | None]] = []
        responses = [
            {
                "execution_id": "exec_1",
                "thread_key": "mesh:run:task:codex",
                "assignment_generation": 1,
                "status": "queued",
            },
            {
                "execution_id": "exec_1",
                "thread_key": "mesh:run:task:codex",
                "assignment_generation": 1,
                "status": "completed",
                "terminal_reason": "ok",
                "result_text": "bounded proposal",
                "error_text": "",
            },
            {"released": True},
        ]

        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode("utf-8")) if request.data else None
            calls.append((request.get_method(), request.full_url, body))
            return FakeResponse(responses.pop(0))

        request = {
            "state_slice": "mesh.agent_sandbox_runtime.v1",
            "thread_key": "mesh:run:task:codex",
            "run_id": "run",
            "task_id": "task",
            "agent": "codex",
            "harness": "codex",
            "authority": {"mesh_control_plane_authoritative": True},
        }
        with patch.dict("os.environ", {"TEST_CENTAUR_API_KEY": "secret"}), patch(
            "urllib.request.urlopen",
            fake_urlopen,
        ):
            result = HttpCentaurClient(self.config).run_sandbox(request, timeout_seconds=3.0)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"], "bounded proposal")
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "http://centaur.test/agent/execute")
        self.assertIn("message", calls[0][2])
        self.assertEqual(calls[1][0], "GET")
        self.assertEqual(calls[1][1], "http://centaur.test/agent/executions/exec_1")
        self.assertEqual(calls[2][0], "POST")
        self.assertEqual(calls[2][1], "http://centaur.test/agent/threads/mesh%3Arun%3Atask%3Acodex/release")
        self.assertEqual(result["events"][2]["event_type"], "centaur_thread_released")
        self.assertEqual(result["output"]["release"]["released"], True)

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
        self.assertEqual([attempt.agent for attempt in attempts], list(DEFAULT_AGENT_WORKERS))
        for attempt in attempts:
            self.assertEqual(attempt.status, "failed")
            self.assertEqual(attempt.risk_flags, ["agent_mesh_timeout"])

    def test_agent_tasks_receive_verified_memory_packets(self) -> None:
        state_store = FileStateStore(self.config)
        state_store.append_observation({
            "observation_id": "obs_memory",
            "scope": {"shared": True, "service": "search"},
            "kind": "note",
            "content": "Search service regressed after the last rollout.",
            "service": "search",
            "run_id": "run_seed",
            "source_type": "run_event",
            "source_refs": [{"run_id": "run_seed", "event_id": "evt_1"}],
            "created_at": "2026-04-16T00:00:00+00:00",
            "author": "mesh",
            "tags": ["search"],
            "metadata": {},
        })
        state_store.save_claim({
            "claim_id": "claim_memory",
            "statement": "Search rollout regressions should be reviewed with verified citations.",
            "entity_refs": ["search"],
            "supporting_observation_ids": ["obs_memory"],
            "contradicting_claim_ids": [],
            "superseded_by": None,
            "confidence": 0.84,
            "confidence_factors": {
                "support_score": 0.8,
                "recency_score": 0.8,
                "authority_score": 0.8,
                "consistency_score": 0.9,
                "verification_score": 0.9,
            },
            "freshness": 0.8,
            "tier": "semantic",
            "state": "active",
            "created_at": "2026-04-16T00:00:00+00:00",
            "updated_at": "2026-04-16T00:00:00+00:00",
        })
        task, trigger, decision, evaluation = self._minimal_task_bundle()
        tasks = AgentMeshService(config=self.config, state_store=state_store).build_tasks(
            run_id=task.run_id,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
        )
        self.assertTrue(tasks[0].memory_packet["citations"])
        self.assertEqual(tasks[0].memory_scope["service"], "search")
        self.assertEqual(tasks[0].memory_write_policy["shared_memory_mode"], "read_mostly")

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
        self.assertEqual(attempt.output["effective_model"], "openai:MiniMax-M2.7")
        self.assertEqual(attempt.output["model_binding"]["provider"], "openai")
        self.assertFalse(attempt.output["model_binding"]["secret_material_present"])

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

    # ------------------------------------------------------------------
    # Observer-fallback tests — deployments that already configure the
    # LLM observer (MESH_OBSERVER_API_KEY / MESH_OBSERVER_MODEL /
    # MESH_OBSERVER_BASE_URL) should not need to set OPENAI_API_KEY or
    # ANTHROPIC_API_KEY again for deepagents to authenticate. Provider
    # must match (we never proxy OpenAI through an Anthropic key).
    # ------------------------------------------------------------------

    def test_observer_fallback_supplies_anthropic_credentials_when_env_missing(self) -> None:
        cfg = RuntimeConfig(
            state_directory="/tmp",
            mesh_deepagents_model="anthropic:claude-3-5-sonnet-20241022",
            observer_enabled=True,
            observer_provider="anthropic",
            observer_api_key="sk-ant-fallback",
            observer_base_url="https://api.anthropic.com",
            observer_model="claude-haiku-4-5-20251001",
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            api_key, base_url = deepagents_adapter_module._resolve_deepagents_credentials(
                "anthropic:claude-3-5-sonnet-20241022", cfg,
            )
            warnings = deepagents_adapter_module._model_env_warnings(
                "anthropic:claude-3-5-sonnet-20241022", cfg,
            )
        self.assertEqual(api_key, "sk-ant-fallback")
        self.assertEqual(base_url, "https://api.anthropic.com")
        self.assertEqual(warnings, [])

    def test_observer_provider_mismatch_does_not_authorize(self) -> None:
        # Critical safety property: an OpenAI observer key must never
        # be handed to an Anthropic client (or vice versa). The observer
        # fallback is gated on provider equality.
        cfg = RuntimeConfig(
            state_directory="/tmp",
            mesh_deepagents_model="anthropic:claude-3-5-sonnet-20241022",
            observer_enabled=True,
            observer_provider="openai",
            observer_api_key="sk-openai-key",
            observer_model="gpt-4-turbo",
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            api_key, _base_url = deepagents_adapter_module._resolve_deepagents_credentials(
                "anthropic:claude-3-5-sonnet-20241022", cfg,
            )
            warnings = deepagents_adapter_module._model_env_warnings(
                "anthropic:claude-3-5-sonnet-20241022", cfg,
            )
        self.assertEqual(api_key, "")
        self.assertTrue(warnings)
        self.assertIn("ANTHROPIC_API_KEY", warnings[0])

    def test_observer_disabled_kills_credential_fallback(self) -> None:
        # Regression: a deployment that sets ``observer_enabled=False``
        # to temporarily disable the observer (while keeping the key
        # configured) must not see deepagents silently inherit those
        # credentials. The previous implementation had a redundant
        # ``observer_enabled or observer_api_key`` clause that made
        # ``observer_enabled`` dead code; fixed in
        # ``_observer_can_back``.
        cfg = RuntimeConfig(
            state_directory="/tmp",
            mesh_deepagents_model="anthropic:claude-3-5-sonnet-20241022",
            observer_enabled=False,
            observer_provider="anthropic",
            observer_api_key="sk-ant-fallback",
            observer_base_url="https://api.anthropic.com",
            observer_model="claude-haiku-4-5-20251001",
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            api_key, base_url = deepagents_adapter_module._resolve_deepagents_credentials(
                "anthropic:claude-3-5-sonnet-20241022", cfg,
            )
            warnings = deepagents_adapter_module._model_env_warnings(
                "anthropic:claude-3-5-sonnet-20241022", cfg,
            )
        self.assertEqual(api_key, "")
        self.assertEqual(base_url, "")
        self.assertTrue(warnings)

    def test_observer_disabled_kills_model_inheritance(self) -> None:
        # Same kill-switch applies to model inheritance — operator
        # turning the observer off must stop deepagents from picking
        # up ``{observer_provider}:{observer_model}`` automatically.
        cfg = RuntimeConfig(
            state_directory="/tmp",
            observer_enabled=False,
            observer_provider="anthropic",
            observer_api_key="sk-ant",
            observer_model="claude-haiku-4-5-20251001",
        )
        with patch.dict("os.environ", {"MESH_DEEPAGENTS_MODEL": ""}, clear=False):
            model = deepagents_adapter_module._resolve_deepagents_model_string(cfg)
        # Field default, not the observer-derived string.
        self.assertEqual(model, cfg.mesh_deepagents_model)

    def test_resolve_deepagents_model_string_inherits_observer_when_no_explicit_env(self) -> None:
        # Default field value, no MESH_DEEPAGENTS_MODEL env, observer
        # configured for anthropic → effective model should be derived
        # from observer_provider + observer_model.
        cfg = RuntimeConfig(
            state_directory="/tmp",
            observer_enabled=True,
            observer_provider="anthropic",
            observer_api_key="sk-ant",
            observer_model="claude-haiku-4-5-20251001",
        )
        with patch.dict("os.environ", {"MESH_DEEPAGENTS_MODEL": ""}, clear=False):
            model = deepagents_adapter_module._resolve_deepagents_model_string(cfg)
        self.assertEqual(model, "anthropic:claude-haiku-4-5-20251001")

    def test_explicit_deepagents_model_env_takes_precedence_over_observer(self) -> None:
        cfg = RuntimeConfig(
            state_directory="/tmp",
            mesh_deepagents_model="openai:gpt-4o-mini",
            observer_enabled=True,
            observer_provider="anthropic",
            observer_api_key="sk-ant",
            observer_model="claude-haiku-4-5-20251001",
        )
        with patch.dict("os.environ", {"MESH_DEEPAGENTS_MODEL": "openai:gpt-4o-mini"}, clear=False):
            model = deepagents_adapter_module._resolve_deepagents_model_string(cfg)
        self.assertEqual(model, "openai:gpt-4o-mini")

    def test_resolve_deepagents_model_passes_observer_key_to_anthropic_client(self) -> None:
        # End-to-end: build the chat-model object and verify the
        # observer's api_key + base_url are threaded through to
        # init_chat_model when the env path is empty.
        cfg = RuntimeConfig(
            state_directory="/tmp",
            mesh_deepagents_model="anthropic:claude-3-5-sonnet-20241022",
            observer_enabled=True,
            observer_provider="anthropic",
            observer_api_key="sk-ant-fallback",
            observer_base_url="https://api.anthropic.com",
            observer_model="claude-haiku-4-5-20251001",
        )
        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False),
            patch.object(deepagents_adapter_module, "init_chat_model", return_value=sentinel.model) as mock_init,
        ):
            result = deepagents_adapter_module._resolve_deepagents_model(
                "anthropic:claude-3-5-sonnet-20241022", config=cfg,
            )
        self.assertIs(result, sentinel.model)
        mock_init.assert_called_once_with(
            "anthropic:claude-3-5-sonnet-20241022",
            max_tokens=1024,
            api_key="sk-ant-fallback",
            base_url="https://api.anthropic.com",
        )

    def test_generic_openai_route_pins_use_responses_api_true(self) -> None:
        # Regression for the bug Cursor's review caught: when
        # OPENAI_API_KEY is set (or the observer fallback supplies an
        # OpenAI key), the new generic-OpenAI branch in
        # ``_resolve_deepagents_model`` pre-initializes the chat model
        # via ``init_chat_model``. Pre-fix the call omitted
        # ``use_responses_api=True``, which permanently silently
        # switched all generic-OpenAI deepagents traffic from the
        # Responses API to Chat Completions (because
        # ``create_deep_agent`` passes pre-initialized BaseChatModel
        # instances through unchanged — the harness profile that
        # would have set the flag never runs).
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-generic", "OPENAI_BASE_URL": ""}, clear=False),
            patch.object(deepagents_adapter_module, "init_chat_model", return_value=sentinel.model) as mock_init,
        ):
            result = deepagents_adapter_module._resolve_deepagents_model("openai:gpt-4o-mini")

        self.assertIs(result, sentinel.model)
        # Critical assertion: use_responses_api must be True so the
        # Responses API path stays selected on the pre-initialized
        # client.
        mock_init.assert_called_once_with(
            "openai:gpt-4o-mini",
            use_responses_api=True,
            api_key="sk-test-generic",
        )

    def test_generic_openai_route_with_observer_fallback_pins_use_responses_api(self) -> None:
        # Same regression, exercised through the observer-fallback
        # path (env unset, observer key supplies the credential).
        # Both paths must pin ``use_responses_api=True``.
        cfg = RuntimeConfig(
            state_directory="/tmp",
            mesh_deepagents_model="openai:gpt-4o-mini",
            observer_enabled=True,
            observer_provider="openai",
            observer_api_key="sk-observer-fallback",
            observer_base_url="https://api.openai.com",
            observer_model="gpt-4o-mini",
        )
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": ""}, clear=False),
            patch.object(deepagents_adapter_module, "init_chat_model", return_value=sentinel.model) as mock_init,
        ):
            result = deepagents_adapter_module._resolve_deepagents_model(
                "openai:gpt-4o-mini", config=cfg,
            )

        self.assertIs(result, sentinel.model)
        kwargs = mock_init.call_args.kwargs
        self.assertEqual(kwargs.get("use_responses_api"), True)
        self.assertEqual(kwargs.get("api_key"), "sk-observer-fallback")
        self.assertEqual(kwargs.get("base_url"), "https://api.openai.com")


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

            patcher = patch.object(DeepAgentsAdapter, "build_lane_attempt", stub_lane)
            patcher.start()
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
                    ["deepagents"] * len(DEFAULT_AGENT_WORKERS),
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
                patcher.stop()
        finally:
            temp_dir.cleanup()
