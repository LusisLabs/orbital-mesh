from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from services.control_plane import RunCoordinator
from shared.mesh_runtime import FileStateStore, RuntimeConfig, Trigger
from shared.mesh_runtime.reasoning_bank import ReasoningBankService


def _config(tmp: str, *, enabled: bool = True) -> RuntimeConfig:
    return RuntimeConfig(
        state_directory=tmp,
        vault_path=str(Path(tmp) / "vault"),
        integrations_config_path=str(Path(tmp) / "integrations.json"),
        reasoning_bank_enabled=enabled,
        reasoning_bank_max_strategies=5,
    )


def _trigger() -> Trigger:
    return Trigger(
        trigger_id="trig_1",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="2026-04-28T00:00:00+00:00",
        environment="test",
        service="search",
        endpoint="/healthz",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=None,
        segment={"customer_tier": "standard"},
        metrics={
            "baseline_p95_latency_ms": 100,
            "observed_p95_latency_ms": 250,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.05,
            "sample_size": 100,
            "desired_replicas": 2,
            "restart_count_total": 1,
        },
        related_context={
            "release_id": "rel_1",
            "active_incidents": 0,
            "similar_prior_cases": 0,
            "deployment_name": "search",
            "namespace": "default",
            "error_signatures": ["crash_loop", "redis_regression"],
            "rollout_status": "degraded",
        },
    )


