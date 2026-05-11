from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .agent_workers import MODEL_BOUND_AGENT_WORKERS
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
        "org_profile_ready": _org_profile_ready(profile),
        "path": str(path),
        "active_topology": profile["default_topology"],
        "active_topologies": sorted({profile["default_topology"], *(rule.get("topology") for rule in profile.get("rules", []))}),
        "organization_profile": _organization_profile_summary(profile),
        "model_provider_policy": _model_provider_policy_summary(profile),
        "source_refs": dict(profile.get("source_refs") or {}),
        "required_evidence_refs": list((profile.get("organization_profile") or {}).get("required_evidence_refs") or []),
        "rule_count": len(profile.get("rules") or []),
        "blockers": [] if _org_profile_ready(profile) else ["organization_profile_incomplete"],
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
    lane_model_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = load_orchestration_topology_profile(profile_path)
    source_evidence = _source_evidence(
        profile=profile,
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
    reconciliation = str(rule.get("reconciliation") or _default_reconciliation(active_topology))
    lane_records = [
        _lane_record(
            lane=lane,
            topology=active_topology,
            rule=rule,
            profile=profile,
            context=context,
            source_evidence=source_evidence,
            connector_certification=source_evidence.get("connector_certification", {}),
            lane_model_bindings=lane_model_bindings or {},
            resolution_reconciliation=reconciliation,
        )
        for lane in selected_lanes
    ]
    blockers = list(rule.get("blockers") or [])
    blockers.extend(_lane_selection_blockers(rule, selected_lanes, configured_filter))
    blockers.extend(_topology_blockers(active_topology, rule, source_evidence, context))
    blockers.extend(_risk_policy_blockers(rule, lane_records, context))
    blockers.extend(_model_policy_blockers(profile, lane_records))
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
        "reconciliation": reconciliation,
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
        "allowed_model_providers": context.get("allowed_model_providers"),
        "autonomy_tiers": context.get("autonomy_tier"),
        "data_boundaries": context.get("data_boundaries"),
        "deployment_substrates": context.get("deployment_substrate"),
        "environments": context.get("environment"),
        "model_ids": context.get("allowed_model_ids"),
        "namespaces": context.get("namespace"),
        "org_domains": context.get("org_domain"),
        "risk_tiers": context.get("risk_tier"),
        "signal_sources": context.get("signal_source"),
        "teams": context.get("team_ids"),
        "tenant_ids": context.get("tenant_id"),
        "trust_levels": context.get("trust_level"),
    }
    for field, value in checks.items():
        options = {str(item) for item in match.get(field) or []}
        if options and not _value_matches_any(value, options):
            return False
    return True


def _value_matches_any(value: Any, options: set[str]) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(str(item) in options for item in value)
    return str(value) in options


def _select_lanes(
    rule: dict[str, Any],
    candidate_lanes: list[str],
    configured_filter: list[str] | tuple[str, ...] | None,
) -> list[str]:
    filtered_candidates = list(candidate_lanes)
    if configured_filter:
        configured_set = {str(lane) for lane in configured_filter}
        filtered_candidates = [lane for lane in candidate_lanes if lane in configured_set]
    requested = _requested_rule_lanes(rule)
    if requested:
        candidate_set = set(filtered_candidates)
        selected = [lane for lane in requested if lane in candidate_set]
        if configured_filter:
            return selected or filtered_candidates
        return selected or requested
    return filtered_candidates


def _requested_rule_lanes(rule: dict[str, Any]) -> list[str]:
    lanes: list[str] = []
    for field in ("required_agents", "lanes", "preferred_agents", "fallback_agents"):
        for lane in rule.get(field) or []:
            lane_id = str(lane)
            if lane_id not in lanes:
                lanes.append(lane_id)
    return lanes


