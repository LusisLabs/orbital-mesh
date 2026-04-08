"""Normalize raw infrastructure-healing signals into a shared event envelope."""

from __future__ import annotations

from shared.mesh_runtime import EventEnvelope, validate_payload

from .kubernetes_summary import summarize_kubernetes_logs


class IngestService:
    def normalize_signal(self, raw_signal: dict) -> EventEnvelope:
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
