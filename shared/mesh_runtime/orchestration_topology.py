from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


ORCHESTRATION_TOPOLOGY_PROFILE_SCHEMA = "orchestration-topology-profile.schema.json"
ORCHESTRATION_TOPOLOGY_PROFILE_VERSION = "mesh.orchestration_topology_profile.v1"
ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION = "mesh.orchestration_topology_resolution.v1"
SOURCE_EVIDENCE_VERSION = "mesh.orchestration_topology_source_evidence.v1"
TOPOLOGY_MODES = frozenset({"centralized", "hierarchical", "decentralized", "federated", "hybrid"})
CERTIFIED_ACTION_STATES = frozenset({"pilot-ready", "production-ready"})
PROPOSAL_STATES = frozenset({"proposal-only", "read-only", "staging-ready", "mock", "disabled", "unfinished"})


def load_orchestration_topology_profile(path: str | Path) -> dict[str, Any]:
    profile_path = Path(path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    validate_payload(ORCHESTRATION_TOPOLOGY_PROFILE_SCHEMA, payload)
    return payload


def orchestration_topology_profile_ready(path: str | Path | None) -> bool:
    if not path:
        return False
    try:
        load_orchestration_topology_profile(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError, ValueError):
        return False
    return True


def build_orchestration_topology_status(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {
            "version": ORCHESTRATION_TOPOLOGY_PROFILE_VERSION,
            "ready": False,
            "path": None,
            "active_topology": None,
            "source_refs": {},
            "blockers": ["orchestration_topology_profile_missing"],
        }
    try:
        profile = load_orchestration_topology_profile(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError, ValueError) as exc:
        return {
            "version": ORCHESTRATION_TOPOLOGY_PROFILE_VERSION,
            "ready": False,
            "path": str(path),
            "active_topology": None,
            "source_refs": {},
            "blockers": [f"orchestration_topology_profile_invalid:{exc}"],
        }
    return {
        "version": ORCHESTRATION_TOPOLOGY_PROFILE_VERSION,
        "ready": True,
        "path": str(path),
        "active_topology": profile["default_topology"],
        "source_refs": dict(profile.get("source_refs") or {}),
        "rule_count": len(profile.get("rules") or []),
        "blockers": [],
    }


def resolve_orchestration_topology(
    *,
    profile_path: str | Path,
    trigger: Any,
    decision: Any,
    candidate_lanes: list[str],
    configured_filter: list[str] | tuple[str, ...] | None = None,
    service_agent: dict[str, Any] | None = None,
    readiness_snapshot: dict[str, Any] | None = None,
    ownership_registry_path: str | Path | None = None,
    connector_certification_registry_path: str | Path | None = None,
    policy_lifecycle_manifest_path: str | Path | None = None,
    threat_model_register_path: str | Path | None = None,
    state_directory: str | Path | None = None,
) -> dict[str, Any]:
    profile = load_orchestration_topology_profile(profile_path)
    source_evidence = _source_evidence(
        trigger=trigger,
        service_agent=service_agent,
        ownership_registry_path=ownership_registry_path,
        connector_certification_registry_path=connector_certification_registry_path,
        policy_lifecycle_manifest_path=policy_lifecycle_manifest_path,
        threat_model_register_path=threat_model_register_path,
        state_directory=state_directory,
        readiness_snapshot=readiness_snapshot,
    )
    context = _resolution_context(trigger, decision, service_agent, source_evidence)
    rule = _matching_rule(profile, context)
    active_topology = str(rule.get("topology") or profile["default_topology"])
    if active_topology not in TOPOLOGY_MODES:
        active_topology = profile["default_topology"]
    selected_lanes = _select_lanes(rule, candidate_lanes, configured_filter)
    lane_records = [
        _lane_record(
            lane=lane,
            topology=active_topology,
            connector_certification=source_evidence.get("connector_certification", {}),
        )
        for lane in selected_lanes
    ]
    blockers = list(rule.get("blockers") or [])
    blockers.extend(_lane_selection_blockers(rule, selected_lanes, configured_filter))
    blockers.extend(_topology_blockers(active_topology, rule, source_evidence, context))
    blockers.extend(blocker for lane in lane_records for blocker in lane["blockers"])
    return {
        "version": ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION,
        "profile_version": profile["version"],
        "active_topology": active_topology,
        "rule_id": str(rule.get("rule_id") or "default"),
        "routing_reason": str(rule.get("reason") or f"default {active_topology} Mesh-native topology"),
        "context": context,
        "configured_filter": list(configured_filter or []),
        "selected_agents": [lane["lane_id"] for lane in lane_records],
        "selected_lanes": lane_records,
        "blockers": sorted(set(blockers)),
        "reconciliation": str(rule.get("reconciliation") or _default_reconciliation(active_topology)),
        "source_evidence": source_evidence,
    }


def _matching_rule(profile: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    for rule in profile.get("rules", []):
        match = rule.get("match") or {}
        if _matches(match, context):
            return rule
    return {
        "rule_id": "default",
        "topology": profile["default_topology"],
        "match": {},
        "lanes": [],
        "reason": "default profile topology",
    }


def _matches(match: dict[str, Any], context: dict[str, Any]) -> bool:
    checks = {
        "services": context.get("service"),
        "action_classes": context.get("action_class"),
        "risk_tiers": context.get("risk_tier"),
        "signal_sources": context.get("signal_source"),
        "tenant_ids": context.get("tenant_id"),
        "trust_levels": context.get("trust_level"),
    }
    for field, value in checks.items():
        options = {str(item) for item in match.get(field) or []}
        if options and str(value) not in options:
            return False
    return True


def _select_lanes(
    rule: dict[str, Any],
    candidate_lanes: list[str],
    configured_filter: list[str] | tuple[str, ...] | None,
) -> list[str]:
    filtered_candidates = list(candidate_lanes)
    if configured_filter:
        configured_set = {str(lane) for lane in configured_filter}
        filtered_candidates = [lane for lane in candidate_lanes if lane in configured_set]
    requested = [str(lane) for lane in rule.get("lanes") or []]
    if requested:
        candidate_set = set(filtered_candidates)
        selected = [lane for lane in requested if lane in candidate_set]
        if configured_filter:
            return selected or filtered_candidates
        return selected or requested
    return filtered_candidates


def _lane_selection_blockers(
    rule: dict[str, Any],
    selected_lanes: list[str],
    configured_filter: list[str] | tuple[str, ...] | None,
) -> list[str]:
    requested = [str(lane) for lane in rule.get("lanes") or []]
    if not requested or not configured_filter:
        return []
    requested_set = set(requested)
    selected_set = set(selected_lanes)
    if requested_set.isdisjoint(selected_set):
        return ["topology_rule_lanes_filtered_by_agent_mesh_agents"]
    filtered = sorted(requested_set - selected_set)
    return [f"topology_lane_filtered:{lane}" for lane in filtered]


def _lane_record(
    *,
    lane: str,
    topology: str,
    connector_certification: dict[str, Any],
) -> dict[str, Any]:
    cert = connector_certification.get(lane, {}) if isinstance(connector_certification, dict) else {}
    certified_state = str(cert.get("state") or "mock")
    credential_boundary = cert.get("credential_boundary") if isinstance(cert, dict) else {}
    role = _lane_role(lane, topology)
    authority = "proposal_only"
    blockers: list[str] = []
    if lane == "kubernetes" and certified_state in CERTIFIED_ACTION_STATES:
        if bool((credential_boundary or {}).get("production_actuator_credentials_allowed")):
            authority = "bounded_action"
        else:
            blockers.append("kubernetes_actuator_credentials_not_certified")
    elif certified_state in PROPOSAL_STATES:
        authority = "proposal_only"
    else:
        blockers.append(f"{lane}_connector_not_certified_for_action")
    return {
        "lane_id": lane,
        "role": role,
        "authority": authority,
        "certified_state": certified_state,
        "authority_posture": cert.get("authority_posture") or cert.get("detail") or "Mesh governs this lane",
        "credential_boundary": credential_boundary or {},
        "blockers": blockers,
    }


def _lane_role(lane: str, topology: str) -> str:
    if topology == "centralized":
        return "mesh_assigned_worker"
    if topology == "hierarchical":
        return "supervisor" if lane in {"hermes", "temporal"} else "worker"
    if topology == "decentralized":
        return "peer_proposal"
    if topology == "federated":
        return "federated_lane"
    if topology == "hybrid":
        return "hybrid_lane"
    return "worker"


def _topology_blockers(
    topology: str,
    rule: dict[str, Any],
    source_evidence: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if topology == "federated":
        ownership = source_evidence.get("ownership_boundary", {})
        if not ownership.get("matched"):
            blockers.append("federated_ownership_boundary_unresolved")
        if rule.get("data_boundary_required", True) and not ownership.get("data_boundary"):
            blockers.append("federated_data_boundary_missing")
        if rule.get("credential_boundary_required", True) and not context.get("tenant_id"):
            blockers.append("federated_tenant_boundary_missing")
    return blockers


def _default_reconciliation(topology: str) -> str:
    if topology == "centralized":
        return "mesh_authoritative_single_decision"
    if topology == "hierarchical":
        return "mesh_reconciles_supervisor_and_worker_outputs"
    if topology == "decentralized":
        return "mesh_reconciles_parallel_peer_proposals"
    if topology == "federated":
        return "mesh_reconciles_with_tenant_data_and_credential_boundaries"
    if topology == "hybrid":
        return "mesh_reconciles_per_rule_topology_outputs"
    return "mesh_reconciles"


def _resolution_context(
    trigger: Any,
    decision: Any,
    service_agent: dict[str, Any] | None,
    source_evidence: dict[str, Any],
) -> dict[str, Any]:
    ownership = source_evidence.get("ownership_boundary", {})
    risk = getattr(decision, "risk", {}) if decision is not None else {}
    execution_plan = getattr(decision, "execution_plan", {}) if decision is not None else {}
    parameters = execution_plan.get("parameters", {}) if isinstance(execution_plan, dict) else {}
    service_agent_payload = (service_agent or {}).get("agent") if isinstance(service_agent, dict) else None
    return {
        "service": getattr(trigger, "service", None),
        "environment": getattr(trigger, "environment", None),
        "signal_source": _signal_source(trigger),
        "action_class": str(execution_plan.get("action") or execution_plan.get("system") or getattr(decision, "decision_type", "")),
        "risk_tier": str((risk or {}).get("level") or "unknown"),
        "tenant_id": parameters.get("tenant_id") or ownership.get("tenant_id"),
        "customer_id": parameters.get("customer_id") or ownership.get("customer_id"),
        "trust_level": _trust_level(source_evidence, getattr(trigger, "service", None), service_agent_payload),
    }


def _signal_source(trigger: Any) -> str:
    related = getattr(trigger, "related_context", {}) if trigger is not None else {}
    if isinstance(related, dict):
        for key in ("signal_source", "source", "integration"):
            if related.get(key):
                return str(related[key])
    trigger_type = str(getattr(trigger, "trigger_type", "") or "")
    if "kubernetes" in trigger_type:
        return "kubernetes"
    if "otel" in trigger_type or "metric" in trigger_type:
        return "otel"
    if "flag" in trigger_type:
        return "feature_flag"
    if "data" in trigger_type:
        return "data"
    if "workflow" in trigger_type:
        return "workflow"
    return "unknown"


def _source_evidence(
    *,
    trigger: Any,
    service_agent: dict[str, Any] | None,
    ownership_registry_path: str | Path | None,
    connector_certification_registry_path: str | Path | None,
    policy_lifecycle_manifest_path: str | Path | None,
    threat_model_register_path: str | Path | None,
    state_directory: str | Path | None,
    readiness_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    ownership_payload = _load_json(ownership_registry_path)
    connector_payload = _load_json(connector_certification_registry_path)
    return {
        "version": SOURCE_EVIDENCE_VERSION,
        "ownership_boundary": _ownership_boundary(ownership_payload, trigger),
        "service_agent": _service_agent_evidence(service_agent),
        "connector_certification": _connector_certifications(connector_payload, readiness_snapshot),
        "policy_lifecycle": _source_ref(policy_lifecycle_manifest_path),
        "threat_model": _source_ref(threat_model_register_path),
        "readiness": readiness_snapshot or {},
        "historical_outcomes": {"source_ref": "state://runs", "status": "referenced"},
        "trust_ladder": _load_trust_ladder(state_directory),
    }


def _ownership_boundary(payload: dict[str, Any], trigger: Any) -> dict[str, Any]:
    records = payload.get("records") if isinstance(payload, dict) else []
    service = getattr(trigger, "service", None)
    environment = getattr(trigger, "environment", None)
    for record in records if isinstance(records, list) else []:
        if record.get("service") == service and (not environment or record.get("environment") in {environment, "production"}):
            return {
                "matched": True,
                "record_id": record.get("record_id"),
                "tenant_id": record.get("tenant_id"),
                "customer_id": record.get("customer_id"),
                "namespace": record.get("namespace"),
                "customer_boundary": record.get("customer_boundary"),
                "owner": record.get("owner"),
                "approver_roles": record.get("approver_roles", []),
                "allowed_action_classes": record.get("allowed_action_classes", []),
                "data_boundary": record.get("data_boundary", {}),
            }
    return {"matched": False, "blockers": ["ownership_record_missing"]}


def _service_agent_evidence(service_agent: dict[str, Any] | None) -> dict[str, Any]:
    payload = service_agent if isinstance(service_agent, dict) else {}
    agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
    return {
        "source_ref": "state://service-agents",
        "matched": bool(payload.get("matched")),
        "service": agent.get("service"),
        "agent_id": agent.get("agent_id") or agent.get("id"),
        "agent_type": agent.get("agent_type") or agent.get("type"),
        "trust_level": agent.get("trust_level"),
        "blockers": [] if payload.get("matched") else ["service_agent_not_matched"],
    }


def _connector_certifications(
    registry_payload: dict[str, Any],
    readiness_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    connectors: dict[str, Any] = {}
    for item in registry_payload.get("connectors", []) if isinstance(registry_payload, dict) else []:
        connector_id = item.get("connector_id")
        if connector_id:
            connectors[str(connector_id)] = dict(item)
    runtime_connectors = (readiness_snapshot or {}).get("connector_certification", {})
    if isinstance(runtime_connectors, dict):
        for connector_id, item in runtime_connectors.items():
            if connector_id not in connectors:
                connectors[connector_id] = item if isinstance(item, dict) else {"state": str(item)}
            elif isinstance(item, dict):
                connectors[connector_id] = {**connectors[connector_id], **item}
    return connectors


def _load_trust_ladder(state_directory: str | Path | None) -> dict[str, Any]:
    if not state_directory:
        return {"source_ref": "state://learning/trust_ladder.json", "available": False}
    path = Path(state_directory) / "learning" / "trust_ladder.json"
    payload = _load_json(path)
    return {
        "source_ref": str(path),
        "available": bool(payload),
        "levels": payload.get("levels", payload) if isinstance(payload, dict) else {},
    }


def _trust_level(
    source_evidence: dict[str, Any],
    service: str | None,
    service_agent_payload: dict[str, Any] | None,
) -> str:
    if isinstance(service_agent_payload, dict) and service_agent_payload.get("trust_level"):
        return str(service_agent_payload["trust_level"])
    levels = source_evidence.get("trust_ladder", {}).get("levels", {})
    if isinstance(levels, dict):
        service_level = levels.get(service or "")
        if isinstance(service_level, str):
            return service_level
        if isinstance(service_level, dict) and service_level.get("level"):
            return str(service_level["level"])
    return "unknown"


def _source_ref(path: str | Path | None) -> dict[str, Any]:
    return {"source_ref": str(path) if path else None, "available": bool(path and Path(path).exists())}


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
