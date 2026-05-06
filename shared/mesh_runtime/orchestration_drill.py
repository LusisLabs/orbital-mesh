from __future__ import annotations

import json
import time
from uuid import uuid4
from pathlib import Path
from typing import Any

from .orchestration_topology import ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION
from .schema_validation import SchemaValidationError, validate_payload


ORCHESTRATION_TOPOLOGY_DRILL_SCHEMA = "orchestration-topology-drill.schema.json"
ORCHESTRATION_TOPOLOGY_DRILL_VERSION = "mesh.orchestration_topology_drill.v1"
ORCHESTRATION_TOPOLOGY_DRILL_VERIFICATION_VERSION = "mesh.orchestration_topology_drill_verification.v1"
_PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"staging", "pilot", "production", "prod", "expansion"})
_REQUIRED_SOURCE_EVIDENCE = frozenset(
    {
        "ownership_boundary",
        "connector_certification",
        "policy_lifecycle",
        "threat_model",
        "readiness",
        "historical_outcomes",
        "trust_ladder",
    }
)


def load_orchestration_topology_drill(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(ORCHESTRATION_TOPOLOGY_DRILL_SCHEMA, payload)
    return payload


def orchestration_topology_drill_ready(path: str | Path | None) -> bool:
    return verify_orchestration_topology_drill(path)["status"] == "pass"


def verify_orchestration_topology_drill(path: str | Path | None) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_orchestration_topology_drill(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": ORCHESTRATION_TOPOLOGY_DRILL_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "drill_id": proof.get("drill_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def build_orchestration_topology_drill_packet(
    *,
    run_export: dict[str, Any],
    operator_id: str,
    environment: str,
    state_backend: str,
    profile_ref: str,
    run_export_ref: str | None = None,
    readiness_ref: str = "artifact://integration_readiness",
    operator_approval_recorded: bool = False,
    bounded_action_execution_ref: str | None = None,
    evidence_refs: list[str] | None = None,
    drill_id: str | None = None,
) -> dict[str, Any]:
    artifacts = _run_export_artifacts(run_export)
    topology_resolution = _topology_resolution_from_artifacts(artifacts)
    if not topology_resolution:
        raise ValueError("run export does not contain lane_routing or agent task topology")
    run_id = _run_export_run_id(run_export)
    if not run_id:
        raise ValueError("run export does not contain run_id")
    refs = _evidence_refs(evidence_refs, artifacts, readiness_ref)
    packet = {
        "schema_version": ORCHESTRATION_TOPOLOGY_DRILL_VERSION,
        "drill_id": drill_id or f"orchestration_topology_drill_{uuid4().hex[:12]}",
        "generated_at": _timestamp(),
        "environment": environment,
        "operator_id": operator_id,
        "state_backend": state_backend,
        "run_id": run_id,
        "run_export_ref": run_export_ref or _default_run_export_ref(run_export, run_id),
        "readiness_ref": readiness_ref,
        "profile_ref": profile_ref,
        "operator_approval_recorded": operator_approval_recorded,
        "bounded_action_execution_ref": bounded_action_execution_ref,
        "topology_resolution": topology_resolution,
        "evidence_refs": refs,
        "raw_secret_material_present": False,
    }
    validate_payload(ORCHESTRATION_TOPOLOGY_DRILL_SCHEMA, packet)
    return packet


def _proof_checks(proof: dict[str, Any] | None) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "drill_id_present": False,
            "operator_present": False,
            "production_like_environment": False,
            "postgres_state_backend": False,
            "run_id_present": False,
            "run_export_ref_present": False,
            "readiness_ref_present": False,
            "profile_ref_present": False,
            "topology_resolution_version": False,
            "multi_lane_topology": False,
            "lane_records_cover_selected_lanes": False,
            "lane_roles_present": False,
            "lane_authority_present": False,
            "proposal_lanes_do_not_execute": False,
            "bounded_action_lanes_certified": False,
            "source_evidence_complete": False,
            "reconciliation_recorded": False,
            "operator_approval_recorded": False,
            "evidence_refs_present": False,
            "no_raw_secret_material": False,
        }
    resolution = proof.get("topology_resolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    selected_lanes = resolution.get("selected_lanes", [])
    lane_records = [lane for lane in selected_lanes if isinstance(lane, dict)]
    selected_agents = {str(agent) for agent in resolution.get("selected_agents", []) if str(agent).strip()}
    lane_ids = {str(lane.get("lane_id")) for lane in lane_records if str(lane.get("lane_id") or "").strip()}
    source_evidence = resolution.get("source_evidence")
    source_evidence = source_evidence if isinstance(source_evidence, dict) else {}
    return {
        "proof_present": True,
        "schema_valid": True,
        "drill_id_present": bool(str(proof.get("drill_id") or "").strip()),
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "production_like_environment": str(proof.get("environment") or "").strip() in _PRODUCTION_LIKE_ENVIRONMENTS,
        "postgres_state_backend": proof.get("state_backend") == "postgres",
        "run_id_present": bool(str(proof.get("run_id") or "").strip()),
        "run_export_ref_present": bool(str(proof.get("run_export_ref") or "").strip()),
        "readiness_ref_present": bool(str(proof.get("readiness_ref") or "").strip()),
        "profile_ref_present": bool(str(proof.get("profile_ref") or "").strip()),
        "topology_resolution_version": resolution.get("version") == ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION,
        "multi_lane_topology": len(lane_records) >= 2,
        "lane_records_cover_selected_lanes": bool(lane_ids) and (not selected_agents or selected_agents.issubset(lane_ids)),
        "lane_roles_present": bool(lane_records) and all(bool(str(lane.get("role") or "").strip()) for lane in lane_records),
        "lane_authority_present": bool(lane_records)
        and all(bool(str(lane.get("authority") or "").strip()) for lane in lane_records),
        "proposal_lanes_do_not_execute": _proposal_lanes_do_not_execute(lane_records),
        "bounded_action_lanes_certified": _bounded_action_lanes_certified(lane_records, proof),
        "source_evidence_complete": _REQUIRED_SOURCE_EVIDENCE.issubset(set(source_evidence)),
        "reconciliation_recorded": bool(str(resolution.get("reconciliation") or "").strip()),
        "operator_approval_recorded": proof.get("operator_approval_recorded") is True,
        "evidence_refs_present": bool(proof.get("evidence_refs"))
        and all(bool(str(ref or "").strip()) for ref in proof.get("evidence_refs", [])),
        "no_raw_secret_material": proof.get("raw_secret_material_present") is False,
    }


def _run_export_artifacts(run_export: dict[str, Any]) -> dict[str, Any]:
    artifacts = run_export.get("artifacts")
    if isinstance(artifacts, dict):
        return artifacts
    session = run_export.get("session")
    if isinstance(session, dict) and isinstance(session.get("artifacts"), dict):
        return session["artifacts"]
    return {}


def _topology_resolution_from_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
    lane_routing = artifacts.get("lane_routing")
    if isinstance(lane_routing, dict) and lane_routing.get("version") == ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION:
        return lane_routing
    tasks = artifacts.get("agent_tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            topology = task.get("orchestration_topology") or task.get("lane_routing")
            if isinstance(topology, dict) and topology.get("version") == ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION:
                return topology
    return {}


def _run_export_run_id(run_export: dict[str, Any]) -> str:
    run_id = run_export.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id
    session = run_export.get("session")
    if isinstance(session, dict) and isinstance(session.get("run_id"), str):
        return session["run_id"]
    return ""


def _default_run_export_ref(run_export: dict[str, Any], run_id: str) -> str:
    export_id = run_export.get("export_id")
    if isinstance(export_id, str) and export_id.strip():
        return f"run-export://{run_id}/{export_id}"
    package_sha = run_export.get("package_sha256")
    if isinstance(package_sha, str) and package_sha.strip():
        return f"run-export://{run_id}/sha256:{package_sha}"
    return f"run-export://{run_id}"


def _evidence_refs(
    supplied: list[str] | None,
    artifacts: dict[str, Any],
    readiness_ref: str,
) -> list[str]:
    refs = [ref for ref in supplied or [] if str(ref or "").strip()]
    if artifacts.get("lane_routing"):
        refs.append("artifact://lane_routing")
    if artifacts.get("agent_tasks"):
        refs.append("artifact://agent_tasks")
    if artifacts.get("integration_readiness"):
        refs.append(readiness_ref)
    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref not in seen:
            deduped.append(ref)
            seen.add(ref)
    return deduped or ["artifact://lane_routing"]


def _proposal_lanes_do_not_execute(lane_records: list[dict[str, Any]]) -> bool:
    for lane in lane_records:
        authority = str(lane.get("authority") or "")
        if authority == "proposal_only" and lane.get("execution_ref"):
            return False
    return True


def _bounded_action_lanes_certified(lane_records: list[dict[str, Any]], proof: dict[str, Any]) -> bool:
    bounded = [lane for lane in lane_records if lane.get("authority") == "bounded_action"]
    if not bounded:
        return True
    if proof.get("operator_approval_recorded") is not True:
        return False
    if not str(proof.get("bounded_action_execution_ref") or "").strip():
        return False
    for lane in bounded:
        if lane.get("lane_id") != "kubernetes":
            return False
        if lane.get("certified_state") not in {"pilot-ready", "production-ready"}:
            return False
    return True


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
