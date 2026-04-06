"""Normalize raw infrastructure-healing signals into a shared event envelope."""

from __future__ import annotations

from shared.mesh_runtime import EventEnvelope


class IngestService:
    def normalize_signal(self, raw_signal: dict) -> EventEnvelope:
        return EventEnvelope(
            event_type="normalized_signal",
            object_id=raw_signal["signal_id"],
            schema_version="v1",
            emitted_at=raw_signal["observed_at"],
            payload={
                "environment": raw_signal["environment"],
                "service": raw_signal["service"],
                "endpoint": raw_signal["endpoint"],
                "segment": raw_signal["segment"],
                "baseline": raw_signal["baseline"],
                "observed": raw_signal["observed"],
                "related_changes": raw_signal["related_changes"],
                "evidence_quality": raw_signal["evidence_quality"],
                "persistent_regression": raw_signal.get("persistent_regression", False),
            },
            summary={
                "service": raw_signal["service"],
                "endpoint": raw_signal["endpoint"],
                "segment": raw_signal["segment"],
            },
        )