def _lane_selection_blockers(
    rule: dict[str, Any],
    selected_lanes: list[str],
    configured_filter: list[str] | tuple[str, ...] | None,
) -> list[str]:
    requested = _requested_rule_lanes(rule)
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
    rule: dict[str, Any],
    profile: dict[str, Any],
    context: dict[str, Any],
    source_evidence: dict[str, Any],
    connector_certification: dict[str, Any],
    lane_model_bindings: dict[str, Any],
    resolution_reconciliation: str,
) -> dict[str, Any]:
    cert = connector_certification.get(lane, {}) if isinstance(connector_certification, dict) else {}
    certified_state = str(cert.get("state") or "mock")
    credential_boundary = cert.get("credential_boundary") if isinstance(cert, dict) else {}
    lane_override = _lane_override(rule, lane)
    role = str(lane_override.get("role") or _lane_role(lane, topology))
    topology_role = str(lane_override.get("topology_role") or _topology_role(lane, topology))
    model_binding = _model_binding(
        lane=lane,
        rule=rule,
        profile=profile,
        lane_override=lane_override,
        supplied_bindings=lane_model_bindings,
    )
    reconciliation_mode = str(
        lane_override.get("reconciliation_mode")
        or _lane_reconciliation_mode(topology_role, resolution_reconciliation)
    )
    authority = "proposal_only"
    blockers: list[str] = []
    requested_authority = str(lane_override.get("authority") or "")
    if _bounded_action_allowed(cert, requested_authority):
        authority = "bounded_action"
    elif requested_authority == "bounded_action":
        blockers.append(f"{lane}_bounded_action_not_certified")
    elif lane == "kubernetes" and certified_state in CERTIFIED_ACTION_STATES:
        if bool((credential_boundary or {}).get("production_actuator_credentials_allowed")):
            authority = "bounded_action"
        else:
            blockers.append("kubernetes_actuator_credentials_not_certified")
    elif certified_state in PROPOSAL_STATES:
        authority = "proposal_only"
    else:
        blockers.append(f"{lane}_connector_not_certified_for_action")
    blockers.extend(_lane_boundary_blockers(lane=lane, authority=authority, credential_boundary=credential_boundary))
    return {
        "lane_id": lane,
        "role": role,
        "topology_role": topology_role,
        "adapter": _lane_adapter(lane),
        "runtime_mode": _lane_runtime_mode(lane),
        "generative_capability": _lane_generative_capability(lane, model_binding),
        "model_binding": model_binding,
        "authority": authority,
        "certified_state": certified_state,
        "authority_posture": cert.get("authority_posture") or cert.get("detail") or "Mesh governs this lane",
        "credential_boundary": credential_boundary or {},
        "source_evidence": _lane_source_evidence(
            lane=lane,
            rule=rule,
            context=context,
            source_evidence=source_evidence,
            model_binding=model_binding,
        ),
        "reconciliation_mode": reconciliation_mode,
        "blockers": blockers,
    }


def _lane_override(rule: dict[str, Any], lane: str) -> dict[str, Any]:
    overrides = rule.get("lane_overrides")
    if not isinstance(overrides, dict):
        return {}
    override = overrides.get(lane)
    return override if isinstance(override, dict) else {}


def _bounded_action_allowed(cert: dict[str, Any], requested_authority: str) -> bool:
    if requested_authority != "bounded_action":
        return False
    if str(cert.get("state") or "mock") not in CERTIFIED_ACTION_STATES:
        return False
    boundary = cert.get("credential_boundary") if isinstance(cert.get("credential_boundary"), dict) else {}
    return bool(boundary.get("production_actuator_credentials_allowed"))


def _lane_boundary_blockers(
    *,
    lane: str,
    authority: str,
    credential_boundary: Any,
) -> list[str]:
    boundary = credential_boundary if isinstance(credential_boundary, dict) else {}
    blockers: list[str] = []
    if authority == "proposal_only" and boundary.get("production_actuator_credentials_allowed"):
        blockers.append(f"{lane}_proposal_lane_has_actuator_credential_boundary")
    if authority == "proposal_only" and boundary.get("repo_write_credentials_allowed"):
        blockers.append(f"{lane}_proposal_lane_has_repo_write_credential_boundary")
    return blockers


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


def _topology_role(lane: str, topology: str) -> str:
    if topology == "centralized":
        return "mesh_assigned_worker"
    if topology == "hierarchical":
        return "supervisor_lane" if lane in {"hermes", "temporal"} else "worker_evidence_lane"
    if topology == "decentralized":
        return "peer_proposal_lane"
    if topology == "federated":
        return "federated_tenant_lane"
    if topology == "hybrid":
        if lane in {"temporal"}:
            return "supervisor_lane"
        if lane == "kubernetes":
            return "bounded_actuator_lane"
        if lane in {"flyte", "dagster", "airflow", "prefect", "luigi", "oozie"}:
            return "federated_or_peer_evidence_lane"
        return "peer_proposal_lane"
    return "worker_evidence_lane"


