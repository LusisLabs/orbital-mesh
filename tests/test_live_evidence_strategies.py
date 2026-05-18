"""Tests for live (probe-running) evidence strategies.

Before this work, every non-Reth signal profile used
``StructuredSignalEvidenceStrategy`` — a structural field-presence
check that ran no probes. The K8s, OTel, webhook, and feature-flag
profiles all returned the same shape EvidencePack regardless of
whether mesh had any backend wired (kubectl, Prometheus, etc.).

``KubernetesLiveEvidenceStrategy`` and ``OtelLiveEvidenceStrategy``
now run real read-only probes against the configured backends.
Tests here pin three contracts:

1. **Fail-soft when no backend** — degrade to a structural-only pack,
   no exception, same shape the legacy strategy produced.
2. **Run live probes when configured** — the right kubectl args /
   PromQL queries land via injected runners.
3. **Probe failures surface as failed ProbeResults**, not crashes —
   kubectl timeouts, Prometheus errors stay in the pack so the audit
   trail records the attempt.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from services.evidence.service import EvidencePack, ProbeResult
from services.signal_profiles._live_evidence import (
    KubernetesLiveEvidenceStrategy,
    OtelLiveEvidenceStrategy,
)
from shared.mesh_runtime import RuntimeConfig, Trigger


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _k8s_trigger() -> Trigger:
    return Trigger(
        trigger_id="trg_k8s_test",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="2026-05-17T12:00:00Z",
        environment="prod",
        service="payment-service",
        endpoint="/health",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=None,
        segment={},
        metrics={},
        related_context={"namespace": "boutique", "deployment_name": "payment-service"},
    )


def _otel_trigger() -> Trigger:
    return Trigger(
        trigger_id="trg_otel_test",
        trigger_type="otel_metric_regression",
        triggered_at="2026-05-17T12:00:00Z",
        environment="prod",
        service="api",
        endpoint="/checkout",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=None,
        segment={},
        metrics={"baseline_p95_latency_ms": 100, "observed_p95_latency_ms": 350},
        related_context={},
    )


def _k8s_signal_payload() -> dict[str, Any]:
    return {
        "signal_id": "k8s_test_signal_1",
        "signal_type": "kubernetes_deployment_issue",
        "cluster": "prod-east",
        "namespace": "boutique",
        "deployment": {"name": "payment-service", "rollout_status": "degraded"},
        "pods": [{"name": "payment-service-abc-123", "phase": "Pending"}],
        "events": [],
        "log_summary": {"error_count": 5},
    }


def _otel_signal_payload() -> dict[str, Any]:
    return {
        "signal_id": "otel_test_signal_1",
        "signal_type": "otel_metric_regression",
        "service": "api",
        "metric_regression": {
            "metric_name": "http_request_duration_seconds_p95",
            "observed_value": 0.35,
            "baseline_value": 0.10,
        },
        "resource_attributes": {"service.name": "api", "env": "prod"},
    }


# ---------------------------------------------------------------------------
# KubernetesLiveEvidenceStrategy
# ---------------------------------------------------------------------------


class KubernetesLiveStrategyTests(unittest.TestCase):
    def test_no_kubectl_configured_falls_back_to_structural(self) -> None:
        """The default RuntimeConfig has ``kubernetes_live_execution_enabled=False``
        (mesh's safe default — it doesn't want every dev run shelling
        out to a stray ``kubectl`` on PATH). The strategy MUST
        degrade silently to the structural check in that case so
        existing deployments keep working."""
        strategy = KubernetesLiveEvidenceStrategy(config=RuntimeConfig())
        pack = strategy.assemble(
            trigger=_k8s_trigger(), signal_payload=_k8s_signal_payload()
        )
        # Pack is well-formed; structural probe ran; no kubectl probes.
        self.assertIsInstance(pack, EvidencePack)
        probe_names = [p.name for p in pack.probe_results]
        self.assertIn("structured_signal_fields", probe_names)
        self.assertNotIn("kubectl_get_pods", probe_names)
        self.assertNotIn("kubectl_get_events", probe_names)

    def test_live_probes_fire_when_kubectl_runner_injected(self) -> None:
        """When kubectl is configured + live execution enabled, the
        strategy runs three probes: get pods, get events, describe
        deployment. Each probe's args are passed verbatim to the
        runner so we can assert the kubectl invocation shape."""
        runner_calls: list[tuple[list[str], float]] = []

        def fake_kubectl(args: list[str], timeout: float) -> tuple[bool, str, str | None]:
            runner_calls.append((list(args), timeout))
            if args[:2] == ["get", "pods"]:
                return True, "NAME    READY   STATUS\npayment-abc   0/1   Pending", None
            if args[:2] == ["get", "events"]:
                return True, "LAST SEEN   TYPE      REASON\n5m   Warning   FailedScheduling   pod/payment-abc", None
            if args[:2] == ["describe", "deployment"]:
                return True, "Name: payment-service\nReplicas: 1/3 available", None
            return False, "", f"unexpected args: {args}"

        strategy = KubernetesLiveEvidenceStrategy(kubectl_runner=fake_kubectl)
        pack = strategy.assemble(
            trigger=_k8s_trigger(), signal_payload=_k8s_signal_payload()
        )
        probe_names = [p.name for p in pack.probe_results]
        # Structural check still runs (the regression floor).
        self.assertIn("structured_signal_fields", probe_names)
        # All three live probes fired.
        self.assertIn("kubectl_get_pods", probe_names)
        self.assertIn("kubectl_get_events", probe_names)
        self.assertIn("kubectl_describe_deployment", probe_names)
        # Probe stdout reached the pack.
        get_pods = next(p for p in pack.probe_results if p.name == "kubectl_get_pods")
        self.assertIn("payment-abc", get_pods.payload["stdout"])
        # Source reflects live-mode.
        self.assertIn("kubectl_live", pack.source)
        # kubectl was invoked with the namespace from the signal.
        self.assertEqual(runner_calls[0][0], ["get", "pods", "-n", "boutique", "-o", "wide"])

    def test_kubectl_failure_surfaces_as_failed_probe_not_crash(self) -> None:
        """A timeout or non-zero exit from kubectl must become a
        failed ``ProbeResult``, not a raised exception. Otherwise a
        flaky kubectl breaks the entire evidence stage."""

        def fake_kubectl(args: list[str], timeout: float) -> tuple[bool, str, str | None]:
            return False, "", "simulated kubectl error"

        strategy = KubernetesLiveEvidenceStrategy(kubectl_runner=fake_kubectl)
        pack = strategy.assemble(
            trigger=_k8s_trigger(), signal_payload=_k8s_signal_payload()
        )
        # Pack still produced — pipeline does not crash.
        self.assertIsInstance(pack, EvidencePack)
        # Failures are recorded as failed probes for audit.
        failed = [p for p in pack.probe_results if p.source == "kubectl" and not p.success]
        self.assertEqual(len(failed), 3)
        self.assertTrue(all(p.error == "simulated kubectl error" for p in failed))

    def test_missing_namespace_records_audit_probe(self) -> None:
        """Without a namespace, we can't run kubectl probes — but the
        audit trail must show we tried, not silently skip."""
        trigger = _k8s_trigger()
        trigger.related_context = {}  # strip namespace from related_context
        payload = _k8s_signal_payload()
        del payload["namespace"]
        del payload["deployment"]

        runner = MagicMock()  # never called
        strategy = KubernetesLiveEvidenceStrategy(kubectl_runner=runner)
        pack = strategy.assemble(trigger=trigger, signal_payload=payload)
        runner.assert_not_called()
        probe_names = [p.name for p in pack.probe_results]
        self.assertIn("kubectl_namespace_unavailable", probe_names)

    def test_describe_deployment_uses_service_when_deployment_name_missing(self) -> None:
        """K8s native signals sometimes pass deployment_name in
        related_context; OTEL-shaped signals don't. Service name is
        the last-resort fallback (often equal to deployment name)."""
        trigger = _k8s_trigger()
        trigger.related_context = {"namespace": "boutique"}  # no deployment_name
        payload = _k8s_signal_payload()
        del payload["deployment"]
        payload["namespace"] = "boutique"
        runner_calls: list[list[str]] = []

        def fake_kubectl(args: list[str], timeout: float) -> tuple[bool, str, str | None]:
            runner_calls.append(args)
            return True, "ok", None

        strategy = KubernetesLiveEvidenceStrategy(kubectl_runner=fake_kubectl)
        strategy.assemble(trigger=trigger, signal_payload=payload)
        describe_call = next(
            (c for c in runner_calls if c[:2] == ["describe", "deployment"]),
            None,
        )
        self.assertIsNotNone(describe_call)
        # Used trigger.service = "payment-service" as the fallback name.
        self.assertEqual(describe_call[2], "payment-service")


# ---------------------------------------------------------------------------
# OtelLiveEvidenceStrategy
# ---------------------------------------------------------------------------


class OtelLiveStrategyTests(unittest.TestCase):
    def test_no_prometheus_configured_falls_back_to_structural(self) -> None:
        strategy = OtelLiveEvidenceStrategy(config=RuntimeConfig())
        pack = strategy.assemble(
            trigger=_otel_trigger(), signal_payload=_otel_signal_payload()
        )
        probe_names = [p.name for p in pack.probe_results]
        self.assertIn("structured_signal_fields", probe_names)
        self.assertNotIn("prometheus_range_query", probe_names)

    def test_prometheus_range_query_fires_when_client_injected(self) -> None:
        """The metric name + service from the signal must reach the
        Prometheus client. The returned samples land in the probe
        payload's ``samples_head``."""
        fake_prom = MagicMock()
        fake_prom.range_query.return_value = [
            (1700000000.0, 0.10),
            (1700000060.0, 0.20),
            (1700000120.0, 0.35),
        ]

        strategy = OtelLiveEvidenceStrategy(prometheus_client=fake_prom)
        pack = strategy.assemble(
            trigger=_otel_trigger(), signal_payload=_otel_signal_payload()
        )
        probe_names = [p.name for p in pack.probe_results]
        self.assertIn("prometheus_range_query", probe_names)
        prom_probe = next(p for p in pack.probe_results if p.name == "prometheus_range_query")
        # The metric name from the signal reached the query.
        self.assertEqual(prom_probe.payload["metric_name"], "http_request_duration_seconds_p95")
        # Samples landed in the probe.
        self.assertEqual(prom_probe.payload["samples_count"], 3)
        self.assertEqual(len(prom_probe.payload["samples_head"]), 3)
        # Source reflects live-mode.
        self.assertIn("prometheus_live", pack.source)
        # Prometheus client was called with the right query.
        fake_prom.range_query.assert_called_once()
        called_args = fake_prom.range_query.call_args
        self.assertEqual(called_args[0][0], "http_request_duration_seconds_p95")

    def test_prometheus_exception_surfaces_as_failed_probe(self) -> None:
        fake_prom = MagicMock()
        fake_prom.range_query.side_effect = RuntimeError("connection refused")

        strategy = OtelLiveEvidenceStrategy(prometheus_client=fake_prom)
        pack = strategy.assemble(
            trigger=_otel_trigger(), signal_payload=_otel_signal_payload()
        )
        # Pack still produced.
        self.assertIsInstance(pack, EvidencePack)
        prom_probe = next((p for p in pack.probe_results if p.name == "prometheus_range_query"), None)
        self.assertIsNotNone(prom_probe)
        self.assertFalse(prom_probe.success)
        self.assertIn("connection refused", prom_probe.error or "")

    def test_missing_metric_name_records_audit_probe(self) -> None:
        """Without a metric name we can't query — but the audit trail
        records the attempt."""
        fake_prom = MagicMock()
        payload = _otel_signal_payload()
        # Strip the metric_name path.
        payload["metric_regression"] = {}

        strategy = OtelLiveEvidenceStrategy(prometheus_client=fake_prom)
        pack = strategy.assemble(trigger=_otel_trigger(), signal_payload=payload)
        fake_prom.range_query.assert_not_called()
        probe_names = [p.name for p in pack.probe_results]
        self.assertIn("prometheus_metric_unavailable", probe_names)


