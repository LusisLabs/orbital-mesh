"""Tests for the SignalCorrelator — cross-signal correlation detection."""

from __future__ import annotations

import unittest

from services.signal_correlator import CorrelationContext, SignalCorrelator


class TestCorrelationContext(unittest.TestCase):
    def test_to_dict(self):
        ctx = CorrelationContext(
            correlation_type="same_namespace",
            affected_services=["api", "worker"],
            correlated_signals=[{"deployment_name": "api"}],
            correlation_confidence=0.55,
        )
        d = ctx.to_dict()
        self.assertEqual(d["type"], "same_namespace")
        self.assertEqual(d["correlated_signal_count"], 1)
        self.assertEqual(d["affected_services"], ["api", "worker"])


class TestSignalCorrelator(unittest.TestCase):
    def test_isolated_signal(self):
        correlator = SignalCorrelator(window_seconds=300)
        ctx = correlator.correlate("app", "default", "app-svc", "crash_loop")
        self.assertEqual(ctx.correlation_type, "none")
        self.assertEqual(ctx.affected_services, [])

    def test_same_namespace_correlation(self):
        correlator = SignalCorrelator(window_seconds=300, min_signals=2)
        correlator.correlate("app-a", "prod", "svc-a", "crash_loop")
        ctx = correlator.correlate("app-b", "prod", "svc-b", "oom_killed")
        self.assertEqual(ctx.correlation_type, "same_namespace")
        self.assertIn("svc-a", ctx.affected_services)
        self.assertIn("svc-b", ctx.affected_services)
        self.assertGreater(ctx.correlation_confidence, 0)

    def test_same_deployment_not_correlated(self):
        correlator = SignalCorrelator(window_seconds=300, min_signals=2)
        correlator.correlate("app-a", "prod", "svc-a", "crash_loop")
        ctx = correlator.correlate("app-a", "prod", "svc-a", "oom_killed")
        # Same deployment appearing twice is not a cross-deployment correlation
        self.assertEqual(ctx.correlation_type, "none")

    def test_cascading_across_namespaces(self):
        correlator = SignalCorrelator(window_seconds=300, min_signals=2)
        correlator.correlate("db", "data", "db-svc", "crash_loop")
        ctx = correlator.correlate("api", "web", "api-svc", "timeout")
        self.assertEqual(ctx.correlation_type, "cascading")
        self.assertIn("db-svc", ctx.affected_services)
        self.assertIn("api-svc", ctx.affected_services)

    def test_blast_wave_three_services(self):
        correlator = SignalCorrelator(window_seconds=300, min_signals=2)
        correlator.correlate("db", "data", "db-svc", "crash_loop")
        correlator.correlate("api", "web", "api-svc", "timeout")
        ctx = correlator.correlate("worker", "jobs", "worker-svc", "oom_killed")
        self.assertEqual(ctx.correlation_type, "blast_wave")
        self.assertEqual(len(ctx.affected_services), 3)
        self.assertGreater(ctx.correlation_confidence, 0.5)

    def test_window_expiry(self):
        correlator = SignalCorrelator(window_seconds=300, min_signals=2)
        correlator.correlate("app-a", "prod", "svc-a", "crash_loop")
        # Manually expire the window entry
        correlator._window[0].timestamp -= 400
        ctx = correlator.correlate("app-b", "prod", "svc-b", "oom_killed")
        self.assertEqual(ctx.correlation_type, "none")

    def test_min_signals_respected(self):
        correlator = SignalCorrelator(window_seconds=300, min_signals=3)
        correlator.correlate("app-a", "prod", "svc-a", "crash_loop")
        ctx = correlator.correlate("app-b", "prod", "svc-b", "oom_killed")
        # min_signals=3 requires 2 others in same namespace for same_namespace
        # but there's only 1 other, so it should fall through to cascading check
        # Since they're in the same namespace with different deployments, it still
        # has an other_deployment match, so cascading should fire
        self.assertIn(ctx.correlation_type, ("none", "cascading"))

    def test_status(self):
        correlator = SignalCorrelator(window_seconds=120, min_signals=3)
        correlator.correlate("app", "ns", "svc", "err")
        status = correlator.status()
        self.assertEqual(status["window_seconds"], 120)
        self.assertEqual(status["min_signals"], 3)
        self.assertEqual(status["signals_in_window"], 1)

    def test_thread_safety(self):
        import threading
        correlator = SignalCorrelator(window_seconds=300, min_signals=2)
        errors = []

        def worker(n):
            try:
                for i in range(10):
                    correlator.correlate(f"app-{n}-{i}", f"ns-{n}", f"svc-{n}", "err")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(correlator.status()["signals_in_window"], 40)


class TestDecisionCorrelationAwareness(unittest.TestCase):
    """Verify the decision service forces approval_required for correlated failures."""

    def _make_k8s_trigger(self, correlation_type=None):
        from shared.mesh_runtime import Trigger
        related_context = {
            "error_signatures": ["crash_loop"],
            "deployment_name": "search-api",
            "namespace": "search",
            "rollout_status": "degraded",
            "event_reasons": [],
            "likely_layer": "unknown",
            "cluster": "test",
            "deployment_image": "search:latest",
        }
        if correlation_type:
            related_context["correlation"] = {
                "type": correlation_type,
                "affected_services": ["search-api", "auth-api"],
                "correlated_signal_count": 2,
            }
        return Trigger(
            trigger_id="trig_test",
            trigger_type="kubernetes_deployment_unhealthy",
            triggered_at="2026-04-15T00:00:00Z",
            service="search",
            endpoint="deployment/search",
            environment="prod",
            flag_key="",
            current_rollout_pct=0,
            comparison_window={"start": "2026-04-15T00:00:00Z", "end": "2026-04-15T00:05:00Z"},
            segment={"customer_tier": "standard"},
            metrics={
                "baseline_p95_latency_ms": 100,
                "observed_p95_latency_ms": 100,
                "baseline_error_rate": 0.01,
                "observed_error_rate": 0.01,
            },
            related_context=related_context,
        )

    def test_blast_wave_forces_approval_required(self):
        from services.decision.service import DecisionService
        svc = DecisionService()
        trigger = self._make_k8s_trigger(correlation_type="blast_wave")
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.autonomy_tier, "approval_required")

    def test_cascading_forces_approval_required(self):
        from services.decision.service import DecisionService
        svc = DecisionService()
        trigger = self._make_k8s_trigger(correlation_type="cascading")
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.autonomy_tier, "approval_required")

    def test_no_correlation_keeps_autonomous(self):
        from services.decision.service import DecisionService
        svc = DecisionService()
        trigger = self._make_k8s_trigger(correlation_type=None)
        decision = svc._decide_kubernetes(trigger)
        # crash_loop → restart_deployment → autonomous (no repeated rollback)
        self.assertEqual(decision.autonomy_tier, "autonomous")


if __name__ == "__main__":
    unittest.main()