class ReasoningBankTests(unittest.TestCase):
    def test_retrieval_prefers_procedural_strategy_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(_config(tmp))
            _seed_observation(store, "obs_proc", "Rollback fixed the redis regression.")
            _seed_claim(
                store,
                "claim_proc",
                "For search redis regression crash_loop, rollback_deployment is the reusable strategy.",
                tier="procedural",
                observation_id="obs_proc",
            )
            _seed_observation(store, "obs_sem", "Redis regression affected search.")
            _seed_claim(
                store,
                "claim_sem",
                "Search has redis regression history.",
                tier="semantic",
                observation_id="obs_sem",
            )

            artifact = ReasoningBankService(store, max_strategies=5).retrieve_for_trigger(_trigger())

            self.assertTrue(artifact["enabled"])
            self.assertEqual(artifact["strategies"][0]["claim_id"], "claim_proc")
            self.assertEqual(artifact["strategies"][0]["tier"], "procedural")
            self.assertIn("advisory", artifact["formatted_context"])

    def test_retrieval_falls_back_to_shared_corpus_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(_config(tmp))
            store.append_observation(
                {
                    "observation_id": "obs_corpus_shared",
                    "scope": {"shared": True, "service": "el-1-reth-lighthouse"},
                    "kind": "incident_corpus_row",
                    "content": "redis_regression crash_loop human hold from incident corpus.",
                    "service": "el-1-reth-lighthouse",
                    "run_id": "run_corpus",
                    "source_type": "incident_corpus",
                    "source_refs": [{"row_id": "row_1"}],
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "author": "test",
                    "tags": ["incident_corpus"],
                    "metadata": {},
                }
            )
            store.save_claim(
                {
                    "claim_id": "claim_corpus_shared",
                    "statement": "redis_regression crash_loop requires human review in incident corpus evidence.",
                    "entity_refs": ["el-1-reth-lighthouse", "incident_corpus", "redis_regression"],
                    "supporting_observation_ids": ["obs_corpus_shared"],
                    "contradicting_claim_ids": [],
                    "superseded_by": None,
                    "confidence": 0.8,
                    "confidence_factors": {},
                    "freshness": 0.9,
                    "tier": "semantic",
                    "state": "active",
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "updated_at": "2026-04-28T00:00:00+00:00",
                }
            )

            artifact = ReasoningBankService(store, max_strategies=5).retrieve_for_trigger(_trigger())

            self.assertTrue(artifact["enabled"])
            self.assertEqual(artifact["strategies"][0]["claim_id"], "claim_corpus_shared")

    def test_successful_run_distills_procedural_strategy_with_citations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(_config(tmp))
            run_id = _create_completed_run(store, outcome="successful", execution_status="succeeded", evaluation_passed=True)

            artifact = ReasoningBankService(store).distill_run(run_id)

            lesson = artifact["lessons"][0]
            claim = store.get_claim(lesson["claim_id"])
            observations = store.list_observations({"service": "search"}, {"kind": "reasoning_bank_lesson", "limit": 10})
            self.assertEqual(claim["tier"], "procedural")
            self.assertIn("reusable strategy", claim["statement"])
            self.assertGreater(len(lesson["source_refs"]), 0)
            self.assertTrue(observations[0]["metadata"]["reasoning_bank"])
            self.assertEqual(observations[0]["metadata"]["lesson_type"], "success_strategy")

    def test_failed_run_distills_semantic_guardrail_with_failure_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(_config(tmp))
            run_id = _create_completed_run(
                store,
                outcome="escalated",
                execution_status="skipped",
                evaluation_passed=False,
                blockers=["approval required before execution"],
            )

            artifact = ReasoningBankService(store).distill_run(run_id)

            lesson = artifact["lessons"][0]
            claim = store.get_claim(lesson["claim_id"])
            observations = store.list_observations({"service": "search"}, {"kind": "reasoning_bank_lesson", "limit": 10})
            self.assertEqual(claim["tier"], "semantic")
            self.assertIn("verify the guardrail", claim["statement"])
            self.assertEqual(observations[0]["metadata"]["failure_mode"], "approval required before execution")
            self.assertEqual(observations[0]["metadata"]["lesson_type"], "failure_guardrail")

    def test_disabled_config_writes_no_reasoning_bank_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp, enabled=False)
            coordinator = RunCoordinator(config=config, state_store=FileStateStore(config))
            artifact = coordinator._record_reasoning_bank_retrieval("missing_run", _trigger())
            self.assertFalse(artifact["enabled"])
            self.assertEqual(store_artifact_count(coordinator.state_store, "reasoning_bank_packet"), 0)

    def test_control_plane_endpoint_returns_retrieval_and_lessons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp, enabled=True)
            config.server_host = "127.0.0.1"
            config.server_port = 0
            config.promptfoo_command = "/missing/promptfoo"
            config.hermes_command = "/missing/hermes"
            config.goose_command = "/missing/goose"
            config.evo_command = "/missing/evo"
            server, thread = start_server_in_thread(config, start_sidecar=False)
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                run_id = _create_completed_run(
                    server.coordinator.state_store,
                    outcome="escalated",
                    execution_status="skipped",
                    evaluation_passed=False,
                    blockers=["approval required before execution"],
                )
                session = server.coordinator.state_store.get_run_session(run_id)
                assert session is not None
                session.artifacts["reasoning_bank_packet"] = {
                    "enabled": True,
                    "packet": {"packet_id": "mpkt_test", "claims": [], "procedures": []},
                    "strategies": [],
                }
                server.coordinator.state_store.save_run_session(session)

                payload = _http_json(base_url, "GET", f"/api/runs/{run_id}/reasoning-bank")

                self.assertTrue(payload["enabled"])
                self.assertIsNotNone(payload["retrieval"])
                self.assertIsNotNone(payload["lessons"])
                self.assertGreaterEqual(len(payload["lessons"]["lessons"]), 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


def _seed_observation(store: FileStateStore, observation_id: str, content: str) -> None:
    store.append_observation(
        {
            "observation_id": observation_id,
            "scope": {"shared": True, "service": "search"},
            "kind": "note",
            "content": content,
            "service": "search",
            "run_id": "run_seed",
            "source_type": "test",
            "source_refs": [{"run_id": "run_seed", "event_id": "evt_seed"}],
            "created_at": "2026-04-28T00:00:00+00:00",
            "author": "test",
            "tags": ["reasoning_bank"],
            "metadata": {},
        }
    )


def _seed_claim(store: FileStateStore, claim_id: str, statement: str, *, tier: str, observation_id: str) -> None:
    store.save_claim(
        {
            "claim_id": claim_id,
            "statement": statement,
            "entity_refs": ["search", "kubernetes_deployment_unhealthy", "reasoning_bank"],
            "supporting_observation_ids": [observation_id],
            "contradicting_claim_ids": [],
            "superseded_by": None,
            "confidence": 0.91,
            "confidence_factors": {
                "support_score": 0.9,
                "recency_score": 0.9,
                "authority_score": 0.9,
                "consistency_score": 0.9,
                "verification_score": 0.9,
            },
            "freshness": 0.9,
            "tier": tier,
            "state": "active",
            "created_at": "2026-04-28T00:00:00+00:00",
            "updated_at": "2026-04-28T00:00:00+00:00",
        }
    )


def _create_completed_run(
    store: FileStateStore,
    *,
    outcome: str,
    execution_status: str,
    evaluation_passed: bool,
    blockers: list[str] | None = None,
) -> str:
    trigger = _trigger().to_dict()
    decision = {
        "decision_id": "dec_1",
        "trigger_id": "trig_1",
        "decision_type": "rollback_deployment",
        "summary": "Rollback search.",
        "autonomy_tier": "autonomous",
        "reasoning": {},
        "expected_outcome": {},
        "risk": {},
        "confidence": 0.84,
        "execution_plan": {},
    }
    session = store.create_run_session(
        goal_id=None,
        scenario_key="reasoning_bank_test",
        steering_mode="interruptible_auto",
        auto_mode=True,
        pause_points=[],
        evaluation_mode="native",
        orchestration_mode="native",
        artifacts={
            "trigger": trigger,
            "decision": decision,
            "evaluation": {"passed": evaluation_passed, "blocking_reasons": blockers or []},
            "execution": {"status": execution_status},
            "feedback": {"outcome": outcome},
        },
    )
    for stage, event_type in (
        ("trigger_ready", "trigger_ready"),
        ("decision_ready", "decision_ready"),
        ("evaluation_ready", "evaluation_ready"),
        ("executing", "execution_recorded"),
        ("feedback_ready", "feedback_recorded"),
        ("completed", "run_completed"),
    ):
        store.append_run_event(
            session.run_id,
            stage=stage,
            event_type=event_type,
            payload={"service": "search"},
            artifact_key=stage,
            status="recorded",
        )
    session = store.get_run_session(session.run_id)
    assert session is not None
    session.stage = "completed"
    session.status = "completed"
    store.save_run_session(session)
    return session.run_id


def store_artifact_count(store: FileStateStore, artifact_key: str) -> int:
    return sum(
        1
        for session in store.list_run_sessions(limit=20)
        if artifact_key in session.artifacts
    )


def _http_json(base_url: str, method: str, path: str, payload: dict | None = None) -> dict:
    body = None
    headers = {}
    if payload is not None:
        import json

        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=body, method=method, headers=headers)
    with urlopen(request, timeout=10) as response:
        import json

        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
