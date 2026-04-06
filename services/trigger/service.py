"""Turn normalized operational signals into deduplicated trigger objects."""

from __future__ import annotations

from datetime import datetime

from shared.mesh_runtime import EventEnvelope, Trigger


class TriggerService:
    def detect(self, envelope: EventEnvelope) -> Trigger | None:
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


def _parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
