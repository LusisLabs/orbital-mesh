"""Unit + integration tests for ``services.signal_history``.

The store is generic — it works for any signal type — so the tests
cover the three concrete signal kinds Mesh emits today (reth_node,
kubernetes_deployment_issue, otel_metric_regression) plus the trend
math + retention semantics.

The integration test wires a ``SignalHistoryStore`` through
``IngestService`` and ``DecisionService`` and verifies the
sustained-condition predicates flow into the decision's evidence pack.
This is the cheapest e2e check that the read path actually fires.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.decision.service import DecisionService
from services.ingest.bare_metal_node import BareMetalNodeTarget, RethNodeIngester
from services.ingest.service import IngestService
from services.signal_history import (
    SignalHistoryStore,
    SignalRecord,
    derive_target_id,
)
from services.trigger.service import TriggerService


def _record(
    *,
    target_id: str = "reth:r1",
    signal_type: str = "reth_node",
    observed_at: datetime | None = None,
    payload: dict | None = None,
) -> SignalRecord:
    return SignalRecord(
        target_id=target_id,
        signal_type=signal_type,
        observed_at=observed_at or datetime.now(timezone.utc),
        payload=payload or {"signal_type": signal_type},
    )


class TargetIdDerivationTests(unittest.TestCase):
    """The one signal-type-specific bit. Every signal kind Mesh emits
    today must produce a stable, namespaced target_id; future signal
    kinds get None until the dispatch table is updated."""

    def test_reth_target_id_namespaced_by_service(self) -> None:
        self.assertEqual(
            derive_target_id({"signal_type": "reth_node", "service": "reth-mainnet-01"}),
            "reth:reth-mainnet-01",
        )

    def test_kubernetes_target_id_includes_cluster_namespace_deployment(self) -> None:
        payload = {
            "signal_type": "kubernetes_deployment_issue",
            "cluster": "prod-east",
            "namespace": "search",
            "deployment": {"name": "search-api"},
        }
        self.assertEqual(derive_target_id(payload), "k8s:prod-east:search:search-api")

    def test_otel_target_id_includes_service_and_endpoint(self) -> None:
        payload = {
            "signal_type": "otel_metric_regression",
            "service": "checkout",
            "endpoint": "POST /api/checkout",
        }
        self.assertEqual(derive_target_id(payload), "otel:checkout:POST /api/checkout")

    def test_unknown_signal_type_returns_none(self) -> None:
        """Unrecognized signal kinds shouldn't crash — they just don't
        get history. Allows new signal types to land before the
        dispatch table catches up."""
        self.assertIsNone(derive_target_id({"signal_type": "novel_signal"}))


class StoreRetentionTests(unittest.TestCase):
    """In-memory ring buffer + LRU target eviction."""

    def test_records_per_target_capped(self) -> None:
        store = SignalHistoryStore(records_per_target=3, persist=False)
        for i in range(5):
            store.add(_record(payload={"signal_type": "reth_node", "execution": {"peer_count": i}}))
        records = store.recent("reth:r1")
        # Only the last 3 survived.
        self.assertEqual(len(records), 3)
        peer_counts = [r.payload["execution"]["peer_count"] for r in records]
        self.assertEqual(peer_counts, [2, 3, 4])

    def test_unknown_target_returns_empty_list(self) -> None:
        store = SignalHistoryStore(persist=False)
        self.assertEqual(store.recent("never_seen"), [])

    def test_max_targets_evicts_lru(self) -> None:
        """When we exceed the target cap, the least-recently-touched
        target gets dropped. Important so a million-target cluster can't
        balloon memory."""
        store = SignalHistoryStore(max_targets=2, persist=False)
        store.add(_record(target_id="reth:a"))
        store.add(_record(target_id="reth:b"))
        store.add(_record(target_id="reth:c"))  # forces eviction of reth:a
        self.assertEqual(store.recent("reth:a"), [])
        self.assertEqual(len(store.recent("reth:b")), 1)
        self.assertEqual(len(store.recent("reth:c")), 1)

    def test_seconds_filter_drops_old_records(self) -> None:
        store = SignalHistoryStore(persist=False)
        old = datetime.now(timezone.utc) - timedelta(seconds=600)
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        store.add(_record(observed_at=old))
        store.add(_record(observed_at=recent))
        records_120s = store.recent("reth:r1", seconds=120)
        self.assertEqual(len(records_120s), 1)


class TrendStatsTests(unittest.TestCase):
    """The Trend dataclass owns most of the math. Test each predicate
    in isolation so changes here don't have to re-run the e2e flow."""

    def test_numeric_stats_when_samples_present(self) -> None:
        store = SignalHistoryStore(persist=False)
        for v in (1, 2, 3, 4, 5):
            store.add(_record(payload={"signal_type": "reth_node", "execution": {"peer_count": v}}))
        trend = store.trend("reth:r1", "execution.peer_count", window_seconds=600)
        self.assertEqual(trend.count, 5)
        self.assertEqual(trend.min, 1.0)
        self.assertEqual(trend.max, 5.0)
        self.assertEqual(trend.current, 5)
        self.assertEqual(trend.mean, 3.0)
        self.assertTrue(trend.is_monotonic_increasing)
        self.assertFalse(trend.is_monotonic_decreasing)

    def test_duration_at_or_below_walks_backward_until_violation(self) -> None:
        """Duration predicates must walk *backward* from the most recent
        sample so 'sustained' means 'currently true and held continuously'."""
        store = SignalHistoryStore(persist=False)
        now = datetime.now(timezone.utc)
        # Sequence: 5, 5, 1, 1, 1 — the last 3 are below threshold 2.
        for offset, v in [(120, 5), (90, 5), (60, 1), (30, 1), (0, 1)]:
            store.add(_record(
                observed_at=now - timedelta(seconds=offset),
                payload={"signal_type": "reth_node", "execution": {"peer_count": v}},
            ))
        trend = store.trend("reth:r1", "execution.peer_count", window_seconds=600)
        duration = trend.duration_at_or_below(2.0)
        # The tail run is 60s long (samples at 60, 30, 0).
        self.assertEqual(duration, timedelta(seconds=60))

    def test_duration_at_or_below_returns_zero_when_current_violates(self) -> None:
        store = SignalHistoryStore(persist=False)
        now = datetime.now(timezone.utc)
        for offset, v in [(60, 1), (30, 1), (0, 5)]:  # current is above threshold
            store.add(_record(
                observed_at=now - timedelta(seconds=offset),
                payload={"signal_type": "reth_node", "execution": {"peer_count": v}},
            ))
        trend = store.trend("reth:r1", "execution.peer_count", window_seconds=600)
        self.assertEqual(trend.duration_at_or_below(2.0), timedelta(0))

    def test_to_summary_omits_stats_when_one_sample(self) -> None:
        """A single sample isn't a trend; the LLM should know that. We
        omit min/max/mean/trend so the prompt doesn't suggest false
        precision."""
        store = SignalHistoryStore(persist=False)
        store.add(_record(payload={"signal_type": "reth_node", "execution": {"peer_count": 3}}))
        trend = store.trend("reth:r1", "execution.peer_count", window_seconds=600)
        summary = trend.to_summary()
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["current"], 3)
        self.assertNotIn("trend", summary)
        self.assertNotIn("min", summary)

    def test_trend_handles_missing_path_gracefully(self) -> None:
        """Some envelopes won't have the path (e.g., engine_api_p99_ms is
        only set when metrics scrape is configured). Missing samples
        are skipped, not error."""
        store = SignalHistoryStore(persist=False)
        store.add(_record(payload={"signal_type": "reth_node", "execution": {"peer_count": 1}}))
        store.add(_record(payload={"signal_type": "reth_node"}))  # no execution block
        trend = store.trend("reth:r1", "execution.peer_count", window_seconds=600)
        self.assertEqual(trend.count, 1)


