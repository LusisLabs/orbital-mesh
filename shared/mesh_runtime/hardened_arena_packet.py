from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .hardened_arena import (
    DEFAULT_HARDENED_ARENA_PROFILE_REGISTRY,
    REQUIRED_PROOF_GATES,
    get_hardened_arena_profile,
    verify_hardened_arena_profiles,
)
from .hardened_arena_catalog import DEFAULT_HARDENED_ARENA_CATALOG, load_hardened_arena_catalog
from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
HARDENED_ARENA_PACKET_SCHEMA = "hardened-arena-packet.schema.json"
HARDENED_ARENA_PACKET_VERSION = "mesh.hardened_arena.packet.v1"
HARDENED_ARENA_PACKET_VERIFICATION_VERSION = "mesh.hardened_arena.packet_verification.v1"


def generate_hardened_arena_packet(
    profile_id: str,
    *,
    profile_registry_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    profile_path = _resolve_path(profile_registry_path or DEFAULT_HARDENED_ARENA_PROFILE_REGISTRY)
    catalog_resolved_path = _resolve_path(catalog_path or DEFAULT_HARDENED_ARENA_CATALOG)
    checked_at = generated_at or _timestamp()
    profile_verification = verify_hardened_arena_profiles(profile_path)
    profile = get_hardened_arena_profile(profile_id, profile_path)
    catalog = load_hardened_arena_catalog(catalog_resolved_path)
    catalog_by_slug = {str(entry.get("slug")): entry for entry in catalog.get("entries", []) if isinstance(entry, dict)}
    component_graph = [_component_node(component) for component in profile.get("components", [])]
    dhi_refs = [_dhi_ref(component, catalog_by_slug) for component in profile.get("components", []) if _source(component).get("source_type") == "dhi"]
    blockers = _packet_blockers(profile, profile_verification, dhi_refs)
    packet = {
        "schema_version": HARDENED_ARENA_PACKET_VERSION,
        "packet_id": _packet_id(profile_id, checked_at),
        "generated_at": checked_at,
        "selected_profile": {
            "profile_id": profile["profile_id"],
            "display_name": profile["display_name"],
            "intended_use": profile["intended_use"],
            "lifecycle_state": profile["lifecycle_state"],
            "profile_readiness_posture": profile["readiness_posture"],
        },
        "source_refs": {
            "profile_registry": _display_path(profile_path),
            "catalog": _display_path(catalog_resolved_path),
        },
        "component_graph": component_graph,
        "authority_boundaries": sorted({str(component.get("authority_boundary")) for component in profile.get("components", [])}),
        "credential_classes": sorted({str(component.get("credential_class")) for component in profile.get("components", [])}),
        "dhi_catalog_refs": dhi_refs,
        "blockers": blockers,
        "proof_checklist": [
            {"gate": gate, "required": True, "observed": False, "evidence_ref": None}
            for gate in sorted(set(profile.get("proof_gates", {}).get("required", [])))
        ],
        "mesh_probe_plan": {
            "checks": list(profile.get("probe_plan", {}).get("checks", [])),
            "required": profile.get("probe_plan", {}).get("required") is True,
        },
        "failure_mode_curriculum": list(profile.get("probe_plan", {}).get("failure_modes", [])),
        "cleanup_plan": dict(profile.get("cleanup", {})),
        "data_retention_plan": {
            "classification": profile.get("data_boundary", {}).get("classification"),
            "tenant_boundary": profile.get("data_boundary", {}).get("tenant_boundary"),
            "retention": profile.get("data_boundary", {}).get("retention"),
            "export_policy": profile.get("data_boundary", {}).get("export_policy"),
            "raw_secret_policy": profile.get("data_boundary", {}).get("raw_secret_policy"),
        },
        "readiness_posture": {
            "status": "profile_verified" if profile_verification["status"] == "pass" else "blocked",
            "target_validated": False,
            "production_ready": False,
            "statement": "Profile contract is verified, but no target has been observed; this packet is review/proof-planning material only.",
        },
    }
    validate_payload(HARDENED_ARENA_PACKET_SCHEMA, packet)
    return packet


def write_hardened_arena_packet(packet: dict[str, Any], output_path: str | Path) -> None:
    validate_payload(HARDENED_ARENA_PACKET_SCHEMA, packet)
    path = _resolve_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_hardened_arena_packet(path: str | Path) -> dict[str, Any]:
    packet_path = _resolve_path(path)
    blockers: list[str] = []
    packet: dict[str, Any] | None = None
    packet_sha256: str | None = None
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        validate_payload(HARDENED_ARENA_PACKET_SCHEMA, packet)
        packet_sha256 = _sha256(packet_path)
        blockers.extend(_packet_validation_blockers(packet))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        blockers.append(f"hardened_arena_packet_invalid:{type(exc).__name__}")
        if not packet_path.exists():
            blockers.append("hardened_arena_packet_missing")
    return {
        "schema_version": HARDENED_ARENA_PACKET_VERIFICATION_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": _timestamp(),
        "packet_path": _display_path(packet_path),
        "packet_sha256": packet_sha256,
        "profile_id": packet.get("selected_profile", {}).get("profile_id") if isinstance(packet, dict) else None,
        "readiness_status": packet.get("readiness_posture", {}).get("status") if isinstance(packet, dict) else None,
        "blockers": sorted(set(blockers)),
    }


def output_path_is_generated(path: str | Path) -> bool:
    resolved = _resolve_path(path)
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] == "dist"