# ---------------------------------------------------------------------------
# Profile wiring (end-to-end: profile builder → strategy instance)
# ---------------------------------------------------------------------------


class ProfileWiringTests(unittest.TestCase):
    def test_kubernetes_profile_builds_with_live_strategy(self) -> None:
        from services.signal_profiles import kubernetes as k8s_profile

        cfg = RuntimeConfig(
            kubernetes_live_execution_enabled=True, kubectl_command="/usr/local/bin/kubectl"
        )
        profile = k8s_profile.build(cfg)
        # Strategy is the new live one, not the legacy structural one.
        self.assertIsInstance(profile.evidence_strategy, KubernetesLiveEvidenceStrategy)
        # And the kubectl runner is wired.
        self.assertIsNotNone(profile.evidence_strategy._kubectl_runner)

    def test_kubernetes_profile_degrades_without_live_execution(self) -> None:
        from services.signal_profiles import kubernetes as k8s_profile

        profile = k8s_profile.build(RuntimeConfig())  # defaults
        self.assertIsInstance(profile.evidence_strategy, KubernetesLiveEvidenceStrategy)
        # No runner since kubernetes_live_execution_enabled=False by default.
        self.assertIsNone(profile.evidence_strategy._kubectl_runner)

    def test_otel_profile_builds_with_live_strategy(self) -> None:
        from services.signal_profiles import otel as otel_profile

        cfg = RuntimeConfig(prometheus_url="http://prometheus.observability.svc:9090")
        profile = otel_profile.build(cfg)
        self.assertIsInstance(profile.evidence_strategy, OtelLiveEvidenceStrategy)
        self.assertIsNotNone(profile.evidence_strategy._prometheus)

    def test_otel_profile_degrades_without_prometheus(self) -> None:
        from services.signal_profiles import otel as otel_profile

        profile = otel_profile.build(RuntimeConfig())
        self.assertIsInstance(profile.evidence_strategy, OtelLiveEvidenceStrategy)
        self.assertIsNone(profile.evidence_strategy._prometheus)


if __name__ == "__main__":
    unittest.main()
