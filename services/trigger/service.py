"""Turn normalized operational signals into deduplicated trigger objects."""

from __future__ import annotations

from shared.mesh_runtime import EventEnvelope, Trigger


class TriggerService:
    def detect(self, envelope: EventEnvelope) -> Trigger | None:
        payload = envelope.payload
        baseline = payload["baseline"]
        observed = payload["observed"]

        latency_worse = observed["p95_latency_ms"] >= baseline["p95_latency_ms"] * 1.25
        error_worse = observed["error_rate"] >= baseline["error_rate"] * 1.25
        persistent = payload.get("persistent_regression", False)

        if not latency_worse or not (error_worse or persistent):
            return None

        trigger = Trigger(
            trigger_id=f"trg_{envelope.object_id}",
            trigger_type="performance_regression",
            triggered_at=envelope.emitted_at,
            scope={
                "environment": payload["environment"],
                "service": payload["service"],
                "endpoint": payload["endpoint"],
                "segment": payload["segment"],
            },
            symptoms=[
                {
                    "metric": "p95_latency_ms",
                    "baseline": baseline["p95_latency_ms"],
                    "observed": observed["p95_latency_ms"],
                    "delta_pct": round(
                        ((observed["p95_latency_ms"] - baseline["p95_latency_ms"]) / baseline["p95_latency_ms"]) * 100,
                        1,
                    ),
                },
                {
                    "metric": "error_rate",
                    "baseline": baseline["error_rate"],
                    "observed": observed["error_rate"],
                    "delta_pct": round(
                        ((observed["error_rate"] - baseline["error_rate"]) / baseline["error_rate"]) * 100,
                        1,
                    ),
                },
            ],
            related_changes=payload["related_changes"],
            evidence_quality=payload["evidence_quality"],
            dedupe_key=":".join(
                [
                    payload["environment"],
                    payload["service"],
                    payload["endpoint"],
                    payload["segment"],
                ]
            ),
        )
        trigger.validate()
        return trigger
