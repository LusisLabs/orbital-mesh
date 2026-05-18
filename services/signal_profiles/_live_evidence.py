"""Live evidence strategies for non-Reth signal profiles.

The Reth profile has been the only signal type that actually gathers
evidence (``RethEvidenceStrategy`` runs JSON-RPC probes against the
node). Every other profile — Kubernetes, OTel, webhook, feature-flag,
generic — used ``StructuredSignalEvidenceStrategy``, which only checks
whether the inbound payload has the expected required fields. No
probes ran. The "evidence" was just the signal renamed.

That left the system "Reth-only when it matters" — when an operator
pointed mesh at a Kubernetes cluster or an OTel pipeline, the
evidence stage was a no-op and the entire data-collection burden
shifted to the investigation harness loop. This meant:

* Redundant work — the harness re-discovered the same pod / event /
  metric state on every run because evidence never pre-fetched it.
* No pre-investigation signal — the hypothesis engine, scenario
  analyzer, and decision engine all read ``evidence_pack``; if it's
  empty they fall back to trigger.related_context only.

This module ports the same probe-running shape Reth has into live
strategies for K8s and OTel:

* ``KubernetesLiveEvidenceStrategy`` runs read-only ``kubectl``
  probes (get pods, get events, describe deployment) when the
  ``MESH_KUBECTL_COMMAND`` config is wired. Falls back to the
  structural check otherwise.
* ``OtelLiveEvidenceStrategy`` queries the configured Prometheus
  for the metric over the comparison window when
  ``MESH_PROMETHEUS_URL`` is set. Falls back to the structural
  check otherwise.

The structural check is preserved in both — sufficient operators run
without those backends configured and still need an audited artifact.
The new behavior is purely additive: when a backend is configured,
real probe results show up alongside the structural finding.

Safety: all probes here are read-only by construction (``kubectl
get``, ``kubectl describe``, Prometheus ``/api/v1/query``). No
subprocess invocation outside the configured tool path. Network /
subprocess failures are caught and surfaced as failed ``ProbeResult``
entries — they never crash the pipeline.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from services.evidence.service import EvidencePack, ProbeResult
from shared.mesh_runtime import RuntimeConfig, Trigger
from shared.mesh_runtime.otel import PrometheusClient

from ._evidence_strategies import (
    StructuredSignalEvidenceStrategy,
    _now_iso,
    _read_dotted,
)


_LOG = logging.getLogger("mesh.evidence.live")


# ---------------------------------------------------------------------------
# Kubernetes
# ---------------------------------------------------------------------------


# kubectl runner shape: (args list, timeout_seconds) -> (success, stdout_text,
# error_string). Default factory shells out to ``config.kubectl_command``;
# tests inject a fake to return canned text without needing a real cluster.
KubectlRunner = Callable[[list[str], float], tuple[bool, str, str | None]]


def _default_kubectl_runner(config: RuntimeConfig) -> KubectlRunner | None:
    """Return a kubectl invoker, or ``None`` if live K8s is disabled.

    Gated on ``MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1`` rather than
    on ``kubectl_command`` being non-empty: the config defaults
    ``kubectl_command`` to the literal string ``"kubectl"`` so
    relying on it would mean every dev / benchmark / CI run tries
    to shell out to whatever ``kubectl`` is on the PATH. That's not
    a safe default for evidence collection — the explicit live-mode
    flag is what the actuators module already gates on, so we match
    its semantics here.
    """
    if not getattr(config, "kubernetes_live_execution_enabled", False):
        return None
    kubectl_command = getattr(config, "kubectl_command", "")
    if not kubectl_command:
        return None
    base_cmd = shlex.split(kubectl_command)
    if not base_cmd:
        return None

    def run(argv: list[str], timeout_seconds: float) -> tuple[bool, str, str | None]:
        try:
            completed = subprocess.run(
                base_cmd + argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, "", f"kubectl timeout after {timeout_seconds:.1f}s"
        except OSError as exc:
            return False, "", f"kubectl invocation error: {exc}"
        if completed.returncode != 0:
            return False, completed.stdout, (completed.stderr or "kubectl non-zero exit").strip()
        return True, completed.stdout, None

    return run


class KubernetesLiveEvidenceStrategy:
    """K8s evidence strategy that runs read-only kubectl probes.

    Three probes per run:

    * ``kubectl get pods -n <ns> -o wide`` — current pod state for the
      whole namespace. Used by the harness later for selecting
      unhealthy targets.
    * ``kubectl get events -n <ns> --sort-by=.lastTimestamp`` —
      recent events; the canonical place admission and scheduling
      failures land.
    * ``kubectl describe deployment <name> -n <ns>`` — current
      deployment spec + status + recent events filtered to the
      deployment.

    Each probe wraps the structural field-presence check from the
    legacy strategy. Pre-probe ``required_paths`` failures still
    record an inline ``ProbeResult``; live probes augment the pack
    with the actually-fetched state.

    When kubectl isn't configured (no ``MESH_KUBECTL_COMMAND``), the
    strategy degrades to a structural-only EvidencePack — same shape
    the legacy ``StructuredSignalEvidenceStrategy`` produced, so
    deployments without kubectl wired continue to work unchanged.
    """

    # Bounded so the evidence stage can't hang the pipeline. Reasonable
    # defaults: 4s for list calls, 5s for describe (slower). The
    # investigation harness gets its own deeper budget downstream.
    _LIST_TIMEOUT_SECONDS: float = 4.0
    _DESCRIBE_TIMEOUT_SECONDS: float = 5.0
    _SIGNAL_SOURCE: str = "kubernetes"
    _REQUIRED_PATHS: tuple[str, ...] = (
        "signal_type",
        "cluster",
        "namespace",
        "deployment.name",
        "deployment.rollout_status",
        "pods",
        "events",
        "log_summary",
    )

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        kubectl_runner: KubectlRunner | None = None,
    ) -> None:
        # If the caller passes a runner explicitly that wins; otherwise
        # build one from config when kubectl is configured. ``None``
        # means "no live probes — structural check only," which the
        # ``assemble`` method handles below.
        if kubectl_runner is not None:
            self._kubectl_runner = kubectl_runner
        elif config is not None:
            self._kubectl_runner = _default_kubectl_runner(config)
        else:
            self._kubectl_runner = None
        # Reuse the structural check exactly so degraded mode produces
        # the same artifact shape the legacy strategy did.
        self._structural = StructuredSignalEvidenceStrategy(
            signal_source=self._SIGNAL_SOURCE,
            required_paths=self._REQUIRED_PATHS,
        )

    def assemble(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> EvidencePack:
        # Always run the structural check — it's the regression floor.
        # Then layer live probes on top when kubectl is available.
        base = self._structural.assemble(
            trigger=trigger,
            signal_payload=signal_payload,
            investigation_plan=investigation_plan,
        )
        if self._kubectl_runner is None:
            return base

        namespace = self._extract_namespace(signal_payload, trigger)
        deployment_name = self._extract_deployment_name(signal_payload, trigger)
        if not namespace:
            # No namespace = no live probes possible. Stamp a single
            # ``namespace_unavailable`` probe so the audit trail shows
            # we tried, then return the structural artifact.
            unable = ProbeResult(
                name="kubectl_namespace_unavailable",
                source="kubectl",
                success=False,
                latency_ms=0.0,
                error="signal payload missing namespace",
                payload={"namespace": None},
                citations=[],
            )
            return EvidencePack(
                pack=base.pack,
                assembled_at=base.assembled_at,
                source=base.source,
                probe_results=list(base.probe_results) + [unable],
                sufficient=base.sufficient,
                missing_fields=base.missing_fields,
            )

        live_probes: list[ProbeResult] = []
        live_probes.append(self._probe_pods(namespace))
        live_probes.append(self._probe_events(namespace))
        if deployment_name:
            live_probes.append(self._probe_describe_deployment(namespace, deployment_name))

        return EvidencePack(
            pack=base.pack,
            assembled_at=base.assembled_at,
            source=f"{base.source}+kubectl_live",
            probe_results=list(base.probe_results) + live_probes,
            sufficient=base.sufficient,
            missing_fields=base.missing_fields,
        )

    # ------------------------------------------------------------------
    # Probes
    # ------------------------------------------------------------------

    def _probe_pods(self, namespace: str) -> ProbeResult:
        started = time.monotonic()
        ok, stdout, err = self._kubectl_runner(  # type: ignore[misc]
            ["get", "pods", "-n", namespace, "-o", "wide"],
            self._LIST_TIMEOUT_SECONDS,
        )
        latency_ms = (time.monotonic() - started) * 1000.0
        return ProbeResult(
            name="kubectl_get_pods",
            source="kubectl",
            success=ok,
            latency_ms=round(latency_ms, 3),
            error=err,
            # Cap stdout at 16KB so a 1000-pod namespace doesn't blow
            # the EvidencePack. Investigation harness has its own
            # tools for deep inspection.
            payload={"namespace": namespace, "stdout": (stdout or "")[:16_384]},
            citations=[{"source_type": "kubectl", "source_ref": f"pods/{namespace}"}],
        )

    def _probe_events(self, namespace: str) -> ProbeResult:
        started = time.monotonic()
        ok, stdout, err = self._kubectl_runner(  # type: ignore[misc]
            ["get", "events", "-n", namespace, "--sort-by=.lastTimestamp"],
            self._LIST_TIMEOUT_SECONDS,
        )
        latency_ms = (time.monotonic() - started) * 1000.0
        return ProbeResult(
            name="kubectl_get_events",
            source="kubectl",
            success=ok,
            latency_ms=round(latency_ms, 3),
            error=err,
            payload={"namespace": namespace, "stdout": (stdout or "")[:16_384]},
            citations=[{"source_type": "kubectl", "source_ref": f"events/{namespace}"}],
        )

    def _probe_describe_deployment(self, namespace: str, name: str) -> ProbeResult:
        started = time.monotonic()
        ok, stdout, err = self._kubectl_runner(  # type: ignore[misc]
            ["describe", "deployment", name, "-n", namespace],
            self._DESCRIBE_TIMEOUT_SECONDS,
        )
        latency_ms = (time.monotonic() - started) * 1000.0
        return ProbeResult(
            name="kubectl_describe_deployment",
            source="kubectl",
            success=ok,
            latency_ms=round(latency_ms, 3),
            error=err,
            payload={
                "namespace": namespace,
                "deployment": name,
                "stdout": (stdout or "")[:16_384],
            },
            citations=[
                {
                    "source_type": "kubectl",
                    "source_ref": f"deployment/{namespace}/{name}",
                }
            ],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_namespace(signal_payload: dict[str, Any], trigger: Trigger) -> str | None:
        # Signal-payload `namespace` is canonical; trigger related_context
        # is the K8s-native fallback.
        for getter in (
            lambda: signal_payload.get("namespace"),
            lambda: _read_dotted(signal_payload, "deployment.namespace"),
            lambda: trigger.related_context.get("namespace"),
            lambda: trigger.related_context.get("k8s_namespace"),
        ):
            value = getter()
            if value:
                return str(value)
        return None

    @staticmethod
    def _extract_deployment_name(signal_payload: dict[str, Any], trigger: Trigger) -> str | None:
        for getter in (
            lambda: _read_dotted(signal_payload, "deployment.name"),
            lambda: trigger.related_context.get("deployment_name"),
            lambda: trigger.service,  # last-resort: service name often == deployment name
        ):
            value = getter()
            if value:
                return str(value)
        return None


# ---------------------------------------------------------------------------
# OTel / Prometheus
# ---------------------------------------------------------------------------


# Prometheus runner shape: (query, comparison_window) -> ProbeResult-shaped
# dict. Tests inject a fake to avoid needing a real Prometheus server.
PrometheusRunner = Callable[[str, dict[str, str] | None], dict[str, Any]]


def _default_prometheus_client(config: RuntimeConfig) -> PrometheusClient | None:
    """Return a ``PrometheusClient`` bound to ``config.prometheus_url``,
    or ``None`` if Prometheus isn't configured."""
    url = getattr(config, "prometheus_url", "")
    if not url:
        return None
    timeout = float(getattr(config, "prometheus_query_timeout_seconds", 10.0))
    return PrometheusClient(url, timeout_seconds=timeout)


