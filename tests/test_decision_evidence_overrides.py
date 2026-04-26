"""Tests for the safety overrides ``_decide_reth_node`` applies on top
of the deterministic policy match.

These exist because the EvidenceService and DecisionService share a
contract that's invisible to the policy file. We want a regression
test that proves a fast-path-flagged pack escalates even when the
policy wouldn't on its own — defense in depth against a future policy
edit dropping a signature from ``escalation_signatures``.
"""

from __future__ import annotations

import unittest

from services.decision.service import DecisionService
from shared.mesh_runtime import Trigger


def _trigger(error_signatures: list[str], extra_context: dict | None = None) -> Trigger:
    related = {
        "error_signatures": error_signatures,
        "node": {"role": "rpc", "network": "mainnet"},
        "execution": {"peer_count": 0, "block_lag": 0, "syncing": False},
        "consensus": {
            "engine_api_reachable": True,
            "forkchoice_updates_recent": True,
        },
        "storage": {"disk_used_pct": 60.0},
        "resource_attributes": {},
    }
    if extra_context:
        related.update(extra_context)
    return Trigger(
        trigger_id="trig_test_overrides",
        trigger_type="reth_node_degraded",
        triggered_at="2026-04-26T00:00:00Z",
        environment="prod",
        service="reth-mainnet-07",
        endpoint="reth.rpc",
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
        related_context=related,
    )


class FastPathForceEscalateTests(unittest.TestCase):
    def test_fast_path_forces_escalate_even_when_policy_silent(self):
        """Synthetic scenario: fast-path was triggered for a signature
        the deterministic policy doesn't know about. Without this
        defensive check the pipeline would fall through to no_action
        for an unsafe condition.
        """
        # Build a trigger that the deterministic policy would route to
        # ``no_action`` (no error signatures matched). The evidence pack
        # carries a fast-path flag for an out-of-policy signature.
        trigger = _trigger(error_signatures=[])
        evidence_pack = {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": {},
                "storage": {},
            },
            "source": "fast_path_skip",
            "sufficient": True,  # Fast-path skipped probes; not "insufficient"
            "missing_fields": [],
            "fast_path_signatures": ["mystery_unsafe_signature"],
        }

        decision = DecisionService().decide(trigger, evidence_pack=evidence_pack)
        self.assertEqual(decision.decision_type, "escalate")
        self.assertEqual(decision.autonomy_tier, "escalated")

    def test_fast_path_with_known_escalation_signature_still_escalates(self):
        """Both paths agree: fast-path + policy escalation_signature →
        escalate. Sanity check that adding the override didn't break
        the normal flow."""
        trigger = _trigger(error_signatures=["authrpc_exposed"])
        evidence_pack = {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 12, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True, "authrpc_publicly_exposed": True},
                "consensus": {},
                "storage": {},
            },
            "source": "fast_path_skip",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": ["authrpc_exposed"],
        }
        decision = DecisionService().decide(trigger, evidence_pack=evidence_pack)
        self.assertEqual(decision.decision_type, "escalate")

    def test_no_fast_path_no_force_escalate(self):
        """Negative control: when fast_path_signatures is empty,
        the override does not fire. Normal restart path stands."""
        trigger = _trigger(error_signatures=["peer_starvation"])
        evidence_pack = {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": {"engine_api_reachable": True},
                "storage": {"disk_used_pct": 60.0},
            },
            "source": "inline_signal",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": [],
        }
        decision = DecisionService().decide(trigger, evidence_pack=evidence_pack)
        self.assertEqual(decision.decision_type, "restart_systemd_service")


if __name__ == "__main__":
    unittest.main()
