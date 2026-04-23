"""OpenTelemetry ingest helpers: OTLP/HTTP JSON parsing + Prometheus query client.

Mesh consumes OpenTelemetry signals as a first-class input. This module provides the
vendor-neutral plumbing without pulling in the full ``opentelemetry-sdk`` dependency,
which would bloat the runtime image for a small set of parsing concerns.

Two surfaces:

1. :func:`parse_otlp_metrics` — parse an OTLP/HTTP JSON metrics payload
   (https://opentelemetry.io/docs/specs/otlp/) into a normalized Python structure.
2. :class:`PrometheusClient` — minimal PromQL HTTP client for pull-based metric
   lookups (used by the feedback stage to verify remediation outcomes with real data).

The parsing intentionally stays permissive: OTLP producers vary in how they populate
optional fields, and we prefer to surface what we can rather than reject a payload
over one missing attribute.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OtelDataPoint:
    """A single metric data point extracted from OTLP."""

    value: float
    timestamp_ns: int
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class OtelMetric:
    """One metric stream from an OTLP payload.

    ``kind`` captures the OTLP metric shape (``gauge``, ``sum``, ``histogram``,
    ``summary``). Downstream consumers usually only care about whether the value is
    a point estimate (gauge/sum/summary) or a distribution (histogram).
    """

    name: str
    kind: str
    unit: str | None
    description: str | None
    data_points: list[OtelDataPoint] = field(default_factory=list)


@dataclass
class OtelResourceMetrics:
    """A resource-scoped bundle of metric streams.

    OTLP groups metrics by the resource that emitted them (service, host, cluster).
    ``resource_attributes`` carries the identifying labels — notably
    ``service.name`` and ``deployment.environment``, which we map into the Mesh
    signal envelope.
    """

    resource_attributes: dict[str, Any]
    scope_name: str | None
    metrics: list[OtelMetric]


def parse_otlp_metrics(payload: dict[str, Any]) -> list[OtelResourceMetrics]:
    """Parse an OTLP/HTTP JSON metrics payload.

    Returns one :class:`OtelResourceMetrics` per ``resourceMetrics`` entry. Unknown
    metric kinds are preserved as ``kind="unknown"`` with empty data points so the
    caller can log and skip without crashing the receiver.
    """
    results: list[OtelResourceMetrics] = []
    for resource_metrics in payload.get("resourceMetrics", []):
        resource = resource_metrics.get("resource", {}) or {}
        resource_attrs = _flatten_attributes(resource.get("attributes", []))
        for scope_metrics in resource_metrics.get("scopeMetrics", []):
            scope = scope_metrics.get("scope", {}) or {}
            scope_name = scope.get("name")
            metrics: list[OtelMetric] = []
            for metric in scope_metrics.get("metrics", []):
                parsed = _parse_metric(metric)
                if parsed is not None:
                    metrics.append(parsed)
            if metrics:
                results.append(
                    OtelResourceMetrics(
                        resource_attributes=resource_attrs,
                        scope_name=scope_name,
                        metrics=metrics,
                    )
                )
    return results


def _parse_metric(metric: dict[str, Any]) -> OtelMetric | None:
    name = metric.get("name")
    if not name:
        return None
    description = metric.get("description") or None
    unit = metric.get("unit") or None
    # OTLP metric shape: exactly one of gauge, sum, histogram, exponentialHistogram, summary.
    if "gauge" in metric:
        kind = "gauge"
        points = _extract_number_points(metric["gauge"].get("dataPoints", []))
    elif "sum" in metric:
        kind = "sum"
        points = _extract_number_points(metric["sum"].get("dataPoints", []))
    elif "histogram" in metric:
        kind = "histogram"
        points = _extract_histogram_points(metric["histogram"].get("dataPoints", []))
    elif "summary" in metric:
        kind = "summary"
        points = _extract_summary_points(metric["summary"].get("dataPoints", []))
    else:
        kind = "unknown"
        points = []
    return OtelMetric(
        name=name,
        kind=kind,
        unit=unit,
        description=description,
        data_points=points,
    )


def _extract_number_points(raw_points: list[dict[str, Any]]) -> list[OtelDataPoint]:
    points: list[OtelDataPoint] = []
    for raw in raw_points:
        value = _coerce_number(raw)
        if value is None:
            continue
        points.append(
            OtelDataPoint(
                value=value,
                timestamp_ns=int(raw.get("timeUnixNano", 0) or 0),
                attributes=_flatten_attributes(raw.get("attributes", [])),
            )
        )
    return points


def _extract_histogram_points(raw_points: list[dict[str, Any]]) -> list[OtelDataPoint]:
    """Flatten histogram points to a single representative value.

    We use ``sum/count`` (the mean) as the representative value, which is good enough
    for threshold checks at the trigger stage. Callers that need the full bucket
    distribution can call :func:`parse_otlp_metrics` directly and inspect the raw
    payload themselves; this is a conscious simplification to keep the signal envelope
    flat.
    """
    points: list[OtelDataPoint] = []
    for raw in raw_points:
        count = raw.get("count")
        if count in (None, 0, "0"):
            continue
        total = raw.get("sum")
        if total is None:
            continue
        try:
            mean = float(total) / float(count)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        points.append(
            OtelDataPoint(
                value=mean,
                timestamp_ns=int(raw.get("timeUnixNano", 0) or 0),
                attributes=_flatten_attributes(raw.get("attributes", [])),
            )
        )
    return points


def _extract_summary_points(raw_points: list[dict[str, Any]]) -> list[OtelDataPoint]:
    """Use the highest-quantile value from summaries (typically p99 or p95).

    Summaries are less common than histograms in modern pipelines, but they show up
    in older Prometheus exporters. Picking the highest quantile keeps the signal
    regression-biased — we want to surface tail-latency issues, not p50 noise.
    """
    points: list[OtelDataPoint] = []
    for raw in raw_points:
        quantile_values = raw.get("quantileValues") or []
        if not quantile_values:
            continue
        best = max(quantile_values, key=lambda q: q.get("quantile", 0))
        try:
            value = float(best.get("value"))
        except (TypeError, ValueError):
            continue
        attrs = _flatten_attributes(raw.get("attributes", []))
        attrs["quantile"] = best.get("quantile")
        points.append(
            OtelDataPoint(
                value=value,
                timestamp_ns=int(raw.get("timeUnixNano", 0) or 0),
                attributes=attrs,
            )
        )
    return points


def _coerce_number(raw: dict[str, Any]) -> float | None:
    """OTLP encodes numbers as ``asInt`` or ``asDouble`` depending on the metric type."""
    if "asDouble" in raw and raw["asDouble"] is not None:
        try:
            return float(raw["asDouble"])
        except (TypeError, ValueError):
            return None
    if "asInt" in raw and raw["asInt"] is not None:
        try:
            return float(raw["asInt"])
        except (TypeError, ValueError):
            return None
    return None


def _flatten_attributes(raw_attributes: list[dict[str, Any]]) -> dict[str, Any]:
    """OTLP attributes are ``[{key: str, value: {stringValue|intValue|...}}, ...]``.

    We flatten that to a plain dict, unwrapping the typed value envelope so callers
    see ``{"service.name": "api-gateway"}`` instead of the nested form.
    """
    out: dict[str, Any] = {}
    for attr in raw_attributes:
        key = attr.get("key")
        if not key:
            continue
        value = attr.get("value") or {}
        for type_key in ("stringValue", "boolValue", "intValue", "doubleValue"):
            if type_key in value and value[type_key] is not None:
                out[key] = value[type_key]
                break
        else:
            if "arrayValue" in value:
                array = value["arrayValue"].get("values", [])
                out[key] = [_unwrap_scalar(v) for v in array]
    return out


def _unwrap_scalar(value: dict[str, Any]) -> Any:
    for type_key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if type_key in value:
            return value[type_key]
    return None


class PrometheusQueryError(RuntimeError):
    """Raised when a PromQL query fails or returns malformed data.

    Callers are expected to fall back to stub observations rather than fail the run —
    a metric lookup failure is an observability issue, not a remediation failure.
    """


class PrometheusClient:
    """Minimal Prometheus HTTP API client for instant and range queries.

    The full Prometheus client library is dependency-heavy and mostly redundant for
    the narrow read-only use case Mesh needs (a handful of queries per run). We speak
    the documented HTTP API directly.

    https://prometheus.io/docs/prometheus/latest/querying/api/
    """

    def __init__(self, base_url: str, timeout_seconds: float = 10.0, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.headers = dict(headers or {})

    def instant_query(self, query: str) -> float | None:
        """Run a PromQL instant query and return the first scalar value, or ``None``.

        Used for "what is the current error rate for service X" style lookups. If the
        query returns a vector with multiple series we take the first — callers that
        need disambiguation should pre-filter their PromQL with explicit label matchers.
        """
        url = f"{self.base_url}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
        data = self._fetch(url)
        result = data.get("data", {}).get("result", [])
        if not result:
            return None
        value_pair = result[0].get("value")
        if not value_pair or len(value_pair) < 2:
            return None
        try:
            return float(value_pair[1])
        except (TypeError, ValueError):
            return None

    def range_query(self, query: str, start_ts: float, end_ts: float, step_seconds: int = 60) -> list[tuple[float, float]]:
        """Run a PromQL range query and return ``[(timestamp_seconds, value), ...]``.

        Useful for the feedback stage — pulling 10 minutes of post-action metrics and
        checking whether the mean stayed within guardrails, instead of trusting a
        single instant sample.
        """
        params = {
            "query": query,
            "start": f"{start_ts}",
            "end": f"{end_ts}",
            "step": f"{step_seconds}s",
        }
        url = f"{self.base_url}/api/v1/query_range?{urllib.parse.urlencode(params)}"
        data = self._fetch(url)
        result = data.get("data", {}).get("result", [])
        if not result:
            return []
        series = result[0].get("values", [])
        samples: list[tuple[float, float]] = []
        for sample in series:
            if len(sample) < 2:
                continue
            try:
                samples.append((float(sample[0]), float(sample[1])))
            except (TypeError, ValueError):
                continue
        return samples

    def _fetch(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PrometheusQueryError(f"prometheus query failed: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PrometheusQueryError(f"prometheus returned invalid JSON: {exc}") from exc
        if payload.get("status") != "success":
            raise PrometheusQueryError(f"prometheus query status={payload.get('status')}: {payload.get('error')}")
        return payload
