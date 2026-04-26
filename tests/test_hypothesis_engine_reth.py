"""Tests for the Reth hypothesis templates and predicate evaluation.

Each test pairs a synthetic ``trigger.related_context["error_signatures"]``
with a synthetic evidence pack and asserts the engine produces the
expected ranked hypothesis. This is what the LLM observer reads.
"""

from __future__ import annotations

import unittest

from services.decision.hypothesis_engine import HypothesisEngine
from shared.mesh_runtime import Trigger


def _trigger(error_signatures: list[str]) -> Trigger:
    return Trigger(
        trigger_id="trig_test",
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
        related_context={"error_signatures": error_signatures},
    )


def _pack(**overrides) -> dict:
    """Build a minimal Reth evidence pack the engine will read."""
    base = {
        "execution": {
            "syncing": False,
            "peer_count": 5,
            "block_lag": 0,
            "min_peer_count": 3,
            "max_block_lag": 32,
            "head_block": 19234567,
        },
        "consensus": {
            "engine_api_reachable": True,
            "forkchoice_updates_recent": True,
            "client_healthy": True,
            "client_kind": "lighthouse",
            "jwt_configured": True,
            "jwt_secret_exists": True,
            "jwt_secret_mode": "0600",
        },
        "storage": {
            "disk_used_pct": 60.0,
            "data_dir_free_bytes": 1_000_000_000_000,
            "snapshot_mode": "none",
            "diagnostic_source": "ssh_df",
        },
        "rpc": {
            "http_reachable": True,
            "latency_ms": 30.0,
            "error_rate": 0.0,
            "publicly_exposed": False,
            "authrpc_publicly_exposed": False,
        },
    }
    for section, fields in overrides.items():
        base.setdefault(section, {}).update(fields)
    return {"pack": base, "sufficient": True}


class PeerStarvationTemplateTests(unittest.TestCase):
    def test_zero_peers_with_rpc_up_picks_local_isolation(self):
        engine = HypothesisEngine()
        ranked = engine.generate(
            _trigger(["peer_starvation"]),
            evidence_pack=_pack(execution={"peer_count": 0}),
        )
        ids = [h.hypothesis_id for h in ranked]
        self.assertIn("h_reth_peer_local_isolation", ids)
        # The local-isolation hypothesis should rank higher than the
        # transient one when peer_count is actually zero.
        positions = {h.hypothesis_id: i for i, h in enumerate(ranked)}
        self.assertLess(
            positions["h_reth_peer_local_isolation"],
            positions["h_reth_peer_transient"],
        )

    def test_cascade_peer_zero_engine_down_ranks_consensus_disconnect_top(self):
        """Regression test for the ranking misorder.

        When peers are zero AND engine_api is unreachable, the safer
        cause (consensus_disconnect → escalate) must outrank
        local_isolation (which would recommend a restart that won't
        fix the actual problem). Without this ordering, the cascade
        produces an unsafe action whenever the LLM observer is off.
        """
        engine = HypothesisEngine()
        ranked = engine.generate(
            _trigger(["peer_starvation"]),
            evidence_pack=_pack(
                execution={"peer_count": 0},
                consensus={"engine_api_reachable": False},
            ),
        )
        top = ranked[0]
        self.assertEqual(top.candidate_cause, "consensus_disconnect")
        self.assertEqual(top.recommended_action, "escalate")
        # local_isolation should have at least one disconfirming
        # predicate (engine_api_reachable) and rank below.
        local = next(h for h in ranked if h.candidate_cause == "local_isolation")
        self.assertGreater(top.posterior_confidence, local.posterior_confidence)
        self.assertTrue(
            any("engine_api_reachable" in d for d in local.disconfirming_evidence),
            "local_isolation must disconfirm when engine_api is unreachable",
        )


class SyncStalledTemplateTests(unittest.TestCase):
    def test_disk_pressure_promotes_escalate_recommendation(self):
        engine = HypothesisEngine()
        ranked = engine.generate(
            _trigger(["sync_stalled"]),
            evidence_pack=_pack(
                execution={"syncing": True, "block_lag": 4500},
                storage={"disk_used_pct": 92.5},
            ),
        )
        ids = [h.hypothesis_id for h in ranked]
        self.assertIn("h_reth_sync_disk_pressure", ids)
        # Disk-pressure recommends escalate; that should be the top
        # hypothesis when disk is at 92%.
        top = ranked[0]
        self.assertEqual(top.recommended_action, "escalate")

    def test_consensus_disconnect_recommends_escalate(self):
        engine = HypothesisEngine()
        ranked = engine.generate(
            _trigger(["sync_stalled"]),
            evidence_pack=_pack(
                execution={"syncing": True, "block_lag": 4500},
                consensus={"engine_api_reachable": False, "forkchoice_updates_recent": False},
            ),
        )
        top = ranked[0]
        self.assertEqual(top.candidate_cause, "consensus_disconnect")
        self.assertEqual(top.recommended_action, "escalate")


class RpcDegradedTemplateTests(unittest.TestCase):
    def test_publicly_exposed_overload_demands_escalate(self):
        engine = HypothesisEngine()
        ranked = engine.generate(
            _trigger(["rpc_degraded"]),
            evidence_pack=_pack(
                rpc={"publicly_exposed": True, "error_rate": 0.12},
            ),
        )
        top = ranked[0]
        self.assertEqual(top.candidate_cause, "rpc_exposure_abuse")
        self.assertEqual(top.recommended_action, "escalate")

    def test_internal_overload_allows_restart(self):
        engine = HypothesisEngine()
        ranked = engine.generate(
            _trigger(["rpc_degraded"]),
            evidence_pack=_pack(
                rpc={"publicly_exposed": False, "error_rate": 0.08},
            ),
        )
        top = ranked[0]
        self.assertEqual(top.candidate_cause, "rpc_saturation")
        self.assertEqual(top.recommended_action, "restart_systemd_service")


class MissingPackTests(unittest.TestCase):
    def test_missing_pack_keeps_priors(self):
        # No evidence pack => predicates resolve as 'unknown' and the
        # hypotheses rank only by prior_confidence.
        engine = HypothesisEngine()
        ranked = engine.generate(_trigger(["peer_starvation"]))
        self.assertGreaterEqual(len(ranked), 3)
        # All predicates resolve unknown, so posteriors equal priors.
        for h in ranked:
            self.assertEqual(h.posterior_confidence, h.prior_confidence)


if __name__ == "__main__":
    unittest.main()
