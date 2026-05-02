"""Normalize raw infrastructure-healing signals into a shared event envelope."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from shared.mesh_runtime import EventEnvelope, validate_payload

from .kubernetes_summary import summarize_kubernetes_logs

if TYPE_CHECKING:
    from services.signal_history import SignalHistoryStore
    from shared.mesh_runtime.learning import LearningStore


# Logger name follows the ``mesh.<component>.<area>`` pattern used elsewhere
# in the codebase (see services/actuators/systemd_ssh.py,
# services/control_plane.py) so the harness's root ``mesh`` FileHandler
# captures it automatically.
_LOG = logging.getLogger("mesh.ingest")


class IngestService:
    def __init__(
        self,
        learning_store: LearningStore | None = None,
        *,
        signal_history: "SignalHistoryStore | None" = None,
    ) -> None:
        self.learning_store = learning_store
        # Per-target signal history (S2 fix): every normalized envelope is
        # recorded so the decision service and LLM observer can read trends.
        # Optional so unit tests that don't care about history can omit it.
        self.signal_history = signal_history

    def normalize_signal(self, raw_signal: dict) -> EventEnvelope:
        """Normalize and record. The history-write hook is HERE rather
        than at every per-type return so it covers all signal kinds
        uniformly: any new signal type added to ``_dispatch_normalize``
        gets historicized for free."""
        envelope = self._dispatch_normalize(raw_signal)
        self._record_to_history(envelope)
        return envelope

    def _record_to_history(self, envelope: EventEnvelope) -> None:
        """Write the envelope to the per-target ring buffer, if a
        history store is configured. Best-effort: any failure here logs
        and falls through — history is auxiliary, not on the critical
        decision path."""
        if self.signal_history is None:
            return
        try:
            from services.signal_history import SignalRecord, derive_target_id
            target_id = derive_target_id(envelope)
            if target_id is None:
                return  # signal type not history-keyed yet
            record = SignalRecord(
                target_id=target_id,
                signal_type=str(envelope.payload.get("signal_type", "")),
                observed_at=_parse_envelope_emitted_at(envelope.emitted_at),
                payload=envelope.payload,
                summary=envelope.summary,
            )
            self.signal_history.add(record)
        except Exception:
            _LOG.exception("ingest: signal_history.add failed (non-fatal)")

    def _dispatch_normalize(self, raw_signal: dict) -> EventEnvelope:
        signal_type = raw_signal.get("signal_type") or "feature_flag"
        # One line per stage entry gives readers a reliable cursor when
        # scanning the server log. Keep it short — detail belongs in the
        # stage-specific logs below, not in this header.
        _LOG.info(
            "ingest: signal_type=%s service=%s signal_id=%s",
            signal_type, raw_signal.get("service"), raw_signal.get("signal_id"),
        )
        if signal_type == "otel_metric_regression":
            return self._normalize_otel_signal(raw_signal)
        if signal_type == "reth_node":
            return self._normalize_reth_node_signal(raw_signal)
        if signal_type == "webhook_alert":
            return self._normalize_webhook_signal(raw_signal)
        if signal_type == "kubernetes_deployment_issue":
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
            _LOG.info(
                "ingest: kubernetes deployment=%s rollout_status=%s pods=%d events=%d error_signatures=%s",
                deployment["name"],
                deployment.get("rollout_status"),
                len(raw_signal.get("pods", [])),
                len(raw_signal.get("events", [])),
                log_summary.get("error_signatures", []),
            )
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

    def _normalize_webhook_signal(self, raw_signal: dict) -> EventEnvelope:
        alert_event = raw_signal.get("alert_event", {})
        labels = alert_event.get("labels", {}) if isinstance(alert_event, dict) else {}
        related_context = {
            "active_suppression": False,
            "incident_owned_by_human": False,
            "known_upstream_outage": False,
            "active_incidents": 0,
            "similar_prior_cases": 0,
            "incident_credentials_available": True,
            "audit_logging_available": True,
            "webhook_source_id": alert_event.get("source_id"),
            "webhook_alert_id": alert_event.get("alert_id"),
            "webhook_action": alert_event.get("action", "fire"),
            "webhook_source_type": alert_event.get("template_source_type"),
            "severity": raw_signal.get("severity") or alert_event.get("severity"),
            "labels": labels,
            "annotations": {},
        }
        related_context.update(raw_signal.get("related_context", {}))
        self._enrich_from_learning(
            related_context,
            raw_signal.get("service", ""),
            raw_signal.get("endpoint"),
        )
        return EventEnvelope(
            event_type="normalized_signal",
            object_id=raw_signal["signal_id"],
            schema_version="v1",
            emitted_at=raw_signal["observed_at"],
            payload={
                "signal_type": "webhook_alert",
                "environment": raw_signal["environment"],
                "service": raw_signal["service"],
                "endpoint": raw_signal["endpoint"],
                "segment": raw_signal.get(
                    "segment",
                    {
                        "customer_tier": labels.get("customer_tier", "system"),
                        "region": labels.get("region") or labels.get("cluster") or "unknown",
                    },
                ),
                "comparison_window": None,
                "webhook": {
                    "source_id": alert_event.get("source_id"),
                    "alert_id": alert_event.get("alert_id"),
                    "action": alert_event.get("action", "fire"),
                    "severity": raw_signal.get("severity") or alert_event.get("severity"),
                    "title": raw_signal.get("title") or alert_event.get("title"),
                    "description": raw_signal.get("description") or alert_event.get("description"),
                    "labels": labels,
                    "annotations": {},
                    "raw_event": alert_event,
                },
                "related_context": related_context,
                "post_action_observations": raw_signal.get("post_action_observations", {}),
            },
            summary={
                "service": raw_signal["service"],
                "endpoint": raw_signal["endpoint"],
                "alert_id": alert_event.get("alert_id"),
                "source_id": alert_event.get("source_id"),
            },
        )

    def _normalize_reth_node_signal(self, raw_signal: dict) -> EventEnvelope:
        validate_payload("reth-node-signal.schema.json", raw_signal)

        node = raw_signal["node"]
        execution = raw_signal["execution"]
        consensus = raw_signal["consensus"]
        storage = raw_signal["storage"]
        rpc = raw_signal["rpc"]
        related_context = {
            "release_id": node.get("client_version"),
            "active_suppression": False,
            "incident_owned_by_human": False,
            "known_upstream_outage": False,
            "active_incidents": 0,
            "similar_prior_cases": 0,
            "rollbacks_last_24h": 0,
            "regressions_last_7d": 0,
        }
        related_context.update(raw_signal.get("related_context", {}))
        related_context.update({
            "node": node,
            "execution": execution,
            "consensus": consensus,
            "storage": storage,
            "rpc": rpc,
            "logs": raw_signal["logs"],
            "resource_attributes": raw_signal["resource_attributes"],
        })
        self._enrich_from_learning(related_context, raw_signal["service"], "reth.node")

        _LOG.info(
            "ingest: reth node=%s peers=%s block_lag=%s syncing=%s signatures=%s",
            node["name"],
            execution["peer_count"],
            execution["block_lag"],
            execution["syncing"],
            raw_signal["logs"].get("error_signatures", []),
        )
        return EventEnvelope(
            event_type="normalized_signal",
            object_id=raw_signal["signal_id"],
            schema_version="v1",
            emitted_at=raw_signal["observed_at"],
            payload={
                "signal_type": "reth_node",
                "environment": raw_signal["environment"],
                "service": raw_signal["service"],
                "endpoint": "reth.node",
                "comparison_window": raw_signal.get("comparison_window"),
                "segment": raw_signal.get("segment", {"customer_tier": "system", "region": "unknown"}),
                "node": node,
                "execution": execution,
                "consensus": consensus,
                "storage": storage,
                "rpc": rpc,
                "logs": raw_signal["logs"],
                "resource_attributes": raw_signal["resource_attributes"],
                "related_context": related_context,
                "post_action_observations": raw_signal.get("post_action_observations", {}),
            },
            summary={
                "service": raw_signal["service"],
                "endpoint": "reth.node",
                "peer_count": execution["peer_count"],
                "block_lag": execution["block_lag"],
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


def _parse_envelope_emitted_at(s: str) -> datetime:
    """Tolerant ISO-8601 parse for envelope timestamps. Handles 'Z' suffix
    that Python's ``fromisoformat`` is brittle about across versions."""
    if isinstance(s, datetime):
        return s
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