class JsonPathExtractionTests(unittest.TestCase):
    """The path extractor handles dotted paths, list indexing, and
    missing keys without raising. Locks in the format the LLM observer
    sees in the prompt."""

    def test_nested_dotted_path(self) -> None:
        store = SignalHistoryStore(persist=False)
        store.add(_record(payload={
            "signal_type": "reth_node",
            "consensus": {"engine_api_p99_ms": 3500},
        }))
        trend = store.trend("reth:r1", "consensus.engine_api_p99_ms", window_seconds=600)
        self.assertEqual(trend.current, 3500)

    def test_missing_intermediate_segment_gives_no_sample(self) -> None:
        store = SignalHistoryStore(persist=False)
        store.add(_record(payload={"signal_type": "reth_node"}))
        trend = store.trend("reth:r1", "consensus.engine_api_p99_ms", window_seconds=600)
        self.assertEqual(trend.count, 0)


class PersistenceTests(unittest.TestCase):
    """JSONL on-disk persistence is best-effort and bounded by retention.
    Lets a Mesh restart hydrate a few minutes of warm context."""

    def test_records_round_trip_through_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SignalHistoryStore(state_directory=tmp)
            store.add(_record(target_id="reth:r1", payload={"signal_type": "reth_node", "execution": {"peer_count": 7}}))

            # Fresh store from same dir; hydrate.
            store2 = SignalHistoryStore(state_directory=tmp)
            self.assertEqual(store2.hydrate_from_disk(), 1)
            records = store2.recent("reth:r1")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].payload["execution"]["peer_count"], 7)

    def test_hydrate_drops_records_outside_retention_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SignalHistoryStore(state_directory=tmp, retention_seconds=60)
            old = datetime.now(timezone.utc) - timedelta(seconds=600)
            store.add(_record(target_id="reth:r1", observed_at=old))
            # New process re-loads; old record should not survive the window.
            store2 = SignalHistoryStore(state_directory=tmp, retention_seconds=60)
            store2.hydrate_from_disk()
            self.assertEqual(store2.recent("reth:r1"), [])


