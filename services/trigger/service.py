"""Turn normalized operational signals into deduplicated trigger objects."""

from __future__ import annotations

import logging
from datetime import datetime

from shared.mesh_runtime import EventEnvelope, Trigger


_LOG = logging.getLogger("mesh.trigger")


class TriggerService:
    def detect(self, envelope: EventEnvelope) -> Trigger | None:
        payload = envelope.payload
        signal_type = payload.get("signal_type", "feature_flag")
        _LOG.info("trigger: detect signal_type=%s object_id=%s", signal_type, envelope.object_id)
        if signal_type == "kubernetes_deployment_issue":
            trigger = self._detect_kubernetes_trigger(envelope)
        elif signal_type == "otel_metric_regression":
            trigger = self._detect_otel_metric_trigger(envelope)
        else:
            trigger = self._detect_feature_flag_trigger(envelope)
        # Log the outcome in a single place so readers don't have to hunt
        # across three branch methods to see whether a trigger fired.
        if trigger is None:
            _LOG.info("trigger: no_trigger (signal did not satisfy thresholds or was suppressed)")
        else:
            _LOG.info(
                "trigger: fired type=%s service=%s endpoint=%s signals=%s",
                trigger.trigger_type,
                trigger.service,
                trigger.endpoint,
                trigger.related_context.get("trigger_signals")
                or trigger.related_context.get("error_signatures"),
            )
        return trigger

    def _detect_feature_flag_trigger(self, envelope: EventEnvelope) -> Trigger | None:
        payload = envelope.payload
        feature_flag = payload["feature_flag"]
        telemetry = payload["request_telemetry"]
        baseline = telemetry["baseline"]
        observed = telemetry["observed"]
        related_context = payload["related_context"]

        minutes_since_change = int(
            (
                _parse_timestamp(envelope.emitted_at) - _parse_timestamp(feature_flag["changed_at"])
            ).total_seconds()
            // 60
        )
        flag_changed_recently = 0 <= minutes_since_change <= 30
        sample_size_ok = telemetry["sample_size"] >= 500
        latency_worse = observed["p95_latency_ms"] >= baseline["p95_latency_ms"] * 1.25
        error_worse = baseline["error_rate"] > 0 and observed["error_rate"] >= baseline["error_rate"] * 1.5
        timeout_worse = observed.get("timeout_rate", 0.0) >= 0.02
        persistent = telemetry.get("persistent_windows", 0) >= 2
        trigger_signals: list[str] = []
        if latency_worse:
            trigger_signals.append("latency_regression")
        if error_worse:
            trigger_signals.append("error_regression")
        if timeout_worse:
            trigger_signals.append("timeout_regression")
        suppressed = (
            feature_flag.get("under_rollback", False)
            or related_context.get("active_suppression", False)
            or related_context.get("incident_owned_by_human", False)
            or related_context.get("known_upstream_outage", False)
        )

        if not flag_changed_recently or not sample_size_ok or not persistent or suppressed:
            return None

        if not (latency_worse or error_worse or timeout_worse):
            return None

        trigger_context = {
            "release_id": payload["deployment"]["release_id"],
            "active_incidents": related_context.get("active_incidents", 0),
            "similar_prior_cases": related_context.get("similar_prior_cases", 0),
            "rollbacks_last_24h": related_context.get("rollbacks_last_24h", 0),
            "regressions_last_7d": related_context.get("regressions_last_7d", 0),
            "minutes_since_flag_change": minutes_since_change,
            "trigger_signals": trigger_signals,
            "signal_quality": {
                "sample_size_ok": sample_size_ok,
                "persistent": persistent,
            },
            **related_context,
        }
        trigger = Trigger(
            trigger_id=f"trg_{envelope.object_id}",
            trigger_type="feature_flag_performance_regression",
            triggered_at=envelope.emitted_at,
            environment=payload["environment"],
            service=payload["service"],
            endpoint=payload["endpoint"],
            flag_key=feature_flag["flag_key"],
            current_rollout_pct=feature_flag["current_rollout_pct"],
            comparison_window=payload["comparison_window"],
            segment=payload["segment"],
            metrics={
                "baseline_p95_latency_ms": baseline["p95_latency_ms"],
                "observed_p95_latency_ms": observed["p95_latency_ms"],
                "baseline_error_rate": baseline["error_rate"],
                "observed_error_rate": observed["error_rate"],
                "baseline_timeout_rate": baseline.get("timeout_rate"),
                "observed_timeout_rate": observed.get("timeout_rate"),
                "sample_size": telemetry["sample_size"],
            },
            related_context=trigger_context,
        )
        trigger.validate()
        return trigger

    def _detect_kubernetes_trigger(self, envelope: EventEnvelope) -> Trigger | None:
        payload = envelope.payload
        deployment = payload["deployment"]
        related_context = payload["related_context"]
        log_summary = payload["log_summary"]
        pods = payload["pods"]

        suppressed = (
            related_context.get("active_suppression", False)
            or related_context.get("incident_owned_by_human", False)
            or related_context.get("known_upstream_outage", False)
        )
        rollout_unhealthy = deployment["rollout_status"] in {"degraded", "failed"}
        failing_pods = [pod for pod in pods if not pod.get("ready", False) or int(pod.get("restarts", 0)) > 0]
        if suppressed or (not rollout_unhealthy and not failing_pods):
            return None

        trigger_signals = list(log_summary.get("error_signatures", []))
        trigger = Trigger(
            trigger_id=f"trg_{envelope.object_id}",
            trigger_type="kubernetes_deployment_unhealthy",
            triggered_at=envelope.emitted_at,
            environment=payload["environment"],
            service=payload["service"],
            endpoint=f"deployment/{deployment['name']}",
            flag_key=None,
            current_rollout_pct=None,
            comparison_window=payload.get("comparison_window"),
            segment=payload["segment"],
            metrics={
                "baseline_p95_latency_ms": None,
                "observed_p95_latency_ms": None,
                "baseline_error_rate": None,
                "observed_error_rate": None,
                "baseline_timeout_rate": None,
                "observed_timeout_rate": None,
                "sample_size": None,
                "restart_count_total": log_summary.get("restart_count_total", 0),
                "desired_replicas": deployment["desired_replicas"],
                "available_replicas": deployment["available_replicas"],
            },
            related_context={
                "release_id": deployment["revision"],
                "active_incidents": related_context.get("active_incidents", 0),
                "similar_prior_cases": related_context.get("similar_prior_cases", 0),
                "rollbacks_last_24h": related_context.get("rollbacks_last_24h", 0),
                "cluster": payload["cluster"],
                "namespace": payload["namespace"],
                "deployment_name": deployment["name"],
                "deployment_image": deployment["image"],
                "rollout_status": deployment["rollout_status"],
                "error_signatures": trigger_signals,
                "likely_layer": log_summary.get("likely_layer"),
                "event_reasons": log_summary.get("event_reasons", []),
                "primary_symptom": log_summary.get("primary_symptom"),
                "log_summary": log_summary,
                **related_context,
            },
        )
        trigger.validate()
        return trigger


    def _detect_otel_metric_trigger(self, envelope: EventEnvelope) -> Trigger | None:
        """Emit a trigger for an OTel metric regression signal.

        OTel signals don't fit the feature-flag or Kubernetes shapes. The trigger
        we produce here is intentionally thin — the real decision lives in the
        metric-action rule engine, which reads the full ``metric_regression``
        block out of ``related_context``. We still run the basic suppression
        checks (incident owned by human, upstream outage) so a runaway alert
        stream doesn't flood the system during a known incident.
        """
        payload = envelope.payload
        metric_regression = payload.get("metric_regression") or {}
        related_context = payload.get("related_context") or {}

        suppressed = (
            related_context.get("active_suppression", False)
            or related_context.get("incident_owned_by_human", False)
            or related_context.get("known_upstream_outage", False)
        )
        if suppressed:
            return None

        # A regression with no numeric delta and no threshold crossing is a
        # metrics pipeline artifact, not something worth running the full
        # pipeline for. Emit nothing so the run ends at no_trigger.
        delta_pct = metric_regression.get("delta_pct")
        observed = metric_regression.get("observed_value")
        baseline = metric_regression.get("baseline_value")
        if delta_pct is None and observed == baseline:
            return None

        trigger_signals = [f"metric_regression:{metric_regression.get('metric_name')}"]

        trigger_context = {
            "release_id": related_context.get("release_id"),
            "active_incidents": int(related_context.get("active_incidents", 0)),
            "similar_prior_cases": int(related_context.get("similar_prior_cases", 0)),
            "rollbacks_last_24h": int(related_context.get("rollbacks_last_24h", 0)),
            "regressions_last_7d": int(related_context.get("regressions_last_7d", 0)),
            "metric_regression": metric_regression,
            "resource_attributes": payload.get("resource_attributes", {}),
            "related_metrics": payload.get("related_metrics", []),
            "otel_source": payload.get("source"),
            "trigger_signals": trigger_signals,
            "cluster": payload.get("cluster"),
            "namespace": payload.get("namespace"),
            **{k: v for k, v in related_context.items() if k not in {
                "release_id",
                "active_incidents",
                "similar_prior_cases",
                "rollbacks_last_24h",
                "regressions_last_7d",
            }},
        }

        trigger = Trigger(
            trigger_id=f"trg_{envelope.object_id}",
            trigger_type="otel_metric_regression",
            triggered_at=envelope.emitted_at,
            environment=payload["environment"],
            service=payload["service"],
            endpoint=payload["endpoint"],
            flag_key=None,
            current_rollout_pct=None,
            comparison_window=payload.get("comparison_window"),
            segment=payload.get("segment", {"customer_tier": "system", "region": "unknown"}),
            # Metrics block: we always provide the canonical four latency/error
            # fields so downstream schema validation passes, but they're only
            # meaningful when the signal itself carried a latency or error
            # projection. Rule-based decisions read metric_regression directly.
            metrics={
                "baseline_p95_latency_ms": _metric_projection(payload, "p95_latency_ms", "baseline"),
                "observed_p95_latency_ms": _metric_projection(payload, "p95_latency_ms", "observed"),
                "baseline_error_rate": _metric_projection(payload, "error_rate", "baseline"),
                "observed_error_rate": _metric_projection(payload, "error_rate", "observed"),
                "baseline_timeout_rate": None,
                "observed_timeout_rate": None,
                "sample_size": payload.get("request_telemetry", {}).get("sample_size", 1),
            },
            related_context=trigger_context,
        )
        trigger.validate()
        return trigger


def _metric_projection(payload: dict, field: str, window: str) -> float | None:
    """Pull a latency or error projection from the payload when present.

    When the OTel signal was a latency metric, ``IngestService`` projects it
    into ``request_telemetry`` so the decision engine's existing thresholds
    still work. For non-projected signals (``kafka.consumer.lag``,
    ``memory.usage``, etc.), we return ``None`` — the trigger schema allows
    nulls for these fields and the rule engine reads ``metric_regression``
    directly.
    """
    telemetry = payload.get("request_telemetry")
    if not telemetry:
        return None
    bucket = telemetry.get(window) or {}
    value = bucket.get(field)
    return float(value) if value is not None else None


def _parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
