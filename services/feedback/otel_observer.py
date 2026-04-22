"""Real post-action observations sourced from Prometheus / OTel metrics.

The default feedback flow trusts whatever ``post_action_observations`` the signal
carries — fine for fixtures and replay, useless for a live deployment where we
need to verify the remediation actually worked. This module plugs a PromQL
client into the feedback stage so the 10m/30m windows come from real data.

Usage: a coordinator wires :class:`PrometheusFeedbackObserver` and passes it to
``FeedbackService.record_with_live_metrics``. If the observer is absent or the
query fails, the feedback stage silently falls back to the stub observations —
we never want a monitoring outage to make a run look like it failed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from shared.mesh_runtime.otel import PrometheusClient, PrometheusQueryError


_LOG = logging.getLogger("mesh.feedback.otel")


@dataclass
class MetricWindowResult:
    """Result of a single window-over-metric query.

    ``value`` is ``None`` when Prometheus returned no data — the caller then
    chooses whether to treat that as ``not_achieved`` (conservative) or fall back
    to the signal's stub observation (permissive).
    """

    value: float | None
    measured_at: str


class PrometheusFeedbackObserver:
    """Sample real metrics N minutes after execution to build ``post_action_observations``.

    The shape of the returned dict matches what ``FeedbackService`` already expects:
    ``{"10m": {...}, "30m": {...}}``. That keeps the feedback logic unchanged and
    makes OTel-backed observations a drop-in replacement for the stub ones.

    Two query templates are configurable per service — one for latency, one for
    error rate — because those are the two axes the existing feedback judges use.
    Templates use ``{service}`` and ``{window}`` placeholders that get substituted
    at query time.
    """

    def __init__(
        self,
        client: PrometheusClient,
        latency_query_template: str,
        error_rate_query_template: str,
    ):
        self.client = client
        self.latency_query_template = latency_query_template
        self.error_rate_query_template = error_rate_query_template

    def observe(self, service: str, window_label: str) -> dict[str, Any]:
        """Return only the measurement keys the observer can fill from live data.

        Deliberately narrow: we emit ``measured_at`` and ``source`` to stamp
        provenance, plus ``p95_latency_ms`` and ``error_rate`` when Prometheus has
        data. Everything else (``side_effects``, ``business_guardrail_breached``,
        ``observed_time_to_effect``) must be supplied by the stub observations on
        the signal — we don't want defaults here to clobber context the sender
        already provided.
        """
        latency = self._query(self.latency_query_template, service, window_label)
        error_rate = self._query(self.error_rate_query_template, service, window_label)
        observation: dict[str, Any] = {
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "source": "prometheus",
        }
        if latency.value is not None:
            observation["p95_latency_ms"] = latency.value
        if error_rate.value is not None:
            observation["error_rate"] = error_rate.value
        return observation

    def _query(self, template: str, service: str, window_label: str) -> MetricWindowResult:
        query = template.format(service=service, window=window_label)
        try:
            value = self.client.instant_query(query)
        except PrometheusQueryError as exc:
            # A monitoring gap should not make the remediation look like it failed.
            # Log and return None so the feedback judges fall back to the signal stub.
            _LOG.warning("prometheus query failed for service=%s window=%s: %s", service, window_label, exc)
            value = None
        return MetricWindowResult(
            value=value,
            measured_at=datetime.now(timezone.utc).isoformat(),
        )


def augment_observations(
    signal_observations: dict[str, Any] | None,
    observer: PrometheusFeedbackObserver | None,
    service: str,
) -> dict[str, Any]:
    """Merge stub observations with live Prometheus data.

    When an observer is supplied, the live values take precedence but never remove
    keys the signal already provided — this way sender-side context (``side_effects``,
    ``business_guardrail_breached``) survives even when Prometheus only gives us a
    point estimate of latency and error rate.
    """
    result: dict[str, Any] = {}
    stub = signal_observations or {}
    for window_label in ("10m", "30m"):
        stub_window = dict(stub.get(window_label, {}))
        if observer is not None:
            live = observer.observe(service, window_label)
            # Live data wins where it exists; stub fills anything live didn't provide.
            stub_window.update({k: v for k, v in live.items() if v is not None})
        result[window_label] = stub_window
    if "24h" in stub:
        result["24h"] = dict(stub["24h"])
    return result
