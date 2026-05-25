from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY = REPO_ROOT / "config" / "connector-certification.registry.json"

STATE_ORDER = {
    "disabled": 0,
    "mock": 1,
    "unfinished": 1,
    "read-only": 2,
    "proposal-only": 2,
    "staging-ready": 3,
    "pilot-ready": 4,
    "production-ready": 5,
}


def load_connector_certification_registry(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    registry_path = _resolve_path(path)
    if not registry_path.exists():
        return None
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_payload("connector-certification-registry.schema.json", payload)
    return payload


def connector_certification_registry_ready(path: str | None) -> bool:
    try:
        registry = load_connector_certification_registry(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError):
        return False
    return bool(registry and registry.get("connectors"))


def build_connector_certification_matrix(
    *,
    registry_path: str | None,
    runtime_states: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    connectors: dict[str, Any] = {}
    try:
        registry = load_connector_certification_registry(registry_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        registry = None
        blockers.append(f"connector_certification_registry_invalid:{exc}")
    if registry is None:
        blockers.append("connector_certification_registry_missing")
    else:
        observed = runtime_states or {}
        for record in registry.get("connectors", []):
            if not isinstance(record, dict):
                continue
            connector_id = str(record["connector_id"])
            runtime_record = observed.get(connector_id, {})
            certified_state = str(record["state"])
            observed_state = str(runtime_record.get("state") or certified_state)
            effective_state = _bounded_state(certified_state, observed_state)
            connector_blockers = list(record.get("blockers", []))
            if runtime_record.get("blockers"):
                connector_blockers.extend(str(item) for item in runtime_record["blockers"])
            credential_boundary = dict(record["credential_boundary"])
            connector_blockers.extend(
                _credential_boundary_blockers(
                    connector_id=connector_id,
                    state=effective_state,
                    credential_boundary=credential_boundary,
                    runtime_record=runtime_record,
                )
            )
            connectors[connector_id] = {
                "connector_id": connector_id,
                "display_name": str(record["display_name"]),
                "domain": str(record["domain"]),
                "state": effective_state,
                "certified_state": certified_state,
                "observed_state": observed_state,
                "required_before": str(record["required_before"]),
                "authority_posture": str(record["authority_posture"]),
                "credential_policy": str(record["credential_policy"]),
                "credential_boundary": credential_boundary,
                "degraded_behavior": str(record["degraded_behavior"]),
                "allowed_scopes": list(record.get("allowed_scopes", [])),
                "evidence_refs": list(record.get("evidence_refs", [])),
                "blockers": sorted(set(connector_blockers)),
            }
    packet = {
        "schema_version": "mesh.connector_certification.v1",
        "generated_at": _timestamp(),
        "status": "complete" if connectors and not blockers else "incomplete",
        "registry_path": _display_path(_resolve_path(registry_path)) if registry_path else None,
        "registry_sha256": (
            _sha256(_resolve_path(registry_path))
            if registry_path and _resolve_path(registry_path).exists()
            else None
        ),
        "connectors": connectors,
        "blockers": blockers,
    }
    validate_payload("connector-certification-matrix.schema.json", packet)
    return packet


def _bounded_state(certified_state: str, observed_state: str) -> str:
    if observed_state not in STATE_ORDER:
        observed_state = "mock"
    if certified_state not in STATE_ORDER:
        certified_state = "mock"
    if STATE_ORDER[observed_state] <= STATE_ORDER[certified_state]:
        return observed_state
    return certified_state


def _credential_boundary_blockers(
    *,
    connector_id: str,
    state: str,
    credential_boundary: dict[str, Any],
    runtime_record: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if connector_id != "kubernetes" and credential_boundary.get("production_actuator_credentials_allowed"):
        blockers.append("non_kubernetes_connector_allows_production_actuator_credentials")
    is_proposal_lane = state == "proposal-only"
    if is_proposal_lane and credential_boundary.get("production_actuator_credentials_allowed"):
        blockers.append("proposal_lane_allows_production_actuator_credentials")
    if is_proposal_lane and credential_boundary.get("repo_write_credentials_allowed"):
        blockers.append("proposal_lane_allows_repo_write_credentials")
    if is_proposal_lane and runtime_record.get("production_actuator_credentials_present"):
        blockers.append("proposal_lane_production_actuator_credentials_present")
    if is_proposal_lane and runtime_record.get("repo_write_credentials_present"):
        blockers.append("proposal_lane_repo_write_credentials_present")
    if runtime_record.get("break_glass_used") and not credential_boundary.get("break_glass_recording_required"):
        blockers.append("break_glass_used_without_recording_contract")
    return blockers


def _resolve_path(raw: str | None) -> Path:
    path = Path(raw or str(DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY))
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
