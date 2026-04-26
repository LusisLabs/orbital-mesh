"""Tests for the EvidenceService — assembly, sufficiency, fast-path."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from services.evidence import EvidencePack, EvidenceService
from services.evidence.service import ProbeResult
from shared.mesh_runtime import Trigger


_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "signals"


def _trigger_for_signal(payload: dict, error_signatures: list[str]) -> Trigger:
    """Build a minimal Trigger that matches the EvidenceService inputs."""
    return Trigger(
        trigger_id=f"trig_{payload['signal_id']}",
        trigger_type="reth_node_degraded",
        triggered_at=payload["observed_at"],
        environment=payload["environment"],
        service=payload["service"],
        endpoint="reth.rpc",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=payload.get("comparison_window"),
        segment=payload.get("segment", {"customer_tier": "system", "region": "unknown"}),
        metrics={
            "baseline_p95_latency_ms": None,
            "observed_p95_latency_ms": payload["rpc"].get("latency_ms"),
            "baseline_error_rate": None,
            "observed_error_rate": payload["rpc"].get("error_rate"),
            "baseline_timeout_rate": None,
            "observed_timeout_rate": None,
            "sample_size": 1,
        },
        related_context={"error_signatures": error_signatures},
    )


class EvidenceServiceIdentityTests(unittest.TestCase):
    def test_reth_signal_passes_through_as_pack(self):
        payload = json.loads((_FIXTURE_ROOT / "reth_peer_starvation.json").read_text())
        trigger = _trigger_for_signal(payload, ["peer_starvation"])
        service = EvidenceService()
        pack = service.assemble(trigger=trigger, signal_payload=payload)

        self.assertIsInstance(pack, EvidencePack)
        self.assertTrue(pack.sufficient)
        self.assertEqual(pack.source, "inline_signal")
        self.assertEqual(pack.pack["signal_type"], "reth_node")
        self.assertEqual(pack.pack["execution"]["peer_count"], 0)
        self.assertEqual(pack.fast_path_signatures, [])
        self.assertEqual(len(pack.probe_results), 1)
        self.assertEqual(pack.probe_results[0].source, "inline")

    def test_non_reth_signal_returns_noop_pack(self):
        payload = {"signal_type": "kubernetes_deployment_issue", "service": "search"}
        trigger = _trigger_for_signal(
            {
                "signal_id": "noop",
                "observed_at": "2026-04-26T12:00:00Z",
                "environment": "production",
                "service": "search",
                "rpc": {},
            },
            error_signatures=[],
        )
        # The trigger above is a stand-in; assemble() only branches on signal_type.
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "inline_signal")
        self.assertTrue(pack.sufficient)
        self.assertEqual(pack.pack["signal_type"], "kubernetes_deployment_issue")


class EvidenceServiceFastPathTests(unittest.TestCase):
    def test_fast_path_authrpc_exposed_skips_probe_assembly(self):
        payload = json.loads((_FIXTURE_ROOT / "reth_peer_starvation.json").read_text())
        trigger = _trigger_for_signal(
            payload, ["peer_starvation", "authrpc_exposed"]
        )

        called = {"count": 0}

        def runner_should_not_be_called(_signal):
            called["count"] += 1
            return _signal, []

        service = EvidenceService(probe_runner=runner_should_not_be_called)
        pack = service.assemble(trigger=trigger, signal_payload=payload)

        self.assertEqual(called["count"], 0, "fast path must skip the runner")
        self.assertEqual(pack.source, "fast_path_skip")
        self.assertEqual(pack.fast_path_signatures, ["authrpc_exposed"])
        self.assertTrue(pack.sufficient)

    def test_fast_path_jwt_missing_skips_probe_assembly(self):
        payload = json.loads((_FIXTURE_ROOT / "reth_peer_starvation.json").read_text())
        trigger = _trigger_for_signal(payload, ["jwt_missing"])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")
        self.assertIn("jwt_missing", pack.fast_path_signatures)


class EvidenceServiceSufficiencyTests(unittest.TestCase):
    def test_sparse_signal_below_threshold_is_insufficient(self):
        sparse = {
            "signal_type": "reth_node",
            "signal_id": "sig_sparse_001",
            "observed_at": "2026-04-26T12:00:00Z",
            "environment": "production",
            "service": "reth-mainnet-07",
            "execution": {},   # All required fields missing
            "consensus": {},
            "storage": {},
            "rpc": {},
            "logs": {"error_signatures": ["peer_starvation"]},
            "resource_attributes": {},
            "node": {},
        }
        trigger = _trigger_for_signal(
            {
                "signal_id": "sparse",
                "observed_at": "2026-04-26T12:00:00Z",
                "environment": "production",
                "service": "reth-mainnet-07",
                "rpc": {},
            },
            error_signatures=["peer_starvation"],
        )

        pack = EvidenceService().assemble(trigger=trigger, signal_payload=sparse)
        self.assertFalse(pack.sufficient)
        self.assertGreater(len(pack.missing_fields), 2)

    def test_full_signal_is_sufficient(self):
        payload = json.loads((_FIXTURE_ROOT / "reth_peer_starvation.json").read_text())
        trigger = _trigger_for_signal(payload, ["peer_starvation"])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertTrue(pack.sufficient)
        self.assertEqual(pack.missing_fields, [])


class EvidenceServiceRunnerErrorTests(unittest.TestCase):
    def test_probe_runner_exception_yields_insufficient_pack(self):
        payload = json.loads((_FIXTURE_ROOT / "reth_peer_starvation.json").read_text())
        trigger = _trigger_for_signal(payload, ["peer_starvation"])

        def boom(_signal):
            raise RuntimeError("rpc unreachable")

        service = EvidenceService(probe_runner=boom)
        pack = service.assemble(trigger=trigger, signal_payload=payload)
        self.assertFalse(pack.sufficient)
        self.assertEqual(len(pack.probe_results), 1)
        self.assertFalse(pack.probe_results[0].success)
        self.assertIn("rpc unreachable", pack.probe_results[0].error or "")


class EvidencePackSerializationTests(unittest.TestCase):
    def test_to_dict_round_trips_probe_results(self):
        pack = EvidencePack(
            pack={"signal_type": "reth_node"},
            assembled_at="2026-04-26T12:00:00Z",
            source="inline_signal",
            probe_results=[
                ProbeResult(name="p1", source="inline", success=True, latency_ms=1.5),
                ProbeResult(name="p2", source="json_rpc", success=False, error="timeout"),
            ],
            sufficient=True,
        )
        d = pack.to_dict()
        self.assertEqual(d["source"], "inline_signal")
        self.assertEqual(len(d["probe_results"]), 2)
        self.assertEqual(d["probe_results"][1]["error"], "timeout")
        self.assertTrue(d["sufficient"])


if __name__ == "__main__":
    unittest.main()