def _lane_reconciliation_mode(topology_role: str, resolution_reconciliation: str) -> str:
    if topology_role == "bounded_actuator_lane":
        return "bounded_action_evidence"
    if topology_role == "supervisor_lane":
        return "supervisor_summary_before_mesh_reconciliation"
    if topology_role == "federated_tenant_lane":
        return "tenant_boundary_evidence_before_mesh_reconciliation"
    if topology_role == "peer_proposal_lane":
        return "parallel_proposal_before_mesh_reconciliation"
    return resolution_reconciliation


def _lane_adapter(lane: str) -> str:
    if lane == "latentmas":
        return "latentmas_http"
    if lane in {"codex", "claudecode", "openclaw", "deepagents"}:
        return "deepagents_or_native_contract"
    if lane in {"goose", "hermes"}:
        return f"{lane}_bridge_or_native_contract"
    if lane in {"airflow", "temporal", "dagster", "prefect", "flyte", "luigi", "oozie", "kubernetes", "n8n"}:
        return "native_orchestration_contract"
    return "native_contract"


def _lane_runtime_mode(lane: str) -> str:
    if lane == "latentmas":
        return "sidecar_inference"
    if lane in {"codex", "claudecode", "openclaw", "deepagents"}:
        return "sandboxed_proposal_fabric"
    if lane in {"goose", "hermes"}:
        return "cli_or_native_proposal"
    if lane == "kubernetes":
        return "bounded_actuator_when_certified"
    return "evidence_adapter"


def _lane_generative_capability(lane: str, model_binding: dict[str, Any]) -> str:
    if lane in MODEL_BOUND_AGENT_WORKERS or model_binding.get("supported") is True:
        return "model_bound"
    return "not_model_backed"


