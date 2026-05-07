from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path
from typing import Any

from .schema_validation import validate_payload


RUN_EXPORT_RETRIEVAL_SCHEMA = "run-export-retrieval.schema.json"
RUN_EXPORT_RETRIEVAL_VERSION = "mesh.run_export_retrieval.v1"
_SECRET_KEY_MARKERS = ("token", "secret", "api_key", "apikey", "authorization", "password", "jwt", "credential", "kubeconfig")
_REQUIRED_ARCHIVE_ENTRIES = frozenset(
    {
        "manifest.json",
        "package.json",
        "timeline.json",
        "postmortem.md",
        "merkle.json",
        "timeline-proof.json",
        "checks.json",
    }
)


def verify_run_export_retrieval(
    *,
    package_path: str | Path | None,
    archive_path: str | Path | None = None,
) -> dict[str, Any]:
    package_file = Path(package_path) if package_path else None
    archive_file = Path(archive_path) if archive_path else None
    errors: list[str] = []
    package = _load_package(package_file, errors)
    checks = _package_checks(package, package_file)
    if archive_file is not None:
        checks.update(_archive_checks(package, archive_file, errors))
    payload = {
        "schema_version": RUN_EXPORT_RETRIEVAL_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) and not errors else "fail",
        "package_path": str(package_file) if package_file else None,
        "archive_path": str(archive_file) if archive_file else None,
        "run_id": package.get("run_id") if package else None,
        "package_sha256": package.get("package_sha256") if package else None,
        "checks": checks,
        "errors": errors,
    }
    validate_payload(RUN_EXPORT_RETRIEVAL_SCHEMA, payload)
    return payload


def _load_package(path: Path | None, errors: list[str]) -> dict[str, Any] | None:
    if path is None:
        errors.append("package_path_missing")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"package_load_failed:{exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("package_not_object")
        return None
    return payload


def _package_checks(package: dict[str, Any] | None, package_path: Path | None) -> dict[str, bool]:
    if package is None:
        return {
            "package_present": False,
            "package_version_valid": False,
            "package_checksum_valid": False,
            "timeline_present": False,
            "postmortem_present": False,
            "merkle_proof_present": False,
            "timeline_proof_present": False,
            "checks_pass": False,
            "retention_present": False,
            "redaction_declared": False,
            "secret_fields_redacted": False,
            "package_path_matches": False,
        }
    return {
        "package_present": True,
        "package_version_valid": package.get("package_version") == "mesh.run_export.v1",
        "package_checksum_valid": _package_sha256_valid(package),
        "timeline_present": bool(package.get("timeline_json")),
        "postmortem_present": bool(str(package.get("postmortem_markdown") or "").strip()),
        "merkle_proof_present": isinstance(package.get("merkle"), dict)
        and bool((package.get("merkle") or {}).get("snapshot"))
        and bool((package.get("merkle") or {}).get("latest_event_proof")),
        "timeline_proof_present": isinstance(package.get("timeline_proof"), dict)
        and bool((package.get("timeline_proof") or {}).get("timeline")),
        "checks_pass": _checks_pass(package.get("checks")),
        "retention_present": isinstance(package.get("retention"), dict)
        and bool((package.get("retention") or {}).get("delete_after")),
        "redaction_declared": isinstance(package.get("redaction"), dict)
        and (package.get("redaction") or {}).get("enabled") is True,
        "secret_fields_redacted": _secret_fields_redacted(package),
        "package_path_matches": package_path is None or str(package.get("path") or "") == str(package_path),
    }


def _archive_checks(
    package: dict[str, Any] | None,
    archive_path: Path,
    errors: list[str],
) -> dict[str, bool]:
    checks = {
        "archive_present": archive_path.is_file(),
        "archive_zip_valid": False,
        "archive_entries_required": False,
        "archive_manifest_matches": False,
        "archive_package_matches": False,
        "archive_paths_safe": False,
        "archive_vault_documents_present": True,
    }
    if not archive_path.is_file() or package is None:
        return checks
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            name_set = set(names)
            checks["archive_zip_valid"] = True
            checks["archive_entries_required"] = _REQUIRED_ARCHIVE_ENTRIES.issubset(name_set)
            checks["archive_paths_safe"] = all(_archive_path_safe(name) for name in names)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8")) if "manifest.json" in name_set else {}
            archived_package = json.loads(archive.read("package.json").decode("utf-8")) if "package.json" in name_set else {}
            checks["archive_manifest_matches"] = (
                isinstance(manifest, dict)
                and manifest.get("archive_version") == "mesh.run_export_archive.v1"
                and manifest.get("run_id") == package.get("run_id")
                and manifest.get("package_sha256") == package.get("package_sha256")
            )
            checks["archive_package_matches"] = (
                isinstance(archived_package, dict)
                and archived_package.get("run_id") == package.get("run_id")
                and archived_package.get("package_sha256") == package.get("package_sha256")
            )
            vault_docs = package.get("vault_documents") if isinstance(package.get("vault_documents"), list) else []
            if vault_docs:
                checks["archive_vault_documents_present"] = any(name.startswith("vault/") for name in names)
    except (OSError, json.JSONDecodeError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"archive_load_failed:{exc}")
    return checks


def _package_sha256_valid(package: dict[str, Any]) -> bool:
    expected = package.get("package_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    payload = dict(package)
    payload.pop("package_sha256", None)
    payload.pop("path", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest() == expected


def _checks_pass(raw_checks: Any) -> bool:
    return isinstance(raw_checks, dict) and bool(raw_checks) and all(value is True for value in raw_checks.values())


def _secret_fields_redacted(value: Any, key: str = "") -> bool:
    if key == "secret_markers":
        return True
    if isinstance(value, dict):
        return all(_secret_fields_redacted(child, child_key) for child_key, child in value.items())
    if isinstance(value, list):
        return all(_secret_fields_redacted(child, key) for child in value)
    if any(marker in key.lower() for marker in _SECRET_KEY_MARKERS):
        return value in (None, "", "<redacted>")
    return True


def _archive_path_safe(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