def _component_node(component: dict[str, Any]) -> dict[str, Any]:
    return {
        "component_id": component["component_id"],
        "display_name": component["display_name"],
        "component_class": component["component_class"],
        "purpose": component["purpose"],
        "source": dict(component.get("source", {})),
        "authority_boundary": component["authority_boundary"],
        "credential_class": component["credential_class"],
        "mutates_state": component["mutates_state"],
        "dependencies": [],
        "rollback_proof_requirements": list(component.get("rollback_proof_requirements", [])),
    }


def _dhi_ref(component: dict[str, Any], catalog_by_slug: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = _source(component)
    dhi_slug = str(source.get("dhi_slug") or "")
    catalog_slug = _catalog_slug(dhi_slug)
    catalog_entry = catalog_by_slug.get(catalog_slug)
    blockers = list(source.get("blockers", []))
    if catalog_entry is None:
        blockers.append("dhi_catalog_entry_not_matched")
    return {
        "component_id": str(component.get("component_id")),
        "dhi_slug": dhi_slug,
        "catalog_match": catalog_entry is not None,
        "catalog_slug": catalog_slug if catalog_entry is not None else None,
        "source_url": catalog_entry.get("source_url") if catalog_entry else None,
        "proof_placeholders": dict(catalog_entry.get("proof_placeholders", {})) if catalog_entry else {},
        "blockers": blockers,
    }


def _packet_blockers(
    profile: dict[str, Any], profile_verification: dict[str, Any], dhi_refs: list[dict[str, Any]]
) -> list[str]:
    blockers = list(profile.get("blockers", []))
    blockers.extend(str(blocker) for blocker in profile_verification.get("blockers", []))
    for ref in dhi_refs:
        blockers.extend(str(blocker) for blocker in ref.get("blockers", []))
    if profile_verification.get("status") != "pass":
        blockers.append("profile_registry_not_verified")
    blockers.append("target_validation_missing")
    return sorted(set(blockers))


def _packet_validation_blockers(packet: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    posture = packet.get("readiness_posture") if isinstance(packet.get("readiness_posture"), dict) else {}
    if posture.get("target_validated") is not False:
        blockers.append("packet_overclaims_target_validated")
    if posture.get("production_ready") is not False:
        blockers.append("packet_overclaims_production_ready")
    if posture.get("status") == "target_validated":
        blockers.append("packet_status_overclaims_target_validated")
    checklist_gates = {str(item.get("gate")) for item in packet.get("proof_checklist", []) if isinstance(item, dict)}
    for gate in sorted(REQUIRED_PROOF_GATES - checklist_gates):
        blockers.append(f"proof_gate_missing:{gate}")
    if not packet.get("component_graph"):
        blockers.append("component_graph_missing")
    if not packet.get("mesh_probe_plan"):
        blockers.append("mesh_probe_plan_missing")
    if not packet.get("failure_mode_curriculum"):
        blockers.append("failure_mode_curriculum_missing")
    if not packet.get("cleanup_plan"):
        blockers.append("cleanup_plan_missing")
    if not packet.get("data_retention_plan"):
        blockers.append("data_retention_plan_missing")
    return blockers


def _source(component: dict[str, Any]) -> dict[str, Any]:
    source = component.get("source")
    return source if isinstance(source, dict) else {}


def _catalog_slug(dhi_slug: str) -> str:
    return dhi_slug.rstrip("/").split("/")[-1]


def _packet_id(profile_id: str, generated_at: str) -> str:
    digest = hashlib.sha256(f"{profile_id}:{generated_at}".encode("utf-8")).hexdigest()[:12]
    return f"hardened-arena-{profile_id}-{digest}"


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
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
