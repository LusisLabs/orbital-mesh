"""Local actuator adapters used by the native orchestration integration."""

from __future__ import annotations

from shared.mesh_runtime import Decision


class FeatureFlagAdapter:
    def set_rollout(self, parameters: dict) -> dict:
        return {
            "status": "succeeded",
            "external_refs": {"flag_change_id": f"ffchg_{parameters['flag_key']}_{parameters['rollout_pct']}"},
        }


class IncidentAdapter:
    def open_incident(self, parameters: dict) -> dict:
        incident_scope = parameters.get("service") or parameters.get("decision_id") or parameters.get("flag_key") or "unknown"
        return {
            "status": "succeeded",
            "external_refs": {"incident_id": f"inc_{incident_scope}"},
        }


class AuditLogAdapter:
    def write_record(self, decision: Decision, idempotency_key: str) -> dict:
        return {
            "status": "succeeded",
            "audit_log_id": f"audit_{decision.decision_id}",
            "idempotency_key": idempotency_key,
        }
