from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY = REPO_ROOT / "config" / "recursive-chaos.arena-profiles.json"

RECURSIVE_CHAOS_ARENA_PROFILES_SCHEMA = "recursive-chaos-arena-profiles.schema.json"
RECURSIVE_CHAOS_EXPERIMENT_MANIFEST_SCHEMA = "recursive-chaos-experiment-manifest.schema.json"
RECURSIVE_CHAOS_CYCLE_PACKET_SCHEMA = "recursive-chaos-cycle-packet.schema.json"
RECURSIVE_CHAOS_GHOST_RECOVERY_PACKET_SCHEMA = "recursive-chaos-ghost-recovery-packet.schema.json"
RECURSIVE_CHAOS_LEARNING_PACKET_SCHEMA = "recursive-chaos-learning-packet.schema.json"
RECURSIVE_CHAOS_EVIDENCE_BUNDLE_SCHEMA = "recursive-chaos-evidence-bundle.schema.json"

RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY_VERSION = "mesh.recursive_chaos.arena_profiles.v1"
RECURSIVE_CHAOS_ARENA_PROFILE_VERIFICATION_VERSION = "mesh.recursive_chaos.arena_profile_verification.v1"

SAFETY_CLASSES = frozenset(
    {
        "local_disposable",
        "staging_owned",
        "production_probe_only",
        "production_mutating_blocked",
    }
)
PRODUCTION_MUTATION_BLOCKING_SAFETY_CLASSES = frozenset({"production_probe_only", "production_mutating_blocked"})
REQUIRED_ARENA_PROFILE_IDS = frozenset(
    {
        "kubernetes_service_platform",
        "hardened_image_supply_chain",
        "ai_model_serving_inference",
        "ai_agent_tool_execution",
        "durable_data_plane",
        "vector_rag_retrieval",
        "observability_signal_trust",
        "crypto_rpc_node_mesh",
        "cross_chain_verifier_signer",
        "queue_event_workflow_plane",
        "identity_authority_secrets",
        "network_gateway_service_mesh",
        "cicd_gitops_release",
        "multi_region_provider_plane",
        "capacity_scheduler_finops",
        "evidence_audit_forensics",
    }
)
P0_ARENA_PROFILE_IDS = frozenset(
    {
        "kubernetes_service_platform",
        "hardened_image_supply_chain",
        "ai_model_serving_inference",
        "durable_data_plane",
        "observability_signal_trust",
        "crypto_rpc_node_mesh",
        "queue_event_workflow_plane",
        "evidence_audit_forensics",
    }
)


