from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARDENED_ARENA_PROFILE_REGISTRY = PACKAGE_ROOT / "config" / "hardened-arena.profiles.json"
HARDENED_ARENA_PROFILES_SCHEMA = "hardened-arena-profiles.schema.json"
HARDENED_ARENA_PROFILE_REGISTRY_VERSION = "mesh.hardened_arena.profiles.v1"
HARDENED_ARENA_PROFILE_VERIFICATION_VERSION = "mesh.hardened_arena.profile_verification.v1"
REQUIRED_PROFILE_IDS = frozenset(
    {
        "solo_project_default",
        "startup_saas_staging",
        "enterprise_onprem_rehearsal",
    }
)
REQUIRED_PROOF_GATES = frozenset(
    {
        "health",
        "readiness",
        "feedback",
        "audit",
        "rollback",
        "run_export",
        "kill_switch",
        "cleanup",
        "release_packet",
    }
)
REQUIRED_PROBE_CHECKS = frozenset(
    {
        "health_endpoint",
        "readiness_endpoint",
        "feedback_source",
        "audit_event",
        "rollback_plan",
        "run_export",
        "kill_switch",
        "cleanup",
        "release_packet_binding",
    }
)


def load_hardened_arena_profiles(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = _resolve_path(path or DEFAULT_HARDENED_ARENA_PROFILE_REGISTRY)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_payload(HARDENED_ARENA_PROFILES_SCHEMA, payload)
    return payload


def hardened_arena_profiles_ready(path: str | Path | None = None) -> bool:
    return verify_hardened_arena_profiles(path)["status"] == "pass"


def verify_hardened_arena_profiles(path: str | Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_path(path or DEFAULT_HARDENED_ARENA_PROFILE_REGISTRY)
    blockers: list[str] = []
    profiles: list[dict[str, Any]] = []
    registry_sha256: str | None = None
    try:
        registry = load_hardened_arena_profiles(resolved_path)
        profiles = [entry for entry in registry.get("profiles", []) if isinstance(entry, dict)]
        registry_sha256 = _sha256(resolved_path)
        blockers.extend(_registry_blockers(profiles))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        blockers.append(f"hardened_arena_profile_registry_invalid:{type(exc).__name__}")
        if not resolved_path.exists():
            blockers.append("hardened_arena_profile_registry_missing")

    return {
        "schema_version": HARDENED_ARENA_PROFILE_VERIFICATION_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": _timestamp(),
        "registry_path": _display_path(resolved_path),
        "registry_sha256": registry_sha256,
        "profile_count": len(profiles),
        "profile_ids": sorted(str(profile.get("profile_id")) for profile in profiles),
        "blockers": sorted(set(blockers)),
    }


def get_hardened_arena_profile(profile_id: str, path: str | Path | None = None) -> dict[str, Any]:
    registry = load_hardened_arena_profiles(path)
    for profile in registry.get("profiles", []):
        if isinstance(profile, dict) and profile.get("profile_id") == profile_id:
            return profile
    raise KeyError(f"unknown hardened arena profile: {profile_id}")


def _registry_blockers(profiles: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    profile_ids = [str(profile.get("profile_id") or "") for profile in profiles]
    duplicate_ids = sorted({profile_id for profile_id in profile_ids if profile_ids.count(profile_id) > 1})
    blockers.extend(f"duplicate_profile:{profile_id}" for profile_id in duplicate_ids)
    observed_ids = set(profile_ids)
    missing = sorted(REQUIRED_PROFILE_IDS - observed_ids)
    extra = sorted(observed_ids - REQUIRED_PROFILE_IDS)
    blockers.extend(f"required_profile_missing:{profile_id}" for profile_id in missing)
    blockers.extend(f"unexpected_profile:{profile_id}" for profile_id in extra)
    if len(profiles) != len(REQUIRED_PROFILE_IDS):
        blockers.append("profile_count_not_exactly_three")
    for profile in profiles:
        blockers.extend(_profile_blockers(profile))
    return blockers


def _profile_blockers(profile: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    profile_id = str(profile.get("profile_id") or "unknown")
    if profile.get("lifecycle_state") != "recipe":
        blockers.append(f"{profile_id}:seed_profile_not_recipe")
    if profile.get("readiness_posture") not in {"recipe_only", "profile_verified"}:
        blockers.append(f"{profile_id}:readiness_posture_overclaims_target_validation")
    if profile.get("production_readiness_claim") is not False:
        blockers.append(f"{profile_id}:production_readiness_claim_not_false")
    if profile.get("ai_lane") not in {"proposal_only", "none"}:
        blockers.append(f"{profile_id}:ai_lane_invalid")
    blockers.extend(_required_section_blockers(profile_id, profile))
    components = [entry for entry in profile.get("components", []) if isinstance(entry, dict)]
    for component in components:
        blockers.extend(_component_blockers(profile_id, component))
    return blockers


def _required_section_blockers(profile_id: str, profile: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    cleanup = profile.get("cleanup") if isinstance(profile.get("cleanup"), dict) else {}
    if cleanup.get("required") is not True:
        blockers.append(f"{profile_id}:cleanup_not_required")
    if cleanup.get("kill_switch_required") is not True:
        blockers.append(f"{profile_id}:cleanup_kill_switch_not_required")
    if not cleanup.get("steps"):
        blockers.append(f"{profile_id}:cleanup_steps_missing")
    if not cleanup.get("artifacts_to_remove"):
        blockers.append(f"{profile_id}:cleanup_artifacts_missing")

    data_boundary = profile.get("data_boundary") if isinstance(profile.get("data_boundary"), dict) else {}
    for field_name in ("classification", "tenant_boundary", "retention", "export_policy", "raw_secret_policy"):
        if not str(data_boundary.get(field_name) or "").strip():
            blockers.append(f"{profile_id}:data_boundary_{field_name}_missing")
    if "secret" not in str(data_boundary.get("raw_secret_policy") or "").lower():
        blockers.append(f"{profile_id}:raw_secret_policy_not_explicit")

    probe_plan = profile.get("probe_plan") if isinstance(profile.get("probe_plan"), dict) else {}
    if probe_plan.get("required") is not True:
        blockers.append(f"{profile_id}:probe_plan_not_required")
    observed_checks = set(str(check) for check in probe_plan.get("checks", []))
    for check in sorted(REQUIRED_PROBE_CHECKS - observed_checks):
        blockers.append(f"{profile_id}:probe_check_missing:{check}")
    if not probe_plan.get("failure_modes"):
        blockers.append(f"{profile_id}:failure_mode_curriculum_missing")

    proof_gates = profile.get("proof_gates") if isinstance(profile.get("proof_gates"), dict) else {}
    observed_gates = set(str(gate) for gate in proof_gates.get("required", []))
    for gate in sorted(REQUIRED_PROOF_GATES - observed_gates):
        blockers.append(f"{profile_id}:proof_gate_missing:{gate}")
    if proof_gates.get("target_validated_allowed") is not False:
        blockers.append(f"{profile_id}:target_validated_allowed_before_proof")
    if proof_gates.get("production_ready_allowed") is not False:
        blockers.append(f"{profile_id}:production_ready_allowed_before_proof")
    return blockers


def _component_blockers(profile_id: str, component: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    component_id = str(component.get("component_id") or "unknown_component")
    source = component.get("source") if isinstance(component.get("source"), dict) else {}
    source_type = source.get("source_type")
    if source_type == "dhi":
        if not str(source.get("dhi_slug") or "").strip():
            blockers.append(f"{profile_id}:{component_id}:dhi_slug_missing")
        refs_present = all(
            str(source.get(field_name) or "").strip()
            for field_name in ("digest_ref", "sbom_ref", "provenance_ref")
        )
        if not refs_present and not source.get("blockers"):
            blockers.append(f"{profile_id}:{component_id}:dhi_proof_refs_or_blockers_missing")
    if component.get("mutates_state") is True or component.get("authority_boundary") == "mutating_actuator":
        rollback_requirements = [
            str(requirement).strip()
            for requirement in component.get("rollback_proof_requirements", [])
            if str(requirement).strip()
        ]
        if not rollback_requirements:
            blockers.append(f"{profile_id}:{component_id}:mutating_component_rollback_proof_missing")
    return blockers


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PACKAGE_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PACKAGE_ROOT))
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
