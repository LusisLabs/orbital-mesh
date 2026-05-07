from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


PUBLIC_PROOF_PACKAGE_SCHEMA = "public-proof-package.schema.json"
PUBLIC_PROOF_PACKAGE_VERSION = "mesh.public_proof_package.v1"
PUBLIC_PROOF_VERIFICATION_VERSION = "mesh.public_proof_package_verification.v1"
REQUIRED_PUBLIC_PROOF_COMPONENTS = frozenset(
    {
        "benchmark_report",
        "architecture_paper",
        "demo_dataset",
        "run_export",
        "limitations_statement",
    }
)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def load_public_proof_package(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    package_path = _resolve_path(path)
    if not package_path.exists():
        return None
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    validate_payload(PUBLIC_PROOF_PACKAGE_SCHEMA, payload)
    return payload


def public_proof_package_ready(path: str | Path | None) -> bool:
    return verify_public_proof_package(path)["status"] == "pass"


def verify_public_proof_package(path: str | Path | None) -> dict[str, Any]:
    package_path = _resolve_path(path) if path else None
    errors: list[str] = []
    try:
        package = load_public_proof_package(package_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        package = None
        errors.append(str(exc))

    checks = _package_checks(package, package_path)
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": PUBLIC_PROOF_VERIFICATION_VERSION,
        "status": "pass" if not failed else "fail",
        "package_path": _display_path(package_path) if package_path else None,
        "package_id": package.get("package_id") if package else None,
        "required_components": sorted(REQUIRED_PUBLIC_PROOF_COMPONENTS),
        "covered_components": sorted(_component_ids(package)),
        "failed_checks": failed,
        "checks": checks,
        "errors": errors,
    }


def _package_checks(package: dict[str, Any] | None, package_path: Path | None) -> dict[str, bool]:
    if package is None:
        return {
            "package_present": False,
            "schema_valid": False,
            "package_ready": False,
            "all_required_components_present": False,
            "all_components_ready": False,
            "artifact_refs_exist": False,
            "verification_commands_reference_repo_tools": False,
            "limitations_refs_exist": False,
            "public_claims_allowed": False,
            "no_raw_secret_material": False,
        }
    return {
        "package_present": package_path is not None and package_path.exists(),
        "schema_valid": True,
        "package_ready": package.get("status") == "ready",
        "all_required_components_present": REQUIRED_PUBLIC_PROOF_COMPONENTS.issubset(_component_ids(package)),
        "all_components_ready": _all_components_ready(package),
        "artifact_refs_exist": _artifact_refs_exist(package),
        "verification_commands_reference_repo_tools": _verification_commands_reference_repo_tools(package),
        "limitations_refs_exist": _limitations_refs_exist(package),
        "public_claims_allowed": _public_claims_allowed(package),
        "no_raw_secret_material": package.get("raw_secret_material_present") is False,
    }


def _component_ids(package: dict[str, Any] | None) -> set[str]:
    if not package:
        return set()
    components = package.get("components")
    if not isinstance(components, list):
        return set()
    return {str(component.get("component_id")) for component in components if isinstance(component, dict)}


def _all_components_ready(package: dict[str, Any]) -> bool:
    return all(
        isinstance(component, dict)
        and component.get("status") == "ready"
        and bool(str(component.get("owner") or "").strip())
        and bool(str(component.get("summary") or "").strip())
        for component in package.get("components", [])
    )


def _artifact_refs_exist(package: dict[str, Any]) -> bool:
    return all(
        _repo_ref_exists(ref)
        for component in package.get("components", [])
        if isinstance(component, dict)
        for ref in component.get("artifact_refs", [])
    )


def _verification_commands_reference_repo_tools(package: dict[str, Any]) -> bool:
    commands = [
        str(command)
        for component in package.get("components", [])
        if isinstance(component, dict)
        for command in component.get("verification_commands", [])
    ]
    if not commands:
        return False
    return all(_command_tool_exists(command) for command in commands)


def _limitations_refs_exist(package: dict[str, Any]) -> bool:
    return all(
        _repo_ref_exists(component.get("limitations_ref"))
        for component in package.get("components", [])
        if isinstance(component, dict)
    )


def _public_claims_allowed(package: dict[str, Any]) -> bool:
    return all(
        isinstance(component, dict) and component.get("public_claim_allowed") is True
        for component in package.get("components", [])
    )


def _repo_ref_exists(ref: Any) -> bool:
    ref_text = str(ref or "").strip()
    if not ref_text or "://" in ref_text or ref_text.startswith("$"):
        return bool(ref_text)
    return (_REPO_ROOT / ref_text).exists()


def _command_tool_exists(command: str) -> bool:
    tool = command.strip().split(" ", 1)[0]
    if not tool or tool.startswith("$"):
        return False
    if tool in {"python3", "npm", "docker", "git"}:
        return True
    return (_REPO_ROOT / tool).exists()


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else _REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)
