from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


PROCUREMENT_SECURITY_PACKAGE_SCHEMA = "procurement-security-package.schema.json"
PROCUREMENT_SECURITY_PACKAGE_VERSION = "mesh.procurement_security_package.v1"
PROCUREMENT_SECURITY_VERIFICATION_VERSION = "mesh.procurement_security_package_verification.v1"
REQUIRED_PROCUREMENT_SECTIONS = frozenset(
    {
        "sso_identity",
        "audit_export",
        "retention_controls",
        "data_boundaries",
        "deployment_modes",
        "security_answers",
        "support_escalation",
        "known_limits",
    }
)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def load_procurement_security_package(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    package_path = Path(path)
    if not package_path.exists():
        return None
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    validate_payload(PROCUREMENT_SECURITY_PACKAGE_SCHEMA, payload)
    return payload


def procurement_security_package_ready(path: str | Path | None) -> bool:
    return verify_procurement_security_package(path)["status"] == "pass"


def verify_procurement_security_package(path: str | Path | None) -> dict[str, Any]:
    package_path = Path(path) if path else None
    errors: list[str] = []
    try:
        package = load_procurement_security_package(package_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        package = None
        errors.append(str(exc))

    checks = _package_checks(package, package_path)
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": PROCUREMENT_SECURITY_VERIFICATION_VERSION,
        "status": "pass" if not failed else "fail",
        "package_path": str(package_path) if package_path else None,
        "package_id": package.get("package_id") if package else None,
        "required_sections": sorted(REQUIRED_PROCUREMENT_SECTIONS),
        "covered_sections": sorted(_section_ids(package)),
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
            "all_required_sections_present": False,
            "all_sections_ready": False,
            "artifact_refs_exist": False,
            "verification_commands_reference_repo_tools": False,
            "no_raw_secret_material": False,
        }
    return {
        "package_present": package_path is not None and package_path.exists(),
        "schema_valid": True,
        "package_ready": package.get("status") == "ready",
        "all_required_sections_present": REQUIRED_PROCUREMENT_SECTIONS.issubset(_section_ids(package)),
        "all_sections_ready": _all_sections_ready(package),
        "artifact_refs_exist": _artifact_refs_exist(package),
        "verification_commands_reference_repo_tools": _verification_commands_reference_repo_tools(package),
        "no_raw_secret_material": package.get("raw_secret_material_present") is False,
    }


def _section_ids(package: dict[str, Any] | None) -> set[str]:
    if not package:
        return set()
    sections = package.get("sections")
    if not isinstance(sections, list):
        return set()
    return {str(section.get("section_id")) for section in sections if isinstance(section, dict)}


def _all_sections_ready(package: dict[str, Any]) -> bool:
    return all(
        isinstance(section, dict)
        and section.get("status") == "ready"
        and bool(str(section.get("owner") or "").strip())
        and bool(str(section.get("summary") or "").strip())
        for section in package.get("sections", [])
    )


def _artifact_refs_exist(package: dict[str, Any]) -> bool:
    return all(
        _repo_ref_exists(ref)
        for section in package.get("sections", [])
        if isinstance(section, dict)
        for ref in section.get("artifact_refs", [])
    )


def _verification_commands_reference_repo_tools(package: dict[str, Any]) -> bool:
    commands = [
        str(command)
        for section in package.get("sections", [])
        if isinstance(section, dict)
        for command in section.get("verification_commands", [])
    ]
    if not commands:
        return False
    return all(_command_tool_exists(command) for command in commands)


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
