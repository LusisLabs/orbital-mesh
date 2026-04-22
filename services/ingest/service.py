"""Normalize raw infrastructure-healing signals into a shared event envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.mesh_runtime import EventEnvelope, validate_payload

from .kubernetes_summary import summarize_kubernetes_logs

if TYPE_CHECKING:
    from shared.mesh_runtime.learning import LearningStore


class IngestService:
    def __init__(self, learning_store: LearningStore | None = None) -> None:
        self.learning_store = learning_store

    def normalize_signal(self, raw_signal: dict) -> EventEnvelope:
        if raw_signal.get("signal_type") == "otel_metric_regression":
            return self._normalize_otel_signal(raw_signal)
        if raw_signal.get("signal_type") == "kubernetes_deployment_issue":
            validate_payload("kubernetes-signal.schema.json", raw_signal)
            related_context = {
                "active_suppression": False,
                "incident_owned_by_human": False,
                "known_upstream_outage": False,
                "active_incidents": 0,
                "similar_prior_cases": 0,
                "rollbacks_last_24h": 0,
                "cluster_access_available": True,
            }
            related_context.update(raw_signal.get("related_context", {}))
            self._enrich_from_learning(related_context, raw_signal.get("service", ""), raw_signal.get("endpoint"))
            deployment = raw_signal["deployment"]
            log_summary = summarize_kubernetes_logs(raw_signal["logs"], raw_signal["events"], raw_signal["pods"])
            return EventEnvelope(
                event_type="normalized_signal",
                object_id=raw_signal["signal_id"],
                schema_version="v1",
                emitted_at=raw_signal["observed_at"],
                payload={
                    "signal_type": "kubernetes_deployment_issue",
                    "environment": raw_signal["environment"],
                    "service": raw_signal["service"],
                    "endpoint": f"deployment/{deployment['name']}",
                    "cluster": raw_signal["cluster"],
                    "namespace": raw_signal["namespace"],
                    "comparison_window": {
                        "baseline": f"revision:{deployment['revision']}-1",
                        "observed": f"revision:{deployment['revision']}",
                    },
                    "segment": {
                        "customer_tier": "system",
                        "region": raw_signal["cluster"],
                    },
                    "deployment": deployment,
                    "pods": raw_signal["pods"],
                    "events": raw_signal["events"],
                    "logs": raw_signal["logs"],
                    "log_summary": log_summary,
                    "related_context": related_context,
                    "post_action_observations": raw_signal.get("post_action_observations", {}),
                },
                summary={
                    "service": raw_signal["service"],
                    "endpoint": f"deployment/{deployment['name']}",
                    "deployment": deployment["name"],
                },
            )
        feature_flag = raw_signal["feature_flag"]
        request_telemetry = raw_signal["request_telemetry"]
        related_context = {
            "active_suppression": False,
            "incident_owned_by_human": False,
            "known_upstream_outage": False,
            "conflicting_signals": False,
            "high_business_impact": False,
            "rollbacks_last_24h": 0,
            "regressions_last_7d": 0,
            "multi_service_impact": False,
            "feature_flag_credentials_available": True,
            "incident_credentials_available": True,
            "audit_logging_available": True,
        }
        related_context.update(raw_signal.get("related_context", {}))
        self._enrich_from_learning(
            related_context,
            raw_signal.get("service", ""),
            raw_signal.get("endpoint"),
            flag_key=feature_flag.get("flag_key"),
        )

        return EventEnvelope(
            event_type="normalized_signal",
            object_id=raw_signal["signal_id"],
            schema_version="v1",
            emitted_at=raw_signal["observed_at"],
            payload={
                "environment": raw_signal["environment"],
                "service": raw_signal["service"],
                "endpoint": raw_signal["endpoint"],
                "comparison_window": raw_signal["comparison_window"],
                "segment": raw_signal["segment"],
                "feature_flag": {
                    "flag_key": feature_flag["flag_key"],
                    "variant": feature_flag.get("variant", "enabled"),
                    "current_rollout_pct": feature_flag["current_rollout_pct"],
                    "previous_rollout_pct": feature_flag.get("previous_rollout_pct", feature_flag["current_rollout_pct"]),
                    "changed_at": feature_flag["changed_at"],
                    "under_rollback": feature_flag.get("under_rollback", False),
                },
                "request_telemetry": {
                    "sample_size": request_telemetry["sample_size"],
                    "baseline": request_telemetry["baseline"],
                    "observed": request_telemetry["observed"],
                    "persistent_windows": request_telemetry.get("persistent_windows", 0),
                },
                "deployment": raw_signal["deployment"],
                "related_context": related_context,
                "post_action_observations": raw_signal.get("post_action_observations", {}),
            },
            summary={
                "service": raw_signal["service"],
                "endpoint": raw_signal["endpoint"],
                "flag_key": feature_flag["flag_key"],
            },
        )

    def _normalize_otel_signal(self, raw_signal: dict) -> EventEnvelope:
        """Normalize an OTel metric-regression signal.

        OTel signals describe a generic "metric X regressed from Y to Z" rather than
        the feature-flag or Kubernetes specifics the downstream stages were originally
        written for. To keep the decision engine thresholds unified, we project the
        observed/baseline pair into the existing ``request_telemetry`` shape when the
        metric is a recognized latency or error measurement. Anything else flows
        through as ``metric_regression`` only — trigger rules can match on that
        alternative shape without conflating it with the classic feature-flag flow.
        """
        validate_payload("otel-metric-signal.schema.json", raw_signal)

        metric = raw_signal["metric_regression"]
        metric_name_lower = metric["metric_name"].lower()
        baseline_value = float(metric["baseline_value"])
        observed_value = float(metric["observed_value"])

        related_context = {
            "active_suppression": False,
            "incident_owned_by_human": False,
            "known_upstream_outage": False,
            "conflicting_signals": False,
            "rollbacks_last_24h": 0,
            "regressions_last_7d": 0,
            "feature_flag_credentials_available": True,
            "incident_credentials_available": True,
            "audit_logging_available": True,
        }
        related_context.update(raw_signal.get("related_context", {}))
        self._enrich_from_learning(related_context, raw_signal["service"], raw_signal.get("endpoint"))

        # Project into request_telemetry when the metric shape is recognizable, so the
        # decision engine can treat this as a latency/error regression and reuse its
        # existing bounded-action menu. When the metric doesn't fit, we omit the
        # projection entirely — the decision engine falls back to the no_action path,
        # which is the right default for a signal we don't know how to act on.
        request_telemetry: dict | None = None
        if any(hint in metric_name_lower for hint in ("latency", "duration", "response_time", "rtt")):
            request_telemetry = {
                "sample_size": _coerce_sample_size(raw_signal),
                "baseline": {
                    "p95_latency_ms": baseline_value,
                    "error_rate": 0.0,
                    "timeout_rate": 0.0,
                },
                "observed": {
                    "p95_latency_ms": observed_value,
                    "error_rate": 0.0,
                    "timeout_rate": 0.0,
                },
                "persistent_windows": 2,
            }
        elif any(hint in metric_name_lower for hint in ("error", "failure", "fault", "5xx")):
            request_telemetry = {
                "sample_size": _coerce_sample_size(raw_signal),
                "baseline": {
                    "p95_latency_ms": 0.0,
                    "error_rate": baseline_value,
                    "timeout_rate": 0.0,
                },
                "observed": {
                    "p95_latency_ms": 0.0,
                    "error_rate": observed_value,
                    "timeout_rate": 0.0,
                },
                "persistent_windows": 2,
            }

        payload: dict = {
            "signal_type": "otel_metric_regression",
            "environment": raw_signal["environment"],
            "service": raw_signal["service"],
            "endpoint": raw_signal["endpoint"],
            "cluster": raw_signal.get("cluster"),
            "namespace": raw_signal.get("namespace"),
            "source": raw_signal.get("source", "otlp_push"),
            "comparison_window": raw_signal["comparison_window"],
            "segment": raw_signal.get("segment", {"customer_tier": "system", "region": "unknown"}),
            "metric_regression": metric,
            "resource_attributes": raw_signal.get("resource_attributes", {}),
            "related_metrics": raw_signal.get("related_metrics", []),
            "related_context": related_context,
            "post_action_observations": raw_signal.get("post_action_observations", {}),
        }
        if request_telemetry is not None:
            payload["request_telemetry"] = request_telemetry

        return EventEnvelope(
            event_type="normalized_signal",
            object_id=raw_signal["signal_id"],
            schema_version="v1",
            emitted_at=raw_signal["observed_at"],
            payload=payload,
            summary={
                "service": raw_signal["service"],
                "endpoint": raw_signal["endpoint"],
                "metric_name": metric["metric_name"],
            },
        )

    def _enrich_from_learning(
        self,
        related_context: dict,
        service: str,
        endpoint: str | None = None,
        flag_key: str | None = None,
    ) -> None:
        if self.learning_store is None or not service:
            return
        enrichment = self.learning_store.enrich_context(service, endpoint, flag_key)
        for key in ("similar_prior_cases", "rollbacks_last_24h", "regressions_last_7d"):
            if related_context.get(key, 0) == 0 and enrichment.get(key, 0) > 0:
                related_context[key] = enrichment[key]


def _coerce_sample_size(raw_signal: dict) -> int:
    """OTel signals don't always carry a sample size. Fall back to a safe default
    that lets the downstream trigger rules evaluate without being suppressed by a
    ``sample_size < min`` guard."""
    for attr in ("sample_size", "request_count"):
        value = raw_signal.get(attr)
        if isinstance(value, int) and value > 0:
            return value
    metric_attrs = raw_signal.get("metric_regression", {}).get("attributes", {})
    value = metric_attrs.get("sample_size") or metric_attrs.get("request_count")
    if isinstance(value, int) and value > 0:
        return value
    return 1000
