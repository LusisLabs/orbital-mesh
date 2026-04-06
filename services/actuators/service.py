"""Local actuator adapters used by the Goose mock integration."""

from __future__ import annotations


class FeatureFlagAdapter:
    def set_rollout(self, parameters: dict) -> dict:
        return {
            "status": "succeeded",
            "external_refs": {"flag_change_id": f"ff_{parameters['flag_key']}"},
            "checkpoint_result": {
                "window": "10m",
                "passed": True,
            },
        }


class IncidentAdapter:
    def open_incident(self, parameters: dict) -> dict:
        return {
            "status": "succeeded",
            "external_refs": {"incident_id": f"inc_{parameters['service']}"},
            "checkpoint_result": {
                "window": "0m",
                "passed": True,
            },
        }


class TrafficControlAdapter:
    def rebalance_pool(self, parameters: dict) -> dict:
        return {
            "status": "succeeded",
            "external_refs": {"traffic_change_id": f"tr_{parameters['service']}"},
            "checkpoint_result": {
                "window": "10m",
                "passed": True,
            },
        }
