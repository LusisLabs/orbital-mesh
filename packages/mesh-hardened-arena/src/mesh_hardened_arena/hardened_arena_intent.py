from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .hardened_arena import DEFAULT_HARDENED_ARENA_PROFILE_REGISTRY, get_hardened_arena_profile
from .schema_validation import SchemaValidationError, validate_payload


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
HARDENED_ARENA_INTENT_SCHEMA = "hardened-arena-intent.schema.json"
HARDENED_ARENA_INTENT_VERSION = "mesh.hardened_arena.intent.v1"
HARDENED_ARENA_INTENT_VERIFICATION_VERSION = "mesh.hardened_arena.intent_verification.v1"
REQUIRED_INTENT_KINDS = frozenset(
    {
        "helm_values_intent",
        "kustomize_intent",
        "rbac_intent",
        "network_policy_intent",
        "secret_reference_manifest",
        "cleanup_manifest",
    }
)
FORBIDDEN_LIVE_TOKENS = ("kubectl apply", "helm install", "kubeconfig:", "secret_value:", "password:", "token:")


def generate_hardened_arena_intent(
    profile_id: str,
    *,
    profile_registry_path: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    profile_path = _resolve_path(profile_registry_path or DEFAULT_HARDENED_ARENA_PROFILE_REGISTRY)
    profile = get_hardened_arena_profile(profile_id, profile_path)
    checked_at = generated_at or _timestamp()
    output_kinds = list(REQUIRED_INTENT_KINDS)
    if "compose_overlay_intent" in profile.get("supported_outputs", []):
        output_kinds.append("compose_overlay_intent")
    outputs = [_output_for_kind(kind, profile) for kind in sorted(output_kinds)]
    bundle = {
        "schema_version": HARDENED_ARENA_INTENT_VERSION,
        "intent_id": _intent_id(profile_id, checked_at),
        "generated_at": checked_at,
        "profile_id": profile_id,
        "review_only": True,
        "live_deployment_allowed": False,
        "secret_values_present": False,
        "kubeconfig_material_present": False,
        "outputs": outputs,
        "rollback_cleanup_requirements": _rollback_cleanup_requirements(profile),
        "blockers": sorted(set(profile.get("blockers", []) + ["intent_review_required", "target_validation_missing"])),
    }
    validate_payload(HARDENED_ARENA_INTENT_SCHEMA, bundle)
    return bundle


def write_hardened_arena_intent(bundle: dict[str, Any], output_dir: str | Path) -> Path:
    validate_payload(HARDENED_ARENA_INTENT_SCHEMA, bundle)
    directory = _resolve_path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    for output in bundle["outputs"]:
        (directory / output["file_name"]).write_text(
            json.dumps(output["content"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    bundle_path = directory / "intent-bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle_path


def verify_hardened_arena_intent(path: str | Path) -> dict[str, Any]:
    intent_path = _resolve_path(path)
    blockers: list[str] = []
    bundle: dict[str, Any] | None = None
    intent_sha256: str | None = None
    try:
        bundle = json.loads(intent_path.read_text(encoding="utf-8"))
        validate_payload(HARDENED_ARENA_INTENT_SCHEMA, bundle)
        intent_sha256 = _sha256(intent_path)
        blockers.extend(_intent_blockers(bundle))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        blockers.append(f"hardened_arena_intent_invalid:{type(exc).__name__}")
        if not intent_path.exists():
            blockers.append("hardened_arena_intent_missing")
    return {
        "schema_version": HARDENED_ARENA_INTENT_VERIFICATION_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": _timestamp(),
        "intent_path": _display_path(intent_path),
        "intent_sha256": intent_sha256,
        "profile_id": bundle.get("profile_id") if isinstance(bundle, dict) else None,
        "output_count": len(bundle.get("outputs", [])) if isinstance(bundle, dict) else 0,
        "blockers": sorted(set(blockers)),
    }


def output_dir_is_generated(path: str | Path) -> bool:
    resolved = _resolve_path(path)
    try:
        relative = resolved.relative_to(PACKAGE_ROOT)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] == "dist"


def _output_for_kind(kind: str, profile: dict[str, Any]) -> dict[str, Any]:
    content_builders = {
        "helm_values_intent": _helm_values_intent,
        "kustomize_intent": _kustomize_intent,
        "compose_overlay_intent": _compose_overlay_intent,
        "rbac_intent": _rbac_intent,
        "network_policy_intent": _network_policy_intent,
        "secret_reference_manifest": _secret_reference_manifest,
        "cleanup_manifest": _cleanup_manifest,
    }
    file_names = {
        "helm_values_intent": "helm-values.intent.json",
        "kustomize_intent": "kustomize.intent.json",
        "compose_overlay_intent": "compose-overlay.intent.json",
        "rbac_intent": "rbac.intent.json",
        "network_policy_intent": "network-policy.intent.json",
        "secret_reference_manifest": "secret-reference-manifest.json",
        "cleanup_manifest": "cleanup-manifest.json",
    }
    return {
        "kind": kind,
        "file_name": file_names[kind],
        "required": kind != "compose_overlay_intent" or "compose_overlay_intent" in profile.get("supported_outputs", []),
        "content": content_builders[kind](profile),
    }


def _helm_values_intent(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mesh.hardened_arena.helm_values_intent.v1",
        "review_only": True,
        "profile_id": profile["profile_id"],
        "components": [_component_ref(component) for component in profile.get("components", [])],
        "notes": ["review material only", "no live Helm command is emitted"],
    }


def _kustomize_intent(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mesh.hardened_arena.kustomize_intent.v1",
        "review_only": True,
        "resources": [f"components/{component['component_id']}.yaml" for component in profile.get("components", [])],
        "patches": ["rbac.intent.json", "network-policy.intent.json", "secret-reference-manifest.json"],
    }


def _compose_overlay_intent(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mesh.hardened_arena.compose_overlay_intent.v1",
        "review_only": True,
        "services": {
            component["component_id"]: {
                "image_or_chart_ref": component.get("source", {}).get("display_ref"),
                "profiles": [profile["profile_id"]],
                "secrets": [f"ref:{component['component_id']}_secret"] if component.get("credential_class") != "none" else [],
            }
            for component in profile.get("components", [])
        },
    }


def _rbac_intent(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mesh.hardened_arena.rbac_intent.v1",
        "review_only": True,
        "subjects": [
            {
                "component_id": component["component_id"],
                "credential_class": component["credential_class"],
                "authority_boundary": component["authority_boundary"],
                "allowed_verbs": ["get", "list", "watch"] if component.get("mutates_state") is not True else ["review_required_for_mutation"],
            }
            for component in profile.get("components", [])
        ],
    }


def _network_policy_intent(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mesh.hardened_arena.network_policy_intent.v1",
        "review_only": True,
        "default_deny": True,
        "allowed_edges": [
            {
                "from": "mesh_probe_lane",
                "to": component["component_id"],
                "purpose": component["purpose"],
            }
            for component in profile.get("components", [])
        ],
    }


def _secret_reference_manifest(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mesh.hardened_arena.secret_reference_manifest.v1",
        "review_only": True,
        "raw_secret_values_present": False,
        "references": [
            {
                "component_id": component["component_id"],
                "credential_class": component["credential_class"],
                "secret_ref": f"ref:{component['component_id']}_secret" if component.get("credential_class") != "none" else None,
            }
            for component in profile.get("components", [])
        ],
    }


def _cleanup_manifest(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "mesh.hardened_arena.cleanup_manifest.v1",
        "review_only": True,
        "kill_switch_required": profile.get("cleanup", {}).get("kill_switch_required") is True,
        "steps": list(profile.get("cleanup", {}).get("steps", [])),
        "artifacts_to_remove": list(profile.get("cleanup", {}).get("artifacts_to_remove", [])),
    }


def _component_ref(component: dict[str, Any]) -> dict[str, Any]:
    source = component.get("source", {})
    return {
        "component_id": component["component_id"],
        "source_type": source.get("source_type"),
        "display_ref": source.get("display_ref"),
        "dhi_slug": source.get("dhi_slug"),
        "digest_ref": source.get("digest_ref"),
        "sbom_ref": source.get("sbom_ref"),
        "provenance_ref": source.get("provenance_ref"),
        "blockers": list(source.get("blockers", [])),
    }


def _rollback_cleanup_requirements(profile: dict[str, Any]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    cleanup_steps = list(profile.get("cleanup", {}).get("steps", []))
    for component in profile.get("components", []):
        if component.get("mutates_state") is True or component.get("authority_boundary") == "mutating_actuator":
            requirements.append(
                {
                    "component_id": component["component_id"],
                    "rollback_intent": list(component.get("rollback_proof_requirements", [])),
                    "cleanup_intent": cleanup_steps,
                }
            )
    return requirements


def _intent_blockers(bundle: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if bundle.get("review_only") is not True:
        blockers.append("intent_not_review_only")
    if bundle.get("live_deployment_allowed") is not False:
        blockers.append("intent_allows_live_deployment")
    if bundle.get("secret_values_present") is not False:
        blockers.append("intent_contains_secret_values")
    if bundle.get("kubeconfig_material_present") is not False:
        blockers.append("intent_contains_kubeconfig_material")
    output_kinds = {str(output.get("kind")) for output in bundle.get("outputs", []) if isinstance(output, dict)}
    for kind in sorted(REQUIRED_INTENT_KINDS - output_kinds):
        blockers.append(f"intent_output_missing:{kind}")
    if not bundle.get("rollback_cleanup_requirements"):
        blockers.append("mutating_component_rollback_cleanup_intent_missing")
    serialized = json.dumps(bundle, sort_keys=True).lower()
    for token in FORBIDDEN_LIVE_TOKENS:
        if token in serialized:
            blockers.append(f"forbidden_live_or_secret_material:{token}")
    return blockers


def _intent_id(profile_id: str, generated_at: str) -> str:
    digest = hashlib.sha256(f"{profile_id}:{generated_at}:intent".encode("utf-8")).hexdigest()[:12]
    return f"hardened-arena-intent-{profile_id}-{digest}"


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
