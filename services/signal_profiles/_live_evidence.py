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
from datetime import datetime, timezone
from typing import Any, Callable

from services.evidence.service import EvidencePack, ProbeResult
from shared.mesh_runtime import RuntimeConfig, Trigger
from shared.mesh_runtime.otel import PrometheusClient

from ._evidence_strategies import (
    StructuredSignalEvidenceStrategy,
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
    # Structural required-field contract carried over from the legacy
    # OTel profile. The pre-PR profile rejected payloads missing
    # ``observed_value``, ``baseline_value`` or ``resource_attributes``
    # — relaxing that would silently flip downstream uncertainty /
    # decision behavior for partially populated OTel signals when
    # Prometheus probes are skipped (no backend configured) or fail.
    # ``service`` isn't in this list on purpose: the live probe falls
    # back to ``trigger.service`` when the payload omits it and emits
    # a ``prometheus_metric_unavailable`` audit probe instead of
    # marking the pack insufficient.
    _REQUIRED_PATHS: tuple[str, ...] = (
        "signal_type",
        "metric_regression.metric_name",
        "metric_regression.observed_value",
        "metric_regression.baseline_value",
        "resource_attributes",
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

        live_probe = self._probe_metric_range(trigger, metric_name, service)
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

    def _probe_metric_range(
        self,
        trigger: Trigger,
        metric_name: str,
        service: str,
    ) -> ProbeResult:
        # PromQL query: scope to the triggered service when the metric
        # name arrives bare. If the operator pre-decorated it with a
        # label matcher (``{...}``), trust their selector verbatim —
        # double-scoping would risk producing a no-match query when
        # the operator's label spelling differs from ours.
        query = _build_promql_query(metric_name, service)
        start_ts, end_ts, window_source = _derive_query_window(
            trigger, default_range_seconds=self._DEFAULT_RANGE_SECONDS
        )
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
                "start_ts": start_ts,
                "end_ts": end_ts,
                "window_source": window_source,
                "samples_count": len(samples),
                # Cap at 200 samples (~100 minutes at 30s step) to
                # keep the artifact small. Investigation harness can
                # re-query with a tighter range if needed.
                "samples_head": list(samples[:200]),
            },
            citations=[
                {
                    "source_type": "prometheus",
                    "source_ref": f"range_query/{query}",
                }
            ],
        )


# ---------------------------------------------------------------------------
# Helpers — promQL query assembly + trigger-window derivation
# ---------------------------------------------------------------------------


def _build_promql_query(metric_name: str, service: str) -> str:
    """Compose a PromQL query that scopes ``metric_name`` to ``service``.

    The legacy code passed ``metric_name`` through verbatim, which in
    multi-service Prometheus setups risks pulling samples from an
    unrelated series (``range_query`` returns one series of points)
    and feeding wrong evidence into ranking + decision. Codex flagged
    this on PR #42; this helper is the fix.

    Behavior:

    * Bare metric name + non-empty service → wrap as
      ``metric_name{service="<service>"}`` so the range query is
      scoped to the triggered service.
    * Metric name already carrying a ``{...}`` matcher → leave it
      alone. Operators that pre-decorate with a custom label
      (``app=…``, ``job=…``, ``k8s_deployment=…``) shouldn't have us
      double-scope on top of their selector — a wrong label name
      would produce a no-match query and *worse* evidence than the
      unscoped probe.
    * Empty metric name → return empty (caller short-circuits).
    * Empty service with a bare metric → fall through to bare query.
      The unscoped query is still useful for single-service Prometheus
      deployments, and the audit trail records ``service=""`` so
      downstream can flag it.

    The ``service`` label name is the OTel-convention default and is
    not currently configurable. Operators that use a different label
    (``job`` is the other common convention) should pre-decorate the
    metric name in the inbound signal.
    """
    name = metric_name.strip()
    if not name:
        return ""
    if "{" in name:
        return name
    svc = service.strip()
    if not svc:
        return name
    # Escape any embedded double-quotes in the service value so we
    # don't produce invalid PromQL when service strings carry quotes.
    safe_service = svc.replace("\\", "\\\\").replace('"', '\\"')
    return f'{name}{{service="{safe_service}"}}'


def _derive_query_window(
    trigger: Trigger,
    *,
    default_range_seconds: int,
) -> tuple[float, float, str]:
    """Pick ``(start_ts, end_ts, source_label)`` for the range query.

    The legacy code anchored every range query at ``datetime.now() -
    10min`` regardless of when the trigger fired or which window it
    flagged. That works for live cluster operation but produces wrong
    evidence for delayed processing, replayed benchmarks, and
    historical incident reruns — Codex's P1 callout on PR #42.

    Priority order:

    1. ``trigger.comparison_window["observed"]`` formatted as an
       ISO 8601 time-interval string ``"<start>/<end>"``. This is the
       shape the OTel ingest pipeline emits (see
       ``services/ingest/otel_signal.py``) — both ends are absolute,
       so we use them as-is. ``source_label="comparison_window"``.
    2. ``trigger.triggered_at`` as the end of the window;
       ``end - default_range_seconds`` as the start. Covers triggers
       that arrive without a comparison_window or with a
       relative-duration-only window (``"PT5M"``, CloudOpsBench).
       ``source_label="triggered_at"``.
    3. ``datetime.now(UTC)`` end / ``- default_range_seconds`` start.
       Last-resort fallback for triggers with no time context (live
       demos, fuzz inputs). ``source_label="now"``.

    Any parse failure on (1) silently falls through to (2). We don't
    surface the parse error because the audit trail still captures
    ``window_source`` in the probe payload, and the comparison_window
    string is preserved on the trigger artifact.
    """
    window = getattr(trigger, "comparison_window", None)
    if isinstance(window, dict):
        observed = window.get("observed")
        if isinstance(observed, str) and "/" in observed:
            start_str, _, end_str = observed.partition("/")
            start = _parse_iso_timestamp(start_str)
            end = _parse_iso_timestamp(end_str)
            if start is not None and end is not None and end > start:
                return start.timestamp(), end.timestamp(), "comparison_window"

    triggered_at = _parse_iso_timestamp(getattr(trigger, "triggered_at", "") or "")
    if triggered_at is not None:
        end_ts = triggered_at.timestamp()
        return end_ts - default_range_seconds, end_ts, "triggered_at"

    end_ts = datetime.now(timezone.utc).timestamp()
    return end_ts - default_range_seconds, end_ts, "now"


def _parse_iso_timestamp(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp, tolerating the ``"Z"`` UTC suffix.

    ``datetime.fromisoformat`` rejects ``"Z"`` on Python < 3.11; we
    normalise to ``"+00:00"`` first so the same code path works on
    3.10. Returns ``None`` on any parse failure so callers can fall
    back without exception handling at the call site.
    """
    if not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


__all__ = [
    "KubectlRunner",
    "KubernetesLiveEvidenceStrategy",
    "OtelLiveEvidenceStrategy",
    "PrometheusRunner",
]
