"""Tests for Layer 4 — learning rules from operator overrides.

Four areas are worth locking down:

1. **Fingerprint stability** — similar signals must produce the same
   fingerprint, and different signals must produce different fingerprints.
2. **Store round-trip** — writes persist, reads filter by age, outcome
   backfill updates the right records.
3. **Synthesis thresholds** — suggestions only emit when observation count
   and agreement threshold are both met.
4. **Median parameter merging** — numeric outliers shouldn't move the
   suggestion; integers should stay integers.
"""

from __future__ import annotations

import tempfile
import unittest

from shared.mesh_runtime.rule_suggestions import (
    OverrideLearningStore,
    fingerprint_signal,
)


def _signal(metric_name: str, service: str, namespace: str, observed: float, baseline: float) -> dict:
    return {
        "signal_type": "otel_metric_regression",
        "service": service,
        "endpoint": metric_name,
        "namespace": namespace,
        "metric_regression": {
            "metric_name": metric_name,
            "baseline_value": baseline,
            "observed_value": observed,
            "delta_pct": ((observed - baseline) / baseline * 100.0) if baseline else None,
        },
        "resource_attributes": {
            "k8s.namespace.name": namespace,
            "k8s.deployment.name": service,
        },
    }


# ------------------------------------------------------------------ fingerprint


class FingerprintTests(unittest.TestCase):
    def test_similar_signals_share_fingerprint(self) -> None:
        """The normalized-name step is the core value prop — lock it in."""
        a = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
        b = _signal("kafka_consumer_lag_total", "payments", "default", 500, 200)
        c = _signal("ConsumerLag", "payments", "default", 300, 150)
        self.assertEqual(fingerprint_signal(a), fingerprint_signal(b))
        self.assertEqual(fingerprint_signal(a), fingerprint_signal(c))

    def test_different_services_separate_fingerprints(self) -> None:
        """Lag on payments vs notifications must not blur together."""
        a = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
        b = _signal("kafka.consumer.lag", "notifications", "default", 200, 100)
        self.assertNotEqual(fingerprint_signal(a), fingerprint_signal(b))

    def test_direction_matters(self) -> None:
        """A metric going up vs down probably wants different remediation."""
        up = _signal("memory.utilization", "api", "default", 90, 50)
        down = _signal("memory.utilization", "api", "default", 30, 70)
        self.assertNotEqual(fingerprint_signal(up), fingerprint_signal(down))

    def test_pod_names_do_not_affect_fingerprint(self) -> None:
        """Per-pod labels shouldn't fragment the grouping."""
        a = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
        a["resource_attributes"]["k8s.pod.name"] = "payments-abc-123"
        b = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
        b["resource_attributes"]["k8s.pod.name"] = "payments-def-456"
        self.assertEqual(fingerprint_signal(a), fingerprint_signal(b))


# ------------------------------------------------------------------ store


class StoreRoundTripTests(unittest.TestCase):
    def _store(self) -> OverrideLearningStore:
        self.tmpdir = tempfile.mkdtemp()
        return OverrideLearningStore(self.tmpdir)

    def test_write_then_read_preserves_fields(self) -> None:
        store = self._store()
        signal = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
        record = store.record_override(
            signal=signal,
            run_id="run_1",
            original_decision_type="escalate",
            override_decision_type="scale_deployment",
            override_parameters={"deployment_name": "payments", "namespace": "default", "replicas_delta": 2},
            original_parameters={},
        )
        read_back = store.list_overrides()
        self.assertEqual(len(read_back), 1)
        self.assertEqual(read_back[0].fingerprint, record.fingerprint)
        self.assertEqual(read_back[0].override_decision_type, "scale_deployment")

    def test_outcome_backfill_updates_matching_records(self) -> None:
        store = self._store()
        signal = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
        store.record_override(
            signal=signal,
            run_id="run_xyz",
            original_decision_type="escalate",
            override_decision_type="scale_deployment",
            override_parameters={"replicas_delta": 2},
            original_parameters={},
        )
        store.update_override_outcome("run_xyz", "successful")
        records = store.list_overrides()
        self.assertEqual(records[0].outcome, "successful")

    def test_age_filter_excludes_old_records(self) -> None:
        """When max_age_days is set, records older than the cutoff are skipped."""
        store = self._store()
        signal = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
        record = store.record_override(
            signal=signal,
            run_id="run_old",
            original_decision_type="escalate",
            override_decision_type="scale_deployment",
            override_parameters={"replicas_delta": 2},
            original_parameters={},
        )
        # Manually rewrite the recorded_at to be far in the past.
        import json
        from pathlib import Path
        path = Path(self.tmpdir) / "learning" / "overrides.json"
        data = json.loads(path.read_text())
        data["overrides"][0]["recorded_at"] = "2020-01-01T00:00:00+00:00"
        path.write_text(json.dumps(data))
        _ = record  # silence unused
        fresh = store.list_overrides(max_age_days=30)
        self.assertEqual(fresh, [])
        everything = store.list_overrides()
        self.assertEqual(len(everything), 1)