class OtelLiveEvidenceStrategy:
    """OTel evidence strategy that queries Prometheus for the regressed metric.

    One range query per run: pulls the metric over the trigger's
    comparison window so the hypothesis engine and scenario analyzer
    have actual time-series data rather than just the regression
    summary from the inbound signal. When the comparison window
    isn't on the trigger, falls back to the last 10 minutes.

    When Prometheus isn't configured (no ``MESH_PROMETHEUS_URL``), the
    strategy degrades to a structural-only EvidencePack — same as the
    legacy strategy. Deployments without Prometheus continue to work
    unchanged.
    """

    _SIGNAL_SOURCE: str = "otel"
    _REQUIRED_PATHS: tuple[str, ...] = (
        "signal_type",
        "metric_regression.metric_name",
        "service",
    )
    # Default range when the trigger doesn't carry an explicit window.
    _DEFAULT_RANGE_SECONDS: int = 10 * 60
    _DEFAULT_STEP_SECONDS: int = 30

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        prometheus_client: PrometheusClient | None = None,
    ) -> None:
        if prometheus_client is not None:
            self._prometheus = prometheus_client
        elif config is not None:
            self._prometheus = _default_prometheus_client(config)
        else:
            self._prometheus = None
        self._structural = StructuredSignalEvidenceStrategy(
            signal_source=self._SIGNAL_SOURCE,
            required_paths=self._REQUIRED_PATHS,
        )

    def assemble(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> EvidencePack:
        base = self._structural.assemble(
            trigger=trigger,
            signal_payload=signal_payload,
            investigation_plan=investigation_plan,
        )
        if self._prometheus is None:
            return base

        metric_name = _read_dotted(signal_payload, "metric_regression.metric_name") or ""
        service = signal_payload.get("service") or trigger.service or ""
        if not metric_name or not service:
            unable = ProbeResult(
                name="prometheus_metric_unavailable",
                source="prometheus",
                success=False,
                latency_ms=0.0,
                error="signal payload missing metric_name or service",
                payload={"metric_name": metric_name, "service": service},
                citations=[],
            )
            return EvidencePack(
                pack=base.pack,
                assembled_at=base.assembled_at,
                source=base.source,
                probe_results=list(base.probe_results) + [unable],
                sufficient=base.sufficient,
                missing_fields=base.missing_fields,
            )

        live_probe = self._probe_metric_range(metric_name, service)
        return EvidencePack(
            pack=base.pack,
            assembled_at=base.assembled_at,
            source=f"{base.source}+prometheus_live",
            probe_results=list(base.probe_results) + [live_probe],
            sufficient=base.sufficient,
            missing_fields=base.missing_fields,
        )

    # ------------------------------------------------------------------
    # Probes
    # ------------------------------------------------------------------

    def _probe_metric_range(self, metric_name: str, service: str) -> ProbeResult:
        # PromQL needs the metric name as-is. We don't enforce a
        # ``{service=...}`` label matcher because mesh's metric_name
        # often arrives pre-decorated (e.g. ``http_request_duration_seconds{service="api"}``).
        # If the operator passes a bare metric name, the query
        # returns all series for that metric — the
        # investigation harness can refine downstream.
        query = metric_name
        end_ts = datetime.now(timezone.utc).timestamp()
        start_ts = end_ts - self._DEFAULT_RANGE_SECONDS
        started = time.monotonic()
        try:
            samples = self._prometheus.range_query(  # type: ignore[union-attr]
                query, start_ts, end_ts, step_seconds=self._DEFAULT_STEP_SECONDS
            )
            err: str | None = None
            success = True
        except Exception as exc:  # noqa: BLE001 — surface as failed probe, not crash
            samples = []
            err = f"prometheus range query failed: {exc}"
            success = False
            _LOG.exception("OtelLiveEvidenceStrategy: prometheus probe failed")
        latency_ms = (time.monotonic() - started) * 1000.0
        return ProbeResult(
            name="prometheus_range_query",
            source="prometheus",
            success=success,
            latency_ms=round(latency_ms, 3),
            error=err,
            payload={
                "metric_name": metric_name,
                "service": service,
                "query": query,
                "samples_count": len(samples),
                # Cap at 200 samples (~100 minutes at 30s step) to
                # keep the artifact small. Investigation harness can
                # re-query with a tighter range if needed.
                "samples_head": list(samples[:200]),
            },
            citations=[
                {
                    "source_type": "prometheus",
                    "source_ref": f"range_query/{metric_name}",
                }
            ],
        )


__all__ = [
    "KubectlRunner",
    "KubernetesLiveEvidenceStrategy",
    "OtelLiveEvidenceStrategy",
    "PrometheusRunner",
]
