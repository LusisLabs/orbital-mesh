from __future__ import annotations

import argparse
import os
import unittest
from unittest.mock import patch

from services.decision.hypothesis_engine import HypothesisEngine
from services.decision.service import DecisionService
from shared.mesh_runtime import Trigger
from simulation.__main__ import _configure_observer_env


def _base_trigger(
    *,
    trigger_id: str,
    trigger_type: str,
    service: str,
    related_context: dict,
) -> Trigger:
    return Trigger(
        trigger_id=trigger_id,
        trigger_type=trigger_type,
        triggered_at="2026-04-26T00:00:00Z",
        environment="prod",
        service=service,
        endpoint=f"{service}.health",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window={"baseline": "PT1H", "observed": "PT5M"},
        segment={"customer_tier": "system", "region": "us-east-1"},
        metrics={
            "baseline_p95_latency_ms": None,
            "observed_p95_latency_ms": None,
            "baseline_error_rate": None,
            "observed_error_rate": None,
            "baseline_timeout_rate": None,
            "observed_timeout_rate": None,
            "sample_size": 1,
        },
        related_context=related_context,
    )


class KubernetesHypothesisUpgradeTests(unittest.TestCase):
    def test_unknown_predicates_do_not_upgrade_escalation(self):
        trigger = _base_trigger(
            trigger_id="trig_k8s_unknown_hypotheses",
            trigger_type="kubernetes_deployment_unhealthy",
            service="checkout",
            related_context={
                "error_signatures": ["crash_loop"],
                "rollout_status": "degraded",
                "deployment_name": "checkout",
                "namespace": "prod",
            },
        )

        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(trigger)

        self.assertEqual(decision.decision_type, "escalate")
        self.assertFalse(decision.reasoning["evidence_pack"]["hypothesis_upgrade_applied"])


class RethReasoningTests(unittest.TestCase):
    def test_known_escalation_signature_keeps_signature_in_primary_hypothesis(self):
        trigger = _base_trigger(
            trigger_id="trig_reth_known_signature",
            trigger_type="reth_node_degraded",
            service="reth-mainnet-07",
            related_context={
                "error_signatures": ["authrpc_exposed"],
                "node": {"role": "rpc", "network": "mainnet"},
                "execution": {"peer_count": 12, "block_lag": 0, "syncing": False},
                "consensus": {"engine_api_reachable": True, "forkchoice_updates_recent": True},
                "storage": {"disk_used_pct": 60.0},
                "resource_attributes": {},
            },
        )

        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(trigger)

        self.assertEqual(decision.decision_type, "escalate")
        self.assertIn("authrpc_exposed", decision.reasoning["primary_hypothesis"])
        self.assertNotIn("Unrecognized error signature", decision.reasoning["primary_hypothesis"])


class SimulationObserverEnvTests(unittest.TestCase):
    def test_cli_observer_flags_override_existing_environment(self):
        args = argparse.Namespace(
            no_observer=False,
            observer_provider="openai",
            observer_base_url="https://cli.example/v1",
            observer_model="cli-model",
            observer_api_key="cli-key",
        )
        with patch.dict(
            os.environ,
            {
                "MESH_OBSERVER_PROVIDER": "anthropic",
                "MESH_OBSERVER_BASE_URL": "https://env.example",
                "MESH_OBSERVER_MODEL": "env-model",
                "OPENAI_API_KEY": "env-key",
            },
            clear=True,
        ):
            active = _configure_observer_env(args)

            self.assertTrue(active)
            self.assertEqual(os.environ["MESH_OBSERVER_PROVIDER"], "openai")
            self.assertEqual(os.environ["MESH_OBSERVER_BASE_URL"], "https://cli.example/v1")
            self.assertEqual(os.environ["MESH_OBSERVER_MODEL"], "cli-model")
            self.assertEqual(os.environ["MESH_OBSERVER_API_KEY"], "cli-key")


if __name__ == "__main__":
    unittest.main()