# ------------------------------------------------------------------ synthesis


class SynthesisTests(unittest.TestCase):
    def _store_with_overrides(self, count: int, action: str = "scale_deployment") -> OverrideLearningStore:
        tmp = tempfile.mkdtemp()
        store = OverrideLearningStore(tmp)
        for i in range(count):
            signal = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
            store.record_override(
                signal=signal,
                run_id=f"run_{i}",
                original_decision_type="escalate",
                override_decision_type=action,
                override_parameters={
                    "deployment_name": "payments",
                    "namespace": "default",
                    "replicas_delta": 2,
                },
                original_parameters={},
            )
            store.update_override_outcome(f"run_{i}", "successful")
        return store

    def test_below_threshold_produces_no_suggestion(self) -> None:
        """4 observations < 5-observation threshold → empty result."""
        store = self._store_with_overrides(count=4)
        self.assertEqual(store.synthesize_suggestions(min_observations=5), [])

    def test_at_threshold_produces_suggestion(self) -> None:
        store = self._store_with_overrides(count=5)
        suggestions = store.synthesize_suggestions(min_observations=5)
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion.rule["propose"]["decision_type"], "scale_deployment")
        self.assertEqual(suggestion.observation_count, 5)
        self.assertEqual(suggestion.success_rate, 1.0)

    def test_disagreement_below_threshold_suppresses_suggestion(self) -> None:
        """When operators can't agree on an action (50/50 split), don't suggest."""
        tmp = tempfile.mkdtemp()
        store = OverrideLearningStore(tmp)
        for i in range(5):
            signal = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
            action = "scale_deployment" if i % 2 == 0 else "restart_deployment"
            store.record_override(
                signal=signal,
                run_id=f"run_{i}",
                original_decision_type="escalate",
                override_decision_type=action,
                override_parameters={"deployment_name": "payments", "namespace": "default", "replicas_delta": 2},
                original_parameters={},
            )
        # 3/5 = 60% agreement, exactly at threshold — should produce a suggestion.
        suggestions = store.synthesize_suggestions(min_observations=5, agreement_threshold=0.6)
        self.assertEqual(len(suggestions), 1)
        # Raise the bar — no longer met, suggestion should be suppressed.
        suggestions = store.synthesize_suggestions(min_observations=5, agreement_threshold=0.8)
        self.assertEqual(len(suggestions), 0)

    def test_parameter_median_ignores_outliers(self) -> None:
        """If one operator types replicas_delta=50 by mistake, the median should
        still reflect the sane majority."""
        tmp = tempfile.mkdtemp()
        store = OverrideLearningStore(tmp)
        deltas = [2, 2, 2, 2, 50]  # one fat-fingered outlier
        for i, delta in enumerate(deltas):
            signal = _signal("kafka.consumer.lag", "payments", "default", 200, 100)
            store.record_override(
                signal=signal,
                run_id=f"run_{i}",
                original_decision_type="escalate",
                override_decision_type="scale_deployment",
                override_parameters={
                    "deployment_name": "payments",
                    "namespace": "default",
                    "replicas_delta": delta,
                },
                original_parameters={},
            )
            store.update_override_outcome(f"run_{i}", "successful")
        suggestions = store.synthesize_suggestions(min_observations=5)
        self.assertEqual(suggestions[0].rule["propose"]["parameters"]["replicas_delta"], 2)

    def test_suggestion_rule_is_shape_compatible_with_policy_file(self) -> None:
        """The rule field of a suggestion must be pasteable into metric-actions.policy.json."""
        store = self._store_with_overrides(count=5)
        suggestions = store.synthesize_suggestions(min_observations=5)
        rule = suggestions[0].rule
        for required_key in ("name", "match", "propose", "bounds", "confidence", "risk_level"):
            self.assertIn(required_key, rule)
        for propose_key in ("decision_type", "system", "action", "parameters"):
            self.assertIn(propose_key, rule["propose"])


if __name__ == "__main__":
    unittest.main()