# ---------------------------------------------------------------- e2e


class SignalHistoryEndToEndTests(unittest.TestCase):
    """Wire SignalHistoryStore through IngestService → DecisionService and
    confirm history flows into the decision's evidence pack. This is
    where S2's value materializes — the engine sees 'this peer count
    has been below floor for 4 ticks' instead of 'peer_count=1 right
    now, escalate'."""

    def _reth_target(self) -> BareMetalNodeTarget:
        return BareMetalNodeTarget.from_dict({
            "name": "reth-mainnet-01",
            "kind": "reth",
            "rpc_url": "http://127.0.0.1:8545",
            "host": "reth-mainnet-01",
            "service": "reth.service",
            "min_peer_count": 3,
            "max_block_lag": 32,
            "deployment_mode": "systemd",
            "network": "mainnet",
            "role": "full",
        })

    def test_end_to_end_history_appears_in_decision_evidence(self) -> None:
        store = SignalHistoryStore(persist=False)
        ingest = IngestService(signal_history=store)
        ingester = RethNodeIngester(self._reth_target())

        # Drive five ticks at peer_count=1 (below floor of 3) so we have
        # a sustained condition in history.
        for _ in range(5):
            with patch(
                "services.ingest.bare_metal_node._rpc_call",
                side_effect=[False, "0x1", "0x1234", "reth/v2.1.0"],
            ):
                signal = ingester.build_signal()
            envelope = ingest.normalize_signal(signal)
            time.sleep(0.001)  # ensure distinct timestamps

        # The store should now have 5 records for reth:reth-mainnet-01.
        records = store.recent("reth:reth-mainnet-01")
        self.assertEqual(len(records), 5)

        # The trend over the window should report 5 samples at peer_count=1.
        trend = store.trend(
            "reth:reth-mainnet-01", "execution.peer_count", window_seconds=600,
        )
        self.assertEqual(trend.count, 5)
        self.assertEqual(trend.current, 1)
        self.assertEqual(trend.min, 1.0)

        # Run the decision service against the latest envelope and assert
        # the trend block lands in the evidence pack.
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)
        svc = DecisionService(signal_history=store)
        decision = svc.decide(trigger)

        history_trends = decision.reasoning["evidence_pack"]["history_trends"]
        self.assertIn("peer_count", history_trends)
        self.assertEqual(history_trends["peer_count"]["count"], 5)
        self.assertEqual(history_trends["peer_count"]["current"], 1)
        # Sustained-below-floor predicate should reflect the multi-tick run.
        # (Whether it crosses the 60s threshold depends on test timing —
        # the assertions above are the durable ones.)
        self.assertIn("duration_below_floor_seconds", history_trends["peer_count"])

    def test_no_history_store_leaves_empty_history_trends(self) -> None:
        """Backward compat: existing call sites that don't wire the
        store get an empty dict, not a crash."""
        ingest = IngestService()  # no signal_history
        ingester = RethNodeIngester(self._reth_target())

        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()
        envelope = ingest.normalize_signal(signal)
        trigger = TriggerService().detect(envelope)
        svc = DecisionService()  # no signal_history
        decision = svc.decide(trigger)

        self.assertEqual(decision.reasoning["evidence_pack"]["history_trends"], {})


