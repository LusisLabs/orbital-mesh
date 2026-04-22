"""OpenTelemetry signal ingesters.

Two entry paths into Mesh from the OTel ecosystem:

* **Push** (:class:`OtlpPushIngester`): an OTLP/HTTP JSON payload arrives at the
  Mesh receiver. We pick the metric that matched an alert rule (or the highest-
  regression candidate) and emit a ``otel_metric_regression`` signal.
* **Pull** (:class:`PrometheusPullIngester`): on a schedule or on demand, Mesh
  queries Prometheus (or any OTel-collector-exposed Prometheus endpoint) for a
  target metric and compares against a baseline query. Same output signal shape.

Both produce dicts matching ``otel-metric-signal.schema.json`` that ``IngestService``
can normalize alongside feature-flag and Kubernetes signals.

The design deliberately keeps these ingesters *stateless* — the Mesh trigger stage
is the place where "is this actionable?" lives. An ingester just surfaces what the
OTel layer said was anomalous; policy and thresholds stay in one place downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from shared.mesh_runtime.otel import (
    OtelMetric,
    OtelResourceMetrics,
    PrometheusClient,
    PrometheusQueryError,
    parse_otlp_metrics,
)


# Metric-name prefixes we recognize as latency-style measurements. Treating these as
# "higher is worse" means a baseline→observed ratio > 1 is a regression. Anything
# outside this set falls back to the caller-supplied alert context.
_LATENCY_HINTS = ("latency", "duration", "response_time", "rtt", "wait")
# Metric-name prefixes we treat as error-rate / failure signals.
_ERROR_HINTS = ("error", "failure", "fail", "5xx", "fault")


@dataclass
class AlertContext:
    """Optional context accompanying an OTLP push when the sender knows which metric tripped.

    OTel Collector's alertmanager-style routes can forward both the metric sample and
    the rule that matched. When we have this context, we use it directly; otherwise we
    fall back to heuristics.
    """

    metric_name: str | None = None
    service: str | None = None
    environment: str | None = None
    baseline_value: float | None = None
    threshold_pct: float | None = None
    region: str | None = None
    customer_tier: str | None = None
    endpoint: str | None = None


class OtlpPushIngester:
    """Map an incoming OTLP/HTTP JSON metrics payload to a Mesh signal dict.

    The returned dict conforms to ``otel-metric-signal.schema.json`` and feeds
    directly into ``IngestService.normalize_signal``.
    """

    def build_signal(
        self,
        otlp_payload: dict[str, Any],
        alert_context: AlertContext | None = None,
    ) -> dict[str, Any]:
        resources = parse_otlp_metrics(otlp_payload)
        if not resources:
            raise ValueError("otlp payload contained no resource metrics")

        chosen_resource, chosen_metric, chosen_value = self._pick_target_metric(resources, alert_context)
        baseline_value = self._resolve_baseline(alert_context, chosen_metric, chosen_value)
        delta_pct = _percent_delta(baseline_value, chosen_value)

        resource_attrs = chosen_resource.resource_attributes
        service = (
            (alert_context.service if alert_context and alert_context.service else None)
            or resource_attrs.get("service.name")
            or "unknown_service"
        )
        environment = (
            (alert_context.environment if alert_context and alert_context.environment else None)
            or resource_attrs.get("deployment.environment")
            or "unknown"
        )
        endpoint = self._resolve_endpoint(alert_context, chosen_metric, chosen_resource)

        now = datetime.now(timezone.utc)
        baseline_window_end = now - timedelta(minutes=10)
        baseline_window_start = baseline_window_end - timedelta(minutes=30)

        signal = {
            "signal_type": "otel_metric_regression",
            "signal_id": f"sig_otel_{uuid4().hex[:12]}",
            "observed_at": now.isoformat().replace("+00:00", "Z"),
            "environment": str(environment),
            "service": str(service),
            "endpoint": endpoint,
            "cluster": resource_attrs.get("k8s.cluster.name") or resource_attrs.get("cluster"),
            "namespace": resource_attrs.get("k8s.namespace.name") or resource_attrs.get("namespace"),
            "source": "otlp_push",
            "comparison_window": {
                "baseline": f"{baseline_window_start.isoformat()}/{baseline_window_end.isoformat()}",
                "observed": f"{baseline_window_end.isoformat()}/{now.isoformat()}",
            },
            "segment": {
                "customer_tier": (alert_context.customer_tier if alert_context else None) or "system",
                "region": (alert_context.region if alert_context else None) or resource_attrs.get("cloud.region", "unknown"),
            },
            "metric_regression": {
                "metric_name": chosen_metric.name,
                "metric_kind": chosen_metric.kind,
                "unit": chosen_metric.unit,
                "baseline_value": baseline_value,
                "observed_value": chosen_value,
                "delta_pct": delta_pct,
                "threshold_pct": alert_context.threshold_pct if alert_context else None,
                "attributes": _representative_attributes(chosen_metric),
            },
            "resource_attributes": resource_attrs,
            "related_metrics": _collect_related_metrics(chosen_resource, exclude=chosen_metric.name),
            "related_context": {
                "active_suppression": False,
                "incident_owned_by_human": False,
                "known_upstream_outage": False,
                "conflicting_signals": False,
                "rollbacks_last_24h": 0,
                "regressions_last_7d": 0,
            },
            "post_action_observations": {},
        }
        return signal

    def _pick_target_metric(
        self,
        resources: list[OtelResourceMetrics],
        alert_context: AlertContext | None,
    ) -> tuple[OtelResourceMetrics, OtelMetric, float]:
        """Pick the metric + data point that best represents the regression.

        If the alert names a specific metric, use it. Otherwise fall back to scoring
        each candidate by how strongly it looks like a latency or error signal — a
        deliberately simple heuristic that works for ~80% of real-world exporters
        without requiring users to configure mappings upfront.
        """
        if alert_context and alert_context.metric_name:
            for resource in resources:
                for metric in resource.metrics:
                    if metric.name == alert_context.metric_name and metric.data_points:
                        return resource, metric, metric.data_points[-1].value
        # Heuristic fallback — pick the first metric with a hint match and a data point.
        for hint_set in (_LATENCY_HINTS, _ERROR_HINTS):
            for resource in resources:
                for metric in resource.metrics:
                    if not metric.data_points:
                        continue
                    name_lower = metric.name.lower()
                    if any(hint in name_lower for hint in hint_set):
                        return resource, metric, metric.data_points[-1].value
        # Last resort: any metric with a data point.
        for resource in resources:
            for metric in resource.metrics:
                if metric.data_points:
                    return resource, metric, metric.data_points[-1].value
        raise ValueError("otlp payload contained no data points we could score")

    def _resolve_baseline(
        self,
        alert_context: AlertContext | None,
        metric: OtelMetric,
        observed_value: float,
    ) -> float:
        """Figure out what "normal" looks like for this metric.

        Order of precedence: alert-supplied baseline > first data point in the stream
        (useful when a sender sends a [baseline, observed] pair) > observed value
        (degenerate, delta_pct ends up 0 — the trigger stage will then rely on absolute
        thresholds from policy).
        """
        if alert_context and alert_context.baseline_value is not None:
            return float(alert_context.baseline_value)
        if len(metric.data_points) >= 2:
            return float(metric.data_points[0].value)
        return float(observed_value)

    def _resolve_endpoint(
        self,
        alert_context: AlertContext | None,
        metric: OtelMetric,
        resource: OtelResourceMetrics,
    ) -> str:
        if alert_context and alert_context.endpoint:
            return alert_context.endpoint
        # Common OTel semantic convention attributes that identify an endpoint.
        for attr_key in ("http.route", "http.target", "rpc.method", "db.operation", "messaging.destination.name"):
            for point in metric.data_points:
                if attr_key in point.attributes:
                    return str(point.attributes[attr_key])
            if attr_key in resource.resource_attributes:
                return str(resource.resource_attributes[attr_key])
        return metric.name


class PrometheusPullIngester:
    """Produce a Mesh signal from a pair of PromQL queries.

    A typical use: "query error rate for service X over the last 5 minutes, compare
    against a 1-hour baseline, emit a signal if the ratio is above threshold".
    The pull variant is preferred over push when Mesh owns the schedule — e.g. a
    periodic audit sweep, or a feedback-stage verification.
    """

    def __init__(self, client: PrometheusClient):
        self.client = client

    def build_signal(
        self,
        *,
        service: str,
        endpoint: str,
        environment: str,
        metric_name: str,
        observed_query: str,
        baseline_query: str,
        threshold_pct: float | None = None,
        region: str | None = None,
        customer_tier: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a signal dict, or ``None`` if the queries returned no data.

        We deliberately return ``None`` on a missing observed value rather than raise
        — the feedback stage runs this on a polling loop and treating "no data" as a
        fatal error would generate pager noise out of a monitoring outage.
        """
        try:
            observed = self.client.instant_query(observed_query)
            baseline = self.client.instant_query(baseline_query)
        except PrometheusQueryError:
            return None
        if observed is None or baseline is None:
            return None

        now = datetime.now(timezone.utc)
        baseline_window_end = now - timedelta(minutes=5)
        baseline_window_start = baseline_window_end - timedelta(minutes=60)
        return {
            "signal_type": "otel_metric_regression",
            "signal_id": f"sig_prom_{uuid4().hex[:12]}",
            "observed_at": now.isoformat().replace("+00:00", "Z"),
            "environment": environment,
            "service": service,
            "endpoint": endpoint,
            "cluster": None,
            "namespace": None,
            "source": "prometheus_pull",
            "comparison_window": {
                "baseline": f"{baseline_window_start.isoformat()}/{baseline_window_end.isoformat()}",
                "observed": f"{baseline_window_end.isoformat()}/{now.isoformat()}",
            },
            "segment": {
                "customer_tier": customer_tier or "system",
                "region": region or "unknown",
            },
            "metric_regression": {
                "metric_name": metric_name,
                "metric_kind": "prometheus_query",
                "unit": None,
                "baseline_value": baseline,
                "observed_value": observed,
                "delta_pct": _percent_delta(baseline, observed),
                "threshold_pct": threshold_pct,
                "attributes": {},
            },
            "resource_attributes": {
                "service.name": service,
                "deployment.environment": environment,
            },
            "related_metrics": [],
            "related_context": {},
            "post_action_observations": {},
        }


def _percent_delta(baseline: float, observed: float) -> float | None:
    """Percentage change from ``baseline`` to ``observed``.

    Returns ``None`` when the baseline is zero (division-undefined) so downstream
    serializers can emit ``null`` instead of an ``inf`` that would break JSON.
    """
    if baseline == 0:
        return None
    return round(((observed - baseline) / baseline) * 100.0, 2)


def _representative_attributes(metric: OtelMetric) -> dict[str, Any]:
    if not metric.data_points:
        return {}
    return dict(metric.data_points[-1].attributes)


def _collect_related_metrics(resource: OtelResourceMetrics, exclude: str) -> list[dict[str, Any]]:
    """Capture the other metrics in the same resource bundle as context.

    Feeding these into the decision stage lets Mesh correlate: e.g. if the primary
    regression is latency but error_rate is also spiking, the decision engine can
    prefer ``disable_flag`` over ``reduce_rollout`` because the blast radius is wider.
    """
    related: list[dict[str, Any]] = []
    for metric in resource.metrics:
        if metric.name == exclude or not metric.data_points:
            continue
        point = metric.data_points[-1]
        related.append(
            {
                "metric_name": metric.name,
                "value": point.value,
                "attributes": dict(point.attributes),
            }
        )
    return related