def _model_binding(
    *,
    lane: str,
    rule: dict[str, Any],
    profile: dict[str, Any],
    lane_override: dict[str, Any],
    supplied_bindings: dict[str, Any],
) -> dict[str, Any]:
    candidates = [
        supplied_bindings.get(lane) if isinstance(supplied_bindings, dict) else None,
        _nested_lane_binding(rule.get("model_bindings"), lane),
        lane_override.get("model_binding"),
        _nested_lane_binding((profile.get("model_provider_policy") or {}).get("lane_defaults"), lane),
        _env_model_binding(lane),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return _sanitize_model_binding(lane, candidate)
    if lane in {"codex", "claudecode", "openclaw"}:
        deepagents_binding = _nested_lane_binding(supplied_bindings, "deepagents")
        if not deepagents_binding:
            deepagents_binding = _nested_lane_binding((profile.get("model_provider_policy") or {}).get("lane_defaults"), "deepagents")
        if deepagents_binding:
            inherited = dict(deepagents_binding)
            inherited["config_source"] = inherited.get("config_source") or "inherited:deepagents"
            return _sanitize_model_binding(lane, inherited)
    if lane in MODEL_BOUND_AGENT_WORKERS:
        return {
            "supported": True,
            "binding_status": "unconfigured",
            "provider": "unknown",
            "model": "unknown",
            "route": _lane_adapter(lane),
            "config_source": "unresolved",
            "secret_ref_envs": [],
            "credential_configured": False,
            "secret_material_present": False,
        }
    return {
        "supported": False,
        "binding_status": "not_supported",
        "provider": "none",
        "model": "none",
        "route": _lane_adapter(lane),
        "config_source": "not_model_backed",
        "secret_ref_envs": [],
        "credential_configured": False,
        "secret_material_present": False,
    }


def _nested_lane_binding(value: Any, lane: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    candidate = value.get(lane)
    return candidate if isinstance(candidate, dict) else {}


def _env_model_binding(lane: str) -> dict[str, Any]:
    if lane == "hermes":
        provider = os.getenv("HERMES_INFERENCE_PROVIDER") or ("openai-compatible" if _openai_base_url_configured() else "")
        model = os.getenv("HERMES_MODEL") or os.getenv("LLM_MODEL") or os.getenv("MINIMAX_MODEL") or ""
        if provider or model:
            return {
                "provider": provider or "auto",
                "model": model or "auto",
                "route": "hermes_bridge",
                "config_source": "environment:HERMES_*",
                "secret_ref_envs": _openai_secret_refs(),
                "credential_configured": _openai_secret_configured(),
            }
    if lane == "goose":
        provider = os.getenv("GOOSE_PROVIDER") or ("openai-compatible" if _openai_base_url_configured() else "")
        model = os.getenv("GOOSE_MODEL") or os.getenv("HERMES_MODEL") or os.getenv("LLM_MODEL") or os.getenv("MINIMAX_MODEL") or ""
        if provider or model:
            return {
                "provider": provider or "auto",
                "model": model or "auto",
                "route": "goose_bridge",
                "config_source": "environment:GOOSE_*",
                "fallback_provider": os.getenv("GOOSE_FALLBACK_PROVIDER") or "",
                "fallback_model": os.getenv("GOOSE_FALLBACK_MODEL") or "",
                "secret_ref_envs": _openai_secret_refs(),
                "credential_configured": _openai_secret_configured(),
            }
    return {}


def _sanitize_model_binding(lane: str, binding: dict[str, Any]) -> dict[str, Any]:
    secret_ref_envs = [str(item) for item in binding.get("secret_ref_envs") or []]
    provider = str(binding.get("provider") or _provider_from_model(str(binding.get("model") or "")) or "unknown")
    model = str(binding.get("model") or "unknown")
    sanitized: dict[str, Any] = {
        "supported": bool(binding.get("supported", True)),
        "binding_status": str(binding.get("binding_status") or "resolved"),
        "provider": provider,
        "model": model,
        "route": str(binding.get("route") or _lane_adapter(lane)),
        "config_source": str(binding.get("config_source") or "profile"),
        "secret_ref_envs": secret_ref_envs,
        "credential_configured": bool(binding.get("credential_configured", _secret_refs_configured(secret_ref_envs))),
        "secret_material_present": False,
    }
    for key in ("device", "prompt_mode", "max_new_tokens", "fallback_provider", "fallback_model"):
        if binding.get(key) is not None:
            sanitized[key] = binding[key]
    return sanitized


def _provider_from_model(model: str) -> str:
    if ":" in model:
        return model.split(":", 1)[0]
    if "/" in model:
        return "huggingface"
    return ""


def _openai_base_url_configured() -> bool:
    return bool((os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_HOST") or "").strip())


def _openai_secret_refs() -> list[str]:
    return ["OPENAI_API_KEY", "MINIMAX_API_KEY"]


def _openai_secret_configured() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY") or "").strip())


def _secret_refs_configured(secret_ref_envs: list[str]) -> bool:
    return any(bool((os.getenv(name) or "").strip()) for name in secret_ref_envs)


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


def _risk_policy_blockers(
    rule: dict[str, Any],
    lane_records: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[str]:
    policy = rule.get("risk_policy") if isinstance(rule.get("risk_policy"), dict) else {}
    if not policy:
        return []
    blockers: list[str] = []
    if policy.get("operator_approval_required") is True and context.get("risk_tier") in {"medium", "high", "critical"}:
        blockers.append("operator_approval_required_for_topology_risk_policy")
    maximum = str(policy.get("maximum_lane_authority") or "")
    if maximum == "proposal_only":
        for lane in lane_records:
            if lane.get("authority") == "bounded_action":
                blockers.append(f"{lane.get('lane_id')}_authority_exceeds_rule_risk_policy")
    return blockers


def _model_policy_blockers(
    profile: dict[str, Any],
    lane_records: list[dict[str, Any]],
) -> list[str]:
    policy = profile.get("model_provider_policy") if isinstance(profile.get("model_provider_policy"), dict) else {}
    allowed_providers = {str(item) for item in policy.get("allowed_providers") or []}
    allowed_models = {
        (str(item.get("provider") or ""), str(item.get("model") or ""))
        for item in policy.get("allowed_models") or []
        if isinstance(item, dict)
    }
    blockers: list[str] = []
    for lane in lane_records:
        binding = lane.get("model_binding") if isinstance(lane.get("model_binding"), dict) else {}
        if binding.get("supported") is not True:
            continue
        provider = str(binding.get("provider") or "")
        model = str(binding.get("model") or "")
        if provider and provider != "unknown" and allowed_providers and provider not in allowed_providers:
            blockers.append(f"{lane.get('lane_id')}_model_provider_not_allowed")
        if model and model != "unknown" and allowed_models and (provider, model) not in allowed_models:
            inherited_openai_compatible = provider == "openai" and ("openai-compatible", model) in allowed_models
            if not inherited_openai_compatible:
                blockers.append(f"{lane.get('lane_id')}_model_not_allowed")
    return blockers


def _lane_source_evidence(
    *,
    lane: str,
    rule: dict[str, Any],
    context: dict[str, Any],
    source_evidence: dict[str, Any],
    model_binding: dict[str, Any],
) -> dict[str, Any]:
    ownership = source_evidence.get("ownership_boundary", {})
    return {
        "profile_rule_ref": f"config/orchestration-topology.profile.json#rules.{rule.get('rule_id', 'default')}",
        "connector_certification_ref": f"config/connector-certification.registry.json#{lane}",
        "readiness_ref": f"/api/readiness#connector_certification.{lane}",
        "ownership_record_id": ownership.get("record_id") if isinstance(ownership, dict) else None,
        "tenant_id": context.get("tenant_id"),
        "trust_level": context.get("trust_level"),
        "model_binding_source": model_binding.get("config_source"),
    }


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
    organization = source_evidence.get("organization_profile", {})
    risk = getattr(decision, "risk", {}) if decision is not None else {}
    execution_plan = getattr(decision, "execution_plan", {}) if decision is not None else {}
    parameters = execution_plan.get("parameters", {}) if isinstance(execution_plan, dict) else {}
    related = getattr(trigger, "related_context", {}) if trigger is not None else {}
    related = related if isinstance(related, dict) else {}
    service_agent_payload = (service_agent or {}).get("agent") if isinstance(service_agent, dict) else None
    namespace = parameters.get("namespace") or related.get("namespace") or ownership.get("namespace")
    data_boundary = ownership.get("data_boundary") if isinstance(ownership.get("data_boundary"), dict) else {}
    owner = ownership.get("owner") if isinstance(ownership.get("owner"), dict) else {}
    team_ids = _dedupe_strings(
        [
            parameters.get("team_id"),
            related.get("team_id"),
            owner.get("owner_id"),
            *_as_list((service_agent_payload or {}).get("team_ids") if isinstance(service_agent_payload, dict) else []),
        ]
    )
    allowed_model_providers = list(organization.get("allowed_model_providers") or [])
    allowed_model_ids = [
        str(item.get("model"))
        for item in organization.get("allowed_models", [])
        if isinstance(item, dict) and item.get("model")
    ]
    return {
        "org_domain": parameters.get("org_domain") or related.get("org_domain") or organization.get("domain"),
        "service": getattr(trigger, "service", None),
        "environment": getattr(trigger, "environment", None),
        "signal_source": _signal_source(trigger),
        "deployment_substrate": parameters.get("deployment_substrate") or related.get("deployment_substrate") or _deployment_substrate(trigger),
        "namespace": namespace,
        "action_class": str(execution_plan.get("action") or execution_plan.get("system") or getattr(decision, "decision_type", "")),
        "autonomy_tier": str(getattr(decision, "autonomy_tier", "") or organization.get("autonomy_tier") or ""),
        "risk_tier": str((risk or {}).get("level") or "unknown"),
        "tenant_id": parameters.get("tenant_id") or ownership.get("tenant_id"),
        "customer_id": parameters.get("customer_id") or ownership.get("customer_id"),
        "team_ids": team_ids,
        "data_boundaries": _dedupe_strings(
            [
                data_boundary.get("classification"),
                related.get("data_boundary"),
                *_as_list(data_boundary.get("reservoir_refs")),
            ]
        ),
        "allowed_model_providers": allowed_model_providers,
        "allowed_model_ids": allowed_model_ids,
        "trust_level": _trust_level(source_evidence, getattr(trigger, "service", None), service_agent_payload),
    }


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        item = str(value)
        if item and item not in result:
            result.append(item)
    return result


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _deployment_substrate(trigger: Any) -> str:
    source = _signal_source(trigger)
    if source in {"kubernetes", "workflow", "data", "ml"}:
        return source
    if source in {"otel", "feature_flag", "argocd", "log"}:
        return "kubernetes"
    return "unknown"


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
    profile: dict[str, Any],
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
        "organization_profile": _organization_profile_evidence(profile),
        "ownership_boundary": _ownership_boundary(ownership_payload, trigger),
        "service_agent": _service_agent_evidence(service_agent),
        "connector_certification": _connector_certifications(connector_payload, readiness_snapshot),
        "policy_lifecycle": _source_ref(policy_lifecycle_manifest_path),
        "threat_model": _source_ref(threat_model_register_path),
        "readiness": readiness_snapshot or {},
        "historical_outcomes": _historical_outcomes(state_directory, trigger),
        "trust_ladder": _load_trust_ladder(state_directory),
    }


def _org_profile_ready(profile: dict[str, Any]) -> bool:
    org = profile.get("organization_profile") if isinstance(profile.get("organization_profile"), dict) else {}
    required = {
        "domain",
        "teams",
        "tenants",
        "ownership_boundaries",
        "deployment_substrates",
        "data_boundaries",
        "preferred_agents",
        "allowed_model_providers",
        "allowed_models",
        "autonomy_tier",
        "risk_thresholds",
        "required_evidence_refs",
    }
    return bool(org) and all(field in org and org[field] not in (None, "", []) for field in required)


def _organization_profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    org = profile.get("organization_profile") if isinstance(profile.get("organization_profile"), dict) else {}
    return {
        "domain": org.get("domain"),
        "autonomy_tier": org.get("autonomy_tier"),
        "team_count": len(org.get("teams") or []),
        "tenant_count": len(org.get("tenants") or []),
        "deployment_substrates": [
            str(item.get("substrate"))
            for item in org.get("deployment_substrates", [])
            if isinstance(item, dict) and item.get("substrate")
        ],
        "data_boundaries": [
            str(item.get("boundary_id") or item.get("classification"))
            for item in org.get("data_boundaries", [])
            if isinstance(item, dict)
        ],
        "preferred_agents": list(org.get("preferred_agents") or []),
        "allowed_model_providers": list(org.get("allowed_model_providers") or []),
        "allowed_model_count": len(org.get("allowed_models") or []),
    }


def _model_provider_policy_summary(profile: dict[str, Any]) -> dict[str, Any]:
    policy = profile.get("model_provider_policy") if isinstance(profile.get("model_provider_policy"), dict) else {}
    return {
        "allowed_providers": list(policy.get("allowed_providers") or []),
        "allowed_models": [
            {"provider": item.get("provider"), "model": item.get("model")}
            for item in policy.get("allowed_models", [])
            if isinstance(item, dict)
        ],
        "lane_defaults": {
            lane: {
                "provider": value.get("provider"),
                "model": value.get("model"),
                "route": value.get("route"),
                "secret_ref_envs": list(value.get("secret_ref_envs") or []),
            }
            for lane, value in (policy.get("lane_defaults") or {}).items()
            if isinstance(value, dict)
        },
    }


def _organization_profile_evidence(profile: dict[str, Any]) -> dict[str, Any]:
    summary = _organization_profile_summary(profile)
    return {
        "source_ref": "config/orchestration-topology.profile.json#organization_profile",
        "matched": _org_profile_ready(profile),
        **summary,
        "blockers": [] if _org_profile_ready(profile) else ["organization_profile_incomplete"],
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


def _historical_outcomes(state_directory: str | Path | None, trigger: Any) -> dict[str, Any]:
    source_ref = "state://runs"
    if not state_directory:
        return {"source_ref": source_ref, "available": False, "total_runs": 0, "status": "unavailable"}
    path = Path(state_directory) / "run_sessions.json"
    payload = _load_json(path)
    records = payload.get("runs") if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return {"source_ref": str(path), "available": False, "total_runs": 0, "status": "unavailable"}
    service = getattr(trigger, "service", None)
    matched: list[dict[str, Any]] = []
    for record in records[:100]:
        if not isinstance(record, dict):
            continue
        artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), dict) else {}
        trigger_record = artifacts.get("trigger") if isinstance(artifacts.get("trigger"), dict) else {}
        record_service = artifacts.get("service") or trigger_record.get("service")
        if service and record_service and record_service != service:
            continue
        matched.append(record)
    completed = sum(1 for record in matched if record.get("status") == "completed")
    failed = sum(1 for record in matched if record.get("status") == "failed")
    return {
        "source_ref": str(path),
        "available": bool(matched),
        "status": "loaded" if matched else "empty",
        "service": service,
        "total_runs": len(matched),
        "completed_runs": completed,
        "failed_runs": failed,
    }


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
