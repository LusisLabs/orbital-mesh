from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.orchestrator.agent_mesh import AgentMeshService
from services.orchestrator.langgraph_adapter import LangGraphAdapter
from shared.mesh_runtime import Decision, EvaluationResult, FileStateStore, RuntimeConfig, Trigger
from shared.mesh_runtime.agent_workers import DEFAULT_AGENT_WORKERS, build_agent_task


class ZaxyLangGraphIntegrationTests(unittest.TestCase):
    def _config(self, temp_dir: str, **overrides):
        values = {
            "state_directory": temp_dir,
            "vault_path": str(Path(temp_dir) / "vault"),
            "integrations_config_path": str(Path(temp_dir) / "integrations.json"),
            "vault_mirror_mode": "off",
        }
        values.update(overrides)
        return RuntimeConfig(**values)

    def test_zaxy_eventloom_mirror_is_redacted_and_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outbox = Path(temp_dir) / "zaxy" / "eventloom.jsonl"
            store = FileStateStore(
                self._config(
                    temp_dir,
                    zaxy_enabled=True,
                    zaxy_eventloom_outbox_path=str(outbox),
                    zaxy_tenant_id="tenant-a",
                    zaxy_project_id="project-a",
                    zaxy_packet_capture_enabled=True,
                )
            )
            run = store.create_run_session(None, None, "approval_gate", False, [], "native", "native", {})

            event = store.append_run_event(
                run.run_id,
                stage="trigger_ready",
                event_type="mesh.trigger.recorded",
                payload={"service": "search", "api_token": "secret-value", "source_refs": [{"event_id": "src"}]},
                summary={"ok": True},
                artifact_key="trigger",
                integration_name="mesh",
                status="recorded",
            )

            persisted = store.list_run_events(run.run_id)
            self.assertEqual(persisted[0].event_id, event.event_id)
            line = outbox.read_text(encoding="utf-8").strip()
            mirror = json.loads(line)
            self.assertEqual(mirror["mesh"]["event_id"], event.event_id)
            self.assertEqual(mirror["scope"]["tenant_id"], "tenant-a")
            self.assertEqual(mirror["scope"]["project_id"], "project-a")
            self.assertEqual(mirror["payload"]["api_token"], "<redacted>")
            self.assertFalse(mirror["authority"]["zaxy_sidecar_authoritative"])

    def test_zaxy_checkout_is_diagnostic_until_mesh_verification_admits_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkout_path = Path(temp_dir) / "checkout.json"
            checkout_path.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "id": "zaxy_cross_tenant",
                                "content": "Search rollout memory from another tenant.",
                                "scope": {"tenant_id": "tenant-b", "service": "search"},
                                "source_refs": [{"event_id": "evt_b"}],
                                "score": 0.9,
                            },
                            {
                                "id": "zaxy_in_scope",
                                "content": "Search rollout memory with citation.",
                                "scope": {"tenant_id": "tenant-a", "service": "search"},
                                "source_refs": [{"event_id": "evt_a"}],
                                "score": 0.8,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            store = FileStateStore(
                self._config(
                    temp_dir,
                    zaxy_enabled=True,
                    zaxy_mcp_url=str(checkout_path),
                    zaxy_tenant_id="tenant-a",
                )
            )
            response = store.retrieve_memory(
                {
                    "query": "search rollout memory",
                    "scope": {"tenant_id": "tenant-a", "service": "search"},
                    "limit": 10,
                }
            )

            self.assertEqual(response["results"], [])
            self.assertEqual(response["zaxy_checkout"]["candidate_count"], 1)
            self.assertEqual(response["zaxy_checkout"]["candidates"][0]["id"], "zaxy_in_scope")
            packet = response["packet"]
            self.assertEqual(packet["observations"], [])
            self.assertEqual(packet["claims"], [])
            self.assertEqual(packet["citations"][0]["state"], "diagnostic_only")
            self.assertFalse(packet["citations"][0]["authority"]["zaxy_checkout_authoritative"])

    def test_langgraph_fabric_returns_proposal_only_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = self._config(
                temp_dir,
                agent_fabric_mode="langgraph",
                langgraph_enabled=True,
                langgraph_checkpointer_url="file:///tmp/langgraph-checkpoints",
            )
            task, trigger, decision, evaluation = _minimal_task_bundle()

            with patch.dict("sys.modules", {"langgraph": object()}):
                tasks = AgentMeshService(config=cfg).build_tasks(
                    run_id=task.run_id,
                    trigger=trigger,
                    decision=decision,
                    evaluation=evaluation,
                )

            attempts = tasks[0].attempts
            self.assertEqual([attempt.agent for attempt in attempts], list(DEFAULT_AGENT_WORKERS))
            for attempt in attempts:
                self.assertEqual(attempt.adapter, "langgraph")
                self.assertEqual(attempt.status, "completed")
                self.assertEqual(attempt.recommended_action, "human_review")
                self.assertFalse(attempt.output["authority"]["langgraph_workflow_authoritative"])
                self.assertFalse(attempt.output["authority"]["production_actuation_allowed"])
                self.assertNotIn("execution", attempt.to_dict())
                self.assertNotIn("approval", attempt.to_dict())

    def test_langgraph_missing_checkpointer_degrades_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = self._config(temp_dir, agent_fabric_mode="langgraph", langgraph_enabled=True)
            task, trigger, decision, evaluation = _minimal_task_bundle()
            attempt = LangGraphAdapter(cfg).build_lane_attempt(
                agent="codex",
                task=task,
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            )

            self.assertEqual(attempt.adapter, "langgraph")
            self.assertEqual(attempt.status, "failed")
            self.assertEqual(attempt.risk_flags, ["langgraph_checkpointer_unavailable"])


def _minimal_task_bundle():
    run_id = "run_langgraph_test"
    task = build_agent_task(run_id=run_id, kind="root_cause")
    trigger = Trigger(
        trigger_id="trg_lg",
        trigger_type="feature_flag_performance_regression",
        triggered_at="2026-04-14T00:00:00Z",
        environment="staging",
        service="search",
        endpoint="/search",
        flag_key="semantic_search",
        current_rollout_pct=100,
        comparison_window={"baseline": "30m", "observed": "5m"},
        segment={"customer_tier": "enterprise"},
        metrics={"observed_p95_latency_ms": 200},
        related_context={},
    )
    decision = Decision(
        decision_id="dec_lg",
        trigger_id="trg_lg",
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
        evaluation_id="eval_lg",
        decision_id="dec_lg",
        passed=True,
        final_recommendation="execute",
        stage_results={},
        blocking_reasons=[],
    )
    return task, trigger, decision, evaluation


if __name__ == "__main__":
    unittest.main()