class KubernetesHistoryTrendsTests(unittest.TestCase):
    """The k8s read site: ``_decide_kubernetes`` should pull trends
    via the same generic store and expose them in the same
    ``evidence_pack.history_trends`` slot the LLM observer reads.

    Uses the kubernetes_crashloop_patch fixture as the base — same
    fixture that locks in the schema contract — and varies just the
    rollout fields per tick.
    """

    def _k8s_signal(self, *, available_replicas: int = 0, rollout_status: str = "failed") -> dict:
        """Schema-compliant k8s signal cloned from the canonical fixture
        and varied per tick. Loading the fixture (instead of hand-rolling
        a payload here) means a future schema change won't break this
        test in a way that's hard to debug."""
        from shared.mesh_runtime import load_fixture
        signal = load_fixture("signals", "kubernetes_crashloop_patch.json")
        # Distinguish each tick's signal_id so they're not deduped on the
        # state store side.
        signal["signal_id"] = f"sig_k8s_{int(time.time() * 1_000_000)}"
        signal["observed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        signal["deployment"]["rollout_status"] = rollout_status
        signal["deployment"]["available_replicas"] = available_replicas
        return signal

    def test_kubernetes_trends_appear_in_evidence_pack(self) -> None:
        """Drive 4 ticks of a stuck rollout and verify the rollout
        history shows up under ``evidence_pack.history_trends``."""
        store = SignalHistoryStore(persist=False)
        ingest = IngestService(signal_history=store)

        last_envelope = None
        for _ in range(4):
            signal = self._k8s_signal(available_replicas=0, rollout_status="failed")
            last_envelope = ingest.normalize_signal(signal)
            time.sleep(0.001)

        # The fixture's cluster/namespace/deployment-name produce this id.
        target_id = "k8s:prod-us-east-1:search:semantic-search"
        records = store.recent(target_id)
        self.assertEqual(len(records), 4)

        trigger = TriggerService().detect(last_envelope)
        self.assertIsNotNone(trigger)
        decision = DecisionService(signal_history=store).decide(trigger)

        history_trends = decision.reasoning["evidence_pack"]["history_trends"]
        self.assertIn("rollout_status", history_trends)
        self.assertEqual(history_trends["rollout_status"]["current"], "failed")
        self.assertEqual(history_trends["rollout_status"]["count"], 4)
        self.assertIn("duration_failed_seconds", history_trends["rollout_status"])
        # ``available_replicas`` trend should also be present (desired=3,
        # available=0 across all four ticks) and report sustained-below-desired.
        self.assertIn("available_replicas", history_trends)
        self.assertEqual(history_trends["available_replicas"]["desired"], 3)


class OtelHistoryTrendsTests(unittest.TestCase):
    """The otel read site: both the rule-match path and the escalation
    fallback expose ``evidence_pack.history_trends``."""

    def _otel_signal(self, *, observed_value: float, delta_pct: float) -> dict:
        return {
            "signal_type": "otel_metric_regression",
            "signal_id": f"sig_{int(time.time() * 1000)}",
            "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "environment": "prod",
            "service": "checkout",
            "endpoint": "POST /api/checkout",
            "metric_regression": {
                "metric_name": "service.request.error_rate",
                "baseline_value": 0.01,
                "observed_value": observed_value,
                "delta_pct": delta_pct,
                "attributes": {"sample_size": 5000},
            },
            "comparison_window": {"baseline": "5m", "observed": "5m"},
            "segment": {"customer_tier": "standard"},
        }

    def test_otel_trends_appear_in_escalation_evidence_pack(self) -> None:
        """Drive 4 ticks of an escalating regression. The escalation
        fallback (no rule match in the default policy for this metric)
        must include the trend block."""
        store = SignalHistoryStore(persist=False)
        ingest = IngestService(signal_history=store)

        last_envelope = None
        for value, delta in [(0.05, 5), (0.08, 8), (0.12, 12), (0.18, 18)]:
            signal = self._otel_signal(observed_value=value, delta_pct=delta)
            last_envelope = ingest.normalize_signal(signal)
            time.sleep(0.001)

        target_id = "otel:checkout:POST /api/checkout"
        self.assertEqual(len(store.recent(target_id)), 4)

        trigger = TriggerService().detect(last_envelope)
        self.assertIsNotNone(trigger)
        decision = DecisionService(signal_history=store).decide(trigger)

        history_trends = decision.reasoning["evidence_pack"]["history_trends"]
        self.assertIn("observed_value", history_trends)
        self.assertEqual(history_trends["observed_value"]["count"], 4)
        # The series 0.05 → 0.08 → 0.12 → 0.18 is monotonically
        # increasing, which the trend extractor should label.
        self.assertEqual(history_trends["observed_value"].get("trend"), "increasing")

        self.assertIn("delta_pct", history_trends)
        self.assertGreaterEqual(history_trends["delta_pct"]["duration_above_10pct_seconds"], 0)


class RuntimeEngineWiringTests(unittest.TestCase):
    """The store must be constructed inside ``MeshRuntimeEngine`` and
    threaded into both ``IngestService`` and ``DecisionService`` so
    end-to-end traffic populates and reads the same instance."""

    def test_runtime_engine_constructs_signal_history_store(self) -> None:
        from services.runtime import MeshRuntimeEngine
        from shared.mesh_runtime import RuntimeConfig

        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfig(state_directory=tmp)
            engine = MeshRuntimeEngine(config=config)
            self.assertIsNotNone(engine.signal_history)
            # Both services must reference the SAME store instance —
            # otherwise reads after writes will return empty.
            self.assertIs(engine.ingest.signal_history, engine.signal_history)
            self.assertIs(engine.decision.signal_history, engine.signal_history)


if __name__ == "__main__":
    unittest.main()
