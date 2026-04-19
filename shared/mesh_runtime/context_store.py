"""Context store — tracks service topology and incident history across runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .json_store import LockedJsonFile as _locked_json

_MAX_INCIDENTS = 200


class ContextStore:
    def __init__(self, state_directory: str | Path):
        self._context_dir = Path(state_directory) / "context"
        self._context_dir.mkdir(parents=True, exist_ok=True)
        self._services_path = self._context_dir / "services.json"
        self._incidents_path = self._context_dir / "incidents.json"

    def update_from_run(self, run_session_dict: dict[str, Any]) -> None:
        artifacts = run_session_dict.get("artifacts", {})
        trigger = artifacts.get("trigger", {})
        decision = artifacts.get("decision", {})
        feedback = artifacts.get("feedback", {})
        service = trigger.get("service") or decision.get("summary", "").split(" ")[-1]
        if not service:
            return
        now = datetime.now(timezone.utc).isoformat()
        outcome = feedback.get("outcome", "unknown")
        decision_type = decision.get("decision_type", "unknown")
        error_signatures = list(trigger.get("related_context", {}).get("error_signatures", []))
        deployment_name = trigger.get("related_context", {}).get("deployment_name")
        namespace = trigger.get("related_context", {}).get("namespace")
        run_id = run_session_dict.get("run_id")

        with _locked_json(self._services_path) as payload:
            services = payload.setdefault("services", {})
            record = services.setdefault(service, {
                "service_name": service,
                "last_seen": now,
                "deployment_names": [],
                "namespaces": [],
                "common_error_patterns": [],
                "total_runs": 0,
                "successful_runs": 0,
                "last_decision_type": None,
            })
            record["last_seen"] = now
            record["total_runs"] = record.get("total_runs", 0) + 1
            if outcome == "successful":
                record["successful_runs"] = record.get("successful_runs", 0) + 1
            record["last_decision_type"] = decision_type
            if deployment_name and deployment_name not in record.get("deployment_names", []):
                record.setdefault("deployment_names", []).append(deployment_name)
            if namespace and namespace not in record.get("namespaces", []):
                record.setdefault("namespaces", []).append(namespace)
            for sig in error_signatures:
                if sig not in record.get("common_error_patterns", []):
                    record.setdefault("common_error_patterns", []).append(sig)
                    if len(record["common_error_patterns"]) > 20:
                        record["common_error_patterns"] = record["common_error_patterns"][-20:]

        if error_signatures or decision_type != "no_action":
            with _locked_json(self._incidents_path) as payload:
                incidents = payload.setdefault("incidents", [])
                incidents.append({
                    "service": service,
                    "deployment": deployment_name,
                    "namespace": namespace,
                    "error_signature": "|".join(error_signatures) if error_signatures else decision_type,
                    "decision_type": decision_type,
                    "outcome": outcome,
                    "recorded_at": now,
                    "run_id": run_id,
                })
                if len(incidents) > _MAX_INCIDENTS:
                    payload["incidents"] = incidents[-_MAX_INCIDENTS:]

    def get_service_context(self, service_name: str) -> dict[str, Any]:
        if not self._services_path.exists():
            return {}
        with _locked_json(self._services_path) as payload:
            services = payload.get("services", {})
            record = services.get(service_name)
            if record is None:
                return {}
            total = record.get("total_runs", 0)
            successful = record.get("successful_runs", 0)
            return {
                "service_name": service_name,
                "total_runs": total,
                "successful_runs": successful,
                "success_rate": round(successful / total, 3) if total > 0 else None,
                "common_error_patterns": list(record.get("common_error_patterns", [])),
                "last_decision_type": record.get("last_decision_type"),
                "deployment_names": list(record.get("deployment_names", [])),
                "namespaces": list(record.get("namespaces", [])),
            }

    def get_similar_incidents(
        self,
        error_signature: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not self._incidents_path.exists():
            return []
        with _locked_json(self._incidents_path) as payload:
            incidents = payload.get("incidents", [])
            matches = []
            for incident in reversed(incidents):
                stored_sig = incident.get("error_signature", "")
                if error_signature in stored_sig or stored_sig in error_signature:
                    matches.append(dict(incident))
                    if len(matches) >= limit:
                        break
            return matches

    def list_services(self) -> list[dict[str, Any]]:
        if not self._services_path.exists():
            return []
        with _locked_json(self._services_path) as payload:
            return list(payload.get("services", {}).values())