def load_recursive_chaos_arena_profiles(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = _resolve_path(path or DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_payload(RECURSIVE_CHAOS_ARENA_PROFILES_SCHEMA, payload)
    return payload


def recursive_chaos_arena_profiles_ready(path: str | Path | None = None) -> bool:
    return verify_recursive_chaos_arena_profiles(path)["status"] == "pass"


def verify_recursive_chaos_arena_profiles(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = _resolve_path(path or DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY)
    blockers: list[str] = []
    profiles: list[dict[str, Any]] = []
    registry_sha256: str | None = None
    try:
        registry = load_recursive_chaos_arena_profiles(registry_path)
        profiles = [profile for profile in registry.get("profiles", []) if isinstance(profile, dict)]
        registry_sha256 = _sha256(registry_path)
        blockers.extend(_registry_blockers(profiles))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        blockers.append(f"recursive_chaos_arena_profile_registry_invalid:{type(exc).__name__}")
        if not registry_path.exists():
            blockers.append("recursive_chaos_arena_profile_registry_missing")

    return {
        "schema_version": RECURSIVE_CHAOS_ARENA_PROFILE_VERIFICATION_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": _timestamp(),
        "registry_path": _display_path(registry_path),
        "registry_sha256": registry_sha256,
        "profile_count": len(profiles),
        "profile_ids": sorted(str(profile.get("profile_id")) for profile in profiles),
        "p0_profile_ids": sorted(
            str(profile.get("profile_id"))
            for profile in profiles
            if str(profile.get("priority_phase")) == "p0"
        ),
        "blockers": sorted(set(blockers)),
    }


def get_recursive_chaos_arena_profile(profile_id: str, path: str | Path | None = None) -> dict[str, Any]:
    registry = load_recursive_chaos_arena_profiles(path)
    for profile in registry.get("profiles", []):
        if isinstance(profile, dict) and profile.get("profile_id") == profile_id:
            return profile
    raise KeyError(f"unknown recursive chaos arena profile: {profile_id}")


def validate_recursive_chaos_experiment_manifest(payload: dict[str, Any]) -> None:
    validate_payload(RECURSIVE_CHAOS_EXPERIMENT_MANIFEST_SCHEMA, payload)
    _raise_if_blocked(_manifest_blockers(payload))


def validate_recursive_chaos_cycle_packet(payload: dict[str, Any]) -> None:
    validate_payload(RECURSIVE_CHAOS_CYCLE_PACKET_SCHEMA, payload)
    _raise_if_blocked(_cycle_packet_blockers(payload))


def validate_ghost_state_recovery_packet(payload: dict[str, Any]) -> None:
    validate_payload(RECURSIVE_CHAOS_GHOST_RECOVERY_PACKET_SCHEMA, payload)
    _raise_if_blocked(_ghost_recovery_blockers(payload))


def validate_chaos_learning_packet(payload: dict[str, Any]) -> None:
    validate_payload(RECURSIVE_CHAOS_LEARNING_PACKET_SCHEMA, payload)
    _raise_if_blocked(_learning_packet_blockers(payload))


def validate_arena_evidence_bundle(payload: dict[str, Any]) -> None:
    validate_payload(RECURSIVE_CHAOS_EVIDENCE_BUNDLE_SCHEMA, payload)
    _raise_if_blocked(_evidence_bundle_blockers(payload))


def safety_class_allows_mutation(safety_class: str) -> bool:
    if safety_class not in SAFETY_CLASSES:
        raise ValueError(f"unknown recursive chaos safety class: {safety_class}")
    return safety_class not in PRODUCTION_MUTATION_BLOCKING_SAFETY_CLASSES


def recursive_chaos_safety_verdict(
    *,
    safety_class: str,
    mutates_target: bool,
    forbidden_actions: list[str] | None = None,
) -> dict[str, Any]:
    allowed = safety_class_allows_mutation(safety_class) or not mutates_target
    enforced_forbidden_actions = sorted(set(forbidden_actions or []))
    reason = "mutation_allowed"
    if not allowed:
        reason = f"{safety_class}_blocks_mutation"
    return {
        "safety_class": safety_class,
        "mutation_allowed": allowed,
        "forbidden_actions_enforced": True,
        "forbidden_actions": enforced_forbidden_actions,
        "reason": reason,
    }


def resolve_recursive_chaos_safety_class(profile: dict[str, Any], environment: str) -> str:
    normalized_environment = environment.strip().lower()
    if "hetzner" in normalized_environment or normalized_environment in {"production", "prod", "pilot"}:
        return "production_probe_only"
    safety_class = str(profile.get("default_safety_class") or "")
    if safety_class not in SAFETY_CLASSES:
        raise ValueError(f"unknown recursive chaos safety class: {safety_class}")
    return safety_class


def build_recursive_chaos_experiment_manifest(
    *,
    manifest_id: str,
    profile: dict[str, Any],
    created_at: str,
    runner: str,
    environment: str,
    target_refs: list[str],
    experiments: list[dict[str, Any]],
) -> dict[str, Any]:
    safety_class = resolve_recursive_chaos_safety_class(profile, environment)
    forbidden_actions = ["production_mutation", "raw_secret_capture"]
    mutating_experiment = any(bool(experiment.get("mutates_target")) for experiment in experiments)
    manifest = {
        "schema_version": "mesh.recursive_chaos.experiment_manifest.v1",
        "manifest_id": manifest_id,
        "profile_id": str(profile["profile_id"]),
        "created_at": created_at,
        "runner": runner,
        "safety_class": safety_class,
        "experiments": experiments,
        "safety_gates": {
            "allow_mutation": safety_class_allows_mutation(safety_class) and mutating_experiment,
            "requires_probe_only": safety_class == "production_probe_only",
            "forbidden_actions": forbidden_actions,
        },
        "mesh_integration": {
            "creates_run": True,
            "records_decision": True,
            "operator_approval_respected": True,
            "seals_packets_before_learning": True,
        },
        "target_refs": target_refs,
        "environment": environment,
    }
    validate_recursive_chaos_experiment_manifest(manifest)
    return manifest


def build_ghost_recovery_packet(
    *,
    recovery_packet_id: str,
    cycle_id: str,
    run_id: str,
    decision_id: str | None,
    pre_state: dict[str, Any],
    fault_state: dict[str, Any],
    recovery_action: dict[str, Any],
    post_state: dict[str, Any],
    residual_drift: dict[str, Any],
    recovered: bool,
    evidence_refs: list[str],
    sealed_at: str,
) -> dict[str, Any]:
    packet = {
        "schema_version": "mesh.recursive_chaos.ghost_recovery_packet.v1",
        "recovery_packet_id": recovery_packet_id,
        "cycle_id": cycle_id,
        "run_id": run_id,
        "decision_id": decision_id,
        "pre_state": pre_state,
        "fault_state": fault_state,
        "recovery_action": recovery_action,
        "post_state": post_state,
        "residual_drift": residual_drift,
        "recovered": recovered,
        "evidence_refs": evidence_refs,
        "sealed_at": sealed_at,
    }
    validate_ghost_state_recovery_packet(packet)
    return packet


def build_chaos_learning_packet(
    *,
    learning_packet_id: str,
    cycle_id: str,
    run_id: str,
    source_packet_refs: list[str],
    recommendations: list[dict[str, Any]],
    sealed_at: str,
    mesh_brain_mode: str = "recommend_only",
    mesh_model_mode: str = "recommend_only",
    training_allowed: bool = False,
    mesh_model_training_allowed: bool = False,
) -> dict[str, Any]:
    packet = {
        "schema_version": "mesh.recursive_chaos.learning_packet.v1",
        "learning_packet_id": learning_packet_id,
        "cycle_id": cycle_id,
        "run_id": run_id,
        "source_packet_refs": source_packet_refs,
        "sealed_source_required": True,
        "mesh_brain_mode": mesh_brain_mode,
        "mesh_model_mode": mesh_model_mode,
        "recommendations": recommendations,
        "training_allowed": training_allowed,
        "mesh_model_training_allowed": mesh_model_training_allowed,
        "advisory_only": True,
        "sealed_at": sealed_at,
    }
    validate_chaos_learning_packet(packet)
    return packet


def build_recursive_chaos_cycle_packet(
    *,
    cycle_id: str,
    manifest_id: str,
    profile_id: str,
    run_id: str,
    decision_id: str | None,
    started_at: str,
    completed_at: str,
    recursion_depth: int,
    selected_experiment: dict[str, Any],
    target: dict[str, Any],
    pre_state_ref: str,
    fault_state_ref: str,
    mesh_observation: dict[str, Any],
    safety_verdict: dict[str, Any],
    recovery_packet_id: str | None,
    learning_packet_id: str | None,
    evidence_refs: list[str],
) -> dict[str, Any]:
    packet = {
        "schema_version": "mesh.recursive_chaos.cycle_packet.v1",
        "cycle_id": cycle_id,
        "manifest_id": manifest_id,
        "profile_id": profile_id,
        "run_id": run_id,
        "decision_id": decision_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "recursion_depth": recursion_depth,
        "selected_experiment": selected_experiment,
        "target": target,
        "pre_state_ref": pre_state_ref,
        "fault_state_ref": fault_state_ref,
        "mesh_observation": mesh_observation,
        "safety_verdict": {
            "safety_class": safety_verdict["safety_class"],
            "mutation_allowed": safety_verdict["mutation_allowed"],
            "forbidden_actions_enforced": safety_verdict["forbidden_actions_enforced"],
        },
        "recovery_packet_id": recovery_packet_id,
        "learning_packet_id": learning_packet_id,
        "evidence_refs": evidence_refs,
        "sealed": True,
    }
    validate_recursive_chaos_cycle_packet(packet)
    return packet


def build_arena_evidence_bundle(
    *,
    bundle_id: str,
    generated_at: str,
    profile_id: str,
    manifest_id: str,
    environment: str,
    safety_class: str,
    cycle_packet_refs: list[str],
    ghost_recovery_packet_refs: list[str],
    learning_packet_refs: list[str],
    run_refs: list[str],
    decision_refs: list[str],
    artifact_refs: list[str],
    gate_results: list[dict[str, Any]],
) -> dict[str, Any]:
    bundle = {
        "schema_version": "mesh.recursive_chaos.evidence_bundle.v1",
        "bundle_id": bundle_id,
        "generated_at": generated_at,
        "profile_id": profile_id,
        "manifest_id": manifest_id,
        "environment": environment,
        "safety_class": safety_class,
        "cycle_packet_refs": cycle_packet_refs,
        "ghost_recovery_packet_refs": ghost_recovery_packet_refs,
        "learning_packet_refs": learning_packet_refs,
        "run_refs": run_refs,
        "decision_refs": decision_refs,
        "artifact_refs": artifact_refs,
        "gate_results": gate_results,
        "production_readiness_claim": False,
        "sealed": True,
    }
    validate_arena_evidence_bundle(bundle)
    return bundle


def _registry_blockers(profiles: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    profile_ids = [str(profile.get("profile_id") or "") for profile in profiles]
    duplicate_ids = sorted({profile_id for profile_id in profile_ids if profile_ids.count(profile_id) > 1})
    blockers.extend(f"duplicate_profile:{profile_id}" for profile_id in duplicate_ids)

    observed_ids = set(profile_ids)
    blockers.extend(f"required_profile_missing:{profile_id}" for profile_id in sorted(REQUIRED_ARENA_PROFILE_IDS - observed_ids))
    blockers.extend(f"unexpected_profile:{profile_id}" for profile_id in sorted(observed_ids - REQUIRED_ARENA_PROFILE_IDS))
    if len(profiles) != len(REQUIRED_ARENA_PROFILE_IDS):
        blockers.append("profile_count_not_exactly_sixteen")

    observed_p0 = {str(profile.get("profile_id")) for profile in profiles if profile.get("priority_phase") == "p0"}
    blockers.extend(f"p0_profile_missing:{profile_id}" for profile_id in sorted(P0_ARENA_PROFILE_IDS - observed_p0))
    for profile in profiles:
        blockers.extend(_profile_blockers(profile))
    return blockers


def _profile_blockers(profile: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    profile_id = str(profile.get("profile_id") or "unknown_profile")
    if profile.get("production_mutation_allowed") is not False:
        blockers.append(f"{profile_id}:production_mutation_not_blocked")
    if str(profile.get("default_safety_class")) not in SAFETY_CLASSES:
        blockers.append(f"{profile_id}:default_safety_class_unknown")
    if profile.get("arena_domain") != profile_id:
        blockers.append(f"{profile_id}:arena_domain_must_match_profile_id")
    if profile.get("production_mutation_allowed") is False:
        resolved = resolve_recursive_chaos_safety_class(profile, "hetzner")
        if resolved != "production_probe_only":
            blockers.append(f"{profile_id}:hetzner_not_probe_only")
    for field_name in (
        "buyer_classes",
        "target_substrates",
        "existing_mesh_surfaces",
        "target_examples",
        "chaos_families",
        "steady_state_checks",
        "proof_gates",
        "ghost_state_bindings",
        "learning_outputs",
        "evidence_requirements",
    ):
        if not profile.get(field_name):
            blockers.append(f"{profile_id}:{field_name}_missing")
    return blockers


def _manifest_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    safety_class = str(payload.get("safety_class") or "")
    experiments = payload.get("experiments") if isinstance(payload.get("experiments"), list) else []
    gates = payload.get("safety_gates") if isinstance(payload.get("safety_gates"), dict) else {}
    if not safety_class_allows_mutation(safety_class) and gates.get("allow_mutation") is not False:
        blockers.append("blocked_safety_class_must_disable_mutation")
    if safety_class == "production_probe_only" and gates.get("requires_probe_only") is not True:
        blockers.append("production_probe_only_requires_probe_gate")
    if safety_class_allows_mutation(safety_class) and any(
        isinstance(experiment, dict) and experiment.get("mutates_target") is True
        for experiment in experiments
    ):
        if gates.get("allow_mutation") is not True:
            blockers.append("mutating_safety_class_must_enable_mutation")
    mesh_integration = payload.get("mesh_integration") if isinstance(payload.get("mesh_integration"), dict) else {}
    for field_name in ("creates_run", "records_decision", "seals_packets_before_learning"):
        if mesh_integration.get(field_name) is not True:
            blockers.append(f"mesh_integration_{field_name}_required")
    return blockers


def _cycle_packet_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    safety_verdict = payload.get("safety_verdict") if isinstance(payload.get("safety_verdict"), dict) else {}
    safety_class = str(safety_verdict.get("safety_class") or "")
    if safety_class and not safety_class_allows_mutation(safety_class):
        if safety_verdict.get("mutation_allowed") is not False:
            blockers.append("cycle_blocked_safety_class_allowed_mutation")
    if payload.get("sealed") is not True:
        blockers.append("cycle_packet_not_sealed")
    if safety_verdict.get("mutation_allowed") is True and not payload.get("recovery_packet_id"):
        blockers.append("recovery_packet_id_missing")
    return blockers


def _ghost_recovery_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not payload.get("pre_state") or not payload.get("fault_state") or not payload.get("post_state"):
        blockers.append("state_hash_chain_incomplete")
    recovery_action = payload.get("recovery_action") if isinstance(payload.get("recovery_action"), dict) else {}
    if recovery_action.get("result") not in {"post_state_restored", "manual_review_required", "blocked"}:
        blockers.append("recovery_action_result_unknown")
    residual_drift = payload.get("residual_drift") if isinstance(payload.get("residual_drift"), dict) else {}
    if payload.get("recovered") is True and residual_drift.get("status") == "unbounded":
        blockers.append("recovered_packet_has_unbounded_drift")
    return blockers


def _learning_packet_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if payload.get("sealed_source_required") is not True:
        blockers.append("sealed_source_required")
    if payload.get("advisory_only") is not True:
        blockers.append("chaos_learning_must_remain_advisory")
    if payload.get("training_allowed") is True and payload.get("mesh_brain_mode") != "training_candidate":
        blockers.append("training_allowed_requires_training_candidate_mode")
    if (
        payload.get("mesh_model_training_allowed") is True
        and payload.get("mesh_model_mode") != "training_candidate"
    ):
        blockers.append("mesh_model_training_allowed_requires_training_candidate_mode")
    if payload.get("mesh_model_training_allowed") is True and payload.get("advisory_only") is True:
        blockers.append("mesh_model_training_must_not_be_advisory_only")
    if not payload.get("source_packet_refs"):
        blockers.append("source_packet_refs_missing")
    return blockers


def _evidence_bundle_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if payload.get("sealed") is not True:
        blockers.append("evidence_bundle_not_sealed")
    if payload.get("production_readiness_claim") is not False:
        blockers.append("recursive_chaos_bundle_must_not_claim_production_readiness")
    gate_results = payload.get("gate_results") if isinstance(payload.get("gate_results"), list) else []
    failed_gates = [
        str(gate.get("gate") or "unknown")
        for gate in gate_results
        if isinstance(gate, dict) and gate.get("status") in {"fail", "blocked"}
    ]
    blockers.extend(f"evidence_gate_not_green:{gate}" for gate in failed_gates)
    return blockers


def _raise_if_blocked(blockers: list[str]) -> None:
    if blockers:
        raise SchemaValidationError(";".join(sorted(set(blockers))))


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
