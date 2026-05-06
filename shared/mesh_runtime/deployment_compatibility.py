from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY = REPO_ROOT / "config" / "deployment-compatibility.registry.json"
DEPLOYMENT_COMPATIBILITY_REGISTRY_SCHEMA = "deployment-compatibility-registry.schema.json"
DEPLOYMENT_COMPATIBILITY_MATRIX_SCHEMA = "deployment-compatibility-matrix.schema.json"
DEPLOYMENT_COMPATIBILITY_VERSION = "mesh.deployment_compatibility.v1"
REQUIRED_TARGETS = frozenset({"docker_compose", "kubernetes", "ecs_fargate"})
REQUIRED_VALIDATED_EVIDENCE = frozenset(
    {"health", "readiness", "persistence", "feedback", "audit", "rollback", "release_packet"}
)
ALLOWED_LEVELS = frozenset(
    {"validated", "supported", "recipe", "backlog", "next_validated_target", "not_planned"}
)


def load_deployment_compatibility_registry(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    registry_path = _resolve_path(path)
    if not registry_path.exists():
        return None
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_payload(DEPLOYMENT_COMPATIBILITY_REGISTRY_SCHEMA, payload)
    return payload


def deployment_compatibility_registry_ready(path: str | Path | None) -> bool:
    return verify_deployment_compatibility_registry(path)["status"] == "pass"


def verify_deployment_compatibility_registry(path: str | Path | None) -> dict[str, Any]:
    matrix = build_deployment_compatibility_matrix(path)
    return {
        "schema_version": "mesh.deployment_compatibility_verification.v1",
        "status": "pass" if matrix["status"] == "complete" else "fail",
        "checked_at": matrix["generated_at"],
        "registry_path": matrix["registry_path"],
        "registry_sha256": matrix["registry_sha256"],
        "target_count": matrix["target_count"],
        "validated_targets": matrix["validated_targets"],
        "next_validated_targets": matrix["next_validated_targets"],
        "blockers": matrix["blockers"],
    }


def build_deployment_compatibility_matrix(path: str | Path | None) -> dict[str, Any]:
    blockers: list[str] = []
    try:
        registry = load_deployment_compatibility_registry(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        registry = None
        blockers.append(f"deployment_compatibility_registry_invalid:{type(exc).__name__}")
    resolved_path = _resolve_path(path or DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY)
    targets_by_id: dict[str, Any] = {}
    if registry is None:
        blockers.append("deployment_compatibility_registry_missing")
    else:
        raw_targets = [entry for entry in registry.get("targets", []) if isinstance(entry, dict)]
        targets_by_id = {str(entry.get("target_id")): dict(entry) for entry in raw_targets}
        blockers.extend(_registry_blockers(raw_targets))
    matrix = {
        "schema_version": DEPLOYMENT_COMPATIBILITY_VERSION,
        "generated_at": _timestamp(),
        "status": "complete" if not blockers else "incomplete",
        "registry_path": _display_path(resolved_path),
        "registry_sha256": _sha256(resolved_path) if resolved_path.exists() else None,
        "target_count": len(targets_by_id),
        "validated_targets": sorted(
            target_id
            for target_id, target in targets_by_id.items()
            if target.get("level") == "validated"
        ),
        "next_validated_targets": sorted(
            target_id
            for target_id, target in targets_by_id.items()
            if target.get("level") == "next_validated_target"
        ),
        "targets": targets_by_id,
        "blockers": sorted(set(blockers)),
    }
    validate_payload(DEPLOYMENT_COMPATIBILITY_MATRIX_SCHEMA, matrix)
    return matrix


def _registry_blockers(targets: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    target_ids = [str(entry.get("target_id") or "") for entry in targets]
    duplicate_ids = sorted({target_id for target_id in target_ids if target_ids.count(target_id) > 1})
    if duplicate_ids:
        blockers.extend(f"duplicate_target:{target_id}" for target_id in duplicate_ids)
    missing_targets = sorted(REQUIRED_TARGETS - set(target_ids))
    blockers.extend(f"required_target_missing:{target_id}" for target_id in missing_targets)
    next_targets = sorted(
        str(entry.get("target_id"))
        for entry in targets
        if entry.get("level") == "next_validated_target"
    )
    if next_targets != ["ecs_fargate"]:
        blockers.append("ecs_fargate_not_single_next_validated_target")
    for entry in targets:
        target_id = str(entry.get("target_id") or "unknown")
        level = str(entry.get("level") or "")
        if level not in ALLOWED_LEVELS:
            blockers.append(f"{target_id}:level_invalid")
            continue
        blockers.extend(_target_blockers(target_id, entry, level))
    return blockers


def _target_blockers(target_id: str, entry: dict[str, Any], level: str) -> list[str]:
    blockers: list[str] = []
    if not str(entry.get("product_stance") or "").strip():
        blockers.append(f"{target_id}:product_stance_missing")
    if not str(entry.get("authority_boundary") or "").strip():
        blockers.append(f"{target_id}:authority_boundary_missing")
    if not entry.get("evidence_refs"):
        blockers.append(f"{target_id}:evidence_refs_missing")
    if level == "validated":
        evidence = set(str(item) for item in entry.get("required_evidence", []))
        if not REQUIRED_VALIDATED_EVIDENCE.issubset(evidence):
            blockers.append(f"{target_id}:validated_evidence_incomplete")
        if not entry.get("validation_commands"):
            blockers.append(f"{target_id}:validated_commands_missing")
        if entry.get("readiness_required") is not True:
            blockers.append(f"{target_id}:validated_readiness_not_required")
        if entry.get("release_packet_required") is not True:
            blockers.append(f"{target_id}:validated_release_packet_not_required")
        if entry.get("promotion_blockers"):
            blockers.append(f"{target_id}:validated_target_has_promotion_blockers")
    if level == "next_validated_target":
        if target_id != "ecs_fargate":
            blockers.append(f"{target_id}:unexpected_next_validated_target")
        if not entry.get("promotion_blockers"):
            blockers.append(f"{target_id}:next_target_missing_promotion_blockers")
        if entry.get("readiness_required") is not True or entry.get("release_packet_required") is not True:
            blockers.append(f"{target_id}:next_target_missing_required_release_gates")
    if level == "not_planned":
        if entry.get("readiness_required") or entry.get("release_packet_required"):
            blockers.append(f"{target_id}:not_planned_target_requires_release_gate")
        if not entry.get("promotion_blockers"):
            blockers.append(f"{target_id}:not_planned_reason_missing")
    return blockers


def _resolve_path(raw: str | Path | None) -> Path:
    path = Path(raw or DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY)
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
