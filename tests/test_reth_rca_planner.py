from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.evidence import EvidenceService
from services.investigation import RethInvestigationPlanner
from services.runtime import MeshRuntimeEngine
from services.trigger.service import TriggerService
from services.ingest.service import IngestService
from shared.mesh_runtime import RuntimeConfig


_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "signals"


def _reth_signal(name: str = "reth_peer_starvation.json") -> dict:
    payload = json.loads((_FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    payload.pop("endpoint", None)
    return payload


def _trigger(signal: dict):
    envelope = IngestService().normalize_signal(signal)
    trigger = TriggerService().detect(envelope)
    assert trigger is not None
    return trigger


class RethPlannerTests(unittest.TestCase):
    def test_native_planner_selects_signature_specific_read_only_probes(self) -> None:
        signal = _reth_signal()
        trigger = _trigger(signal)
        planner = RethInvestigationPlanner(RuntimeConfig(reth_investigation_max_probes=6))

        plan = planner.plan(trigger=trigger, signal_payload=signal)

        self.assertIsNotNone(plan)
        names = {probe["name"] for probe in plan.to_dict()["probes"]}
        self.assertIn("json_rpc_peer_sync", names)
        self.assertIn("json_rpc_rpc_health", names)
        self.assertIn("consensus_status", names)
        self.assertTrue(all(probe["read_only"] for probe in plan.to_dict()["probes"]))

    def test_llm_planner_unknown_probe_falls_back_to_native(self) -> None:
        signal = _reth_signal()
        trigger = _trigger(signal)
        planner = RethInvestigationPlanner(
            RuntimeConfig(
                reth_investigation_planner="llm",
                observer_base_url="http://observer.test",
                observer_api_key="key",
                observer_model="model",
            )
        )

        with patch(
            "services.investigation.reth_planner.chat_completion",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"probe_names": ["restart_systemd_service"], "objective": "bad"}
                            )
                        }
                    }
                ]
            },
        ):
            plan = planner.plan(trigger=trigger, signal_payload=signal)

        self.assertIsNotNone(plan)
        payload = plan.to_dict()
        self.assertEqual("native", payload["probe_budget"]["planner"])
        self.assertIn("llm_planner_fallback", payload["probe_budget"]["fallback_reason"])
        self.assertNotIn("restart_systemd_service", {probe["name"] for probe in payload["probes"]})


class RethEvidenceAndRcaTests(unittest.TestCase):
    def test_evidence_uses_planned_typed_probe_results(self) -> None:
        signal = _reth_signal()
        trigger = _trigger(signal)
        plan = RethInvestigationPlanner(RuntimeConfig()).plan(trigger=trigger, signal_payload=signal)

        pack = EvidenceService().assemble(
            trigger=trigger,
            signal_payload=signal,
            investigation_plan=plan.to_dict() if plan else None,
        )

        probe_names = {probe.name for probe in pack.probe_results}
        self.assertIn("json_rpc_peer_sync", probe_names)
        self.assertIn("json_rpc_rpc_health", probe_names)
        self.assertTrue(all(probe.citations for probe in pack.probe_results))
        self.assertTrue(any(probe.payload for probe in pack.probe_results))

    def test_runtime_emits_reth_plan_ranked_hypotheses_and_rca_report(self) -> None:
        signal = _reth_signal()
        with tempfile.TemporaryDirectory() as tmp:
            engine = MeshRuntimeEngine(config=RuntimeConfig(state_directory=tmp, evaluation_mode="native", orchestration_mode="native"))
            result = engine.run_sync(signal, scenario_name="reth_rca")

        self.assertIn("investigation_plan", result)
        self.assertIn("rca_report", result)
        self.assertEqual("local_isolation", result["rca_report"]["likely_cause"])
        event_keys = [event.get("artifact_key") for event in result["run_events"]]
        self.assertIn("investigation_plan", event_keys)
        self.assertIn("ranked_hypotheses", event_keys)
        self.assertIn("rca_report", event_keys)
        decision_pack = result["decision"]["reasoning"]["evidence_pack"]
        self.assertIn("rca_report", decision_pack)


if __name__ == "__main__":
    unittest.main()
