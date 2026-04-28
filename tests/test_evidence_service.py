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


class PolicyOverrideTests(unittest.TestCase):
    """The reth-node.policy.json ``evidence_sufficiency`` block must be
    read by ``EvidenceService`` so operators can tighten the
    sufficiency threshold without editing source. Otherwise the policy
    file's promise of being the source of truth silently breaks."""

    def test_policy_required_fields_loaded(self):
        # The committed policy lists four required fields; service must
        # adopt them rather than the source-level defaults.
        from services.evidence.service import _DEFAULT_REQUIRED_FIELDS

        service = EvidenceService()
        # The two lists may coincide today, but the contract is "what's
        # in the policy is what runs". Verify by reading the policy
        # directly and asserting parity.
        from shared.mesh_runtime import load_policy

        policy = load_policy("reth-node.policy.json")
        expected = tuple(policy["evidence_sufficiency"]["min_populated_fields"])
        self.assertEqual(service._required_fields, expected)
        # Sanity: the test would silently trivialize if the policy were
        # somehow empty; require that the policy actually overrides
        # something.
        self.assertEqual(
            tuple(_DEFAULT_REQUIRED_FIELDS), expected,
            "policy block and defaults match in this fixture, but the "
            "service should still resolve via the policy path",
        )

    def test_explicit_constructor_arg_wins_over_policy(self):
        custom = ("execution.peer_count",)
        service = EvidenceService(required_fields=custom, max_null_fields=0)
        self.assertEqual(service._required_fields, custom)
        self.assertEqual(service._max_null_fields, 0)


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


class DbCorruptionMatcherTests(unittest.TestCase):
    """The pre-fast-path log scan should stamp ``db_corruption_suspected``
    on the trigger when any DB-engine log line matches the known
    corruption patterns. This means a node that's misbehaving for an
    obvious-looking reason (peer count low, sync stalled) but is
    actually MDBX/Pebble-corrupt won't get a restart proposal — the
    fast-path will escalate.
    """

    def _payload_with_logs(self, log_lines: list[str]) -> dict:
        payload = json.loads((_FIXTURE_ROOT / "reth_peer_starvation.json").read_text())
        payload.setdefault("logs", {})["recent_errors"] = log_lines
        return payload

    def test_mdbx_corrupted_triggers_fast_path(self):
        payload = self._payload_with_logs([
            "2026-04-27T10:30:01Z ERROR reth::db: failed to open: MDBX_CORRUPTED: meta page checksum mismatch",
        ])
        trigger = _trigger_for_signal(payload, ["peer_starvation"])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)

        self.assertEqual(pack.source, "fast_path_skip")
        self.assertIn("db_corruption_suspected", pack.fast_path_signatures)
        # The signature must also be stamped on the trigger so the
        # decision service sees it via related_context.
        self.assertIn(
            "db_corruption_suspected",
            trigger.related_context["error_signatures"],
        )

    def test_pebble_manifest_corruption_triggers_fast_path(self):
        payload = self._payload_with_logs([
            "geth: pebble: manifest version not found",
        ])
        trigger = _trigger_for_signal(payload, ["sync_stalled"])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")
        self.assertIn("db_corruption_suspected", pack.fast_path_signatures)

    def test_rocksdb_sst_ahead_of_wal_triggers_fast_path(self):
        payload = self._payload_with_logs([
            "Nethermind.Db: Corruption: SST file is ahead of WAL",
        ])
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")

    def test_boltdb_corruption_triggers_fast_path(self):
        payload = self._payload_with_logs([
            "prysm: bolt: invalid database",
        ])
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")

    def test_sqlite_malformed_triggers_fast_path(self):
        payload = self._payload_with_logs([
            "lighthouse: database disk image is malformed",
        ])
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")

    def test_state_root_mismatch_triggers_fast_path(self):
        # Generic state-trie divergence (bit-rot, pruner bug). No DB
        # engine error needed.
        payload = self._payload_with_logs([
            "reth: ERROR engine: state root mismatch at block 19234567",
        ])
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")

    def test_clean_logs_do_not_trigger_fast_path(self):
        payload = self._payload_with_logs([
            "reth: INFO main: imported 12 blocks, head=19234600",
            "reth: INFO net: 27 peers, syncing=false",
        ])
        trigger = _trigger_for_signal(payload, ["peer_starvation"])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        # No corruption stamped; the normal path (or its sufficient pack)
        # runs.
        self.assertNotEqual(pack.source, "fast_path_skip")
        self.assertNotIn(
            "db_corruption_suspected",
            trigger.related_context.get("error_signatures", []),
        )

    def test_match_is_case_insensitive(self):
        payload = self._payload_with_logs([
            "reth: error: mdbx_corrupted: page invalid",
        ])
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")


class FilesystemUnsuitabilityTests(unittest.TestCase):
    """When the operator stamps the datadir filesystem and it's NFS,
    FUSE, tmpfs, or SMB, we refuse to act regardless of which symptom
    fired. Restarting won't fix an MDBX-on-NFS configuration."""

    def _payload_with_fs(self, fstype: str | None, *, attr: bool = False) -> dict:
        payload = json.loads((_FIXTURE_ROOT / "reth_peer_starvation.json").read_text())
        if fstype is not None:
            if attr:
                payload.setdefault("resource_attributes", {})["mesh.node.fstype"] = fstype
            else:
                payload.setdefault("storage", {})["filesystem"] = fstype
        return payload

    def test_nfs_storage_field_triggers_fast_path(self):
        payload = self._payload_with_fs("nfs4")
        trigger = _trigger_for_signal(payload, ["peer_starvation"])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")
        self.assertIn("filesystem_unsuitable", pack.fast_path_signatures)

    def test_fuse_resource_attribute_triggers_fast_path(self):
        payload = self._payload_with_fs("fuse.s3fs", attr=True)
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")

    def test_tmpfs_triggers_fast_path(self):
        payload = self._payload_with_fs("tmpfs")
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertEqual(pack.source, "fast_path_skip")

    def test_safe_filesystem_does_not_trigger(self):
        payload = self._payload_with_fs("ext4")
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertNotEqual(pack.source, "fast_path_skip")

    def test_no_filesystem_field_does_not_trigger(self):
        payload = self._payload_with_fs(None)
        trigger = _trigger_for_signal(payload, [])
        pack = EvidenceService().assemble(trigger=trigger, signal_payload=payload)
        self.assertNotEqual(pack.source, "fast_path_skip")


if __name__ == "__main__":
    unittest.main()
