#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_IMAGE_TAG = "orbital-mesh-stack:dev"
REHEARSAL_SCANNER = "release-assurance-rehearsal"
REQUIRED_CI_CHECKS = frozenset({"python-test", "web", "docker-build"})
REQUIRED_CI_ATTESTATION_PROVIDER = "github-actions"
REQUIRED_CI_ATTESTATION_PROVIDER_REASON = "provider:github-actions"
REQUIRED_CI_ATTESTATION_FIELDS = ("workflow", "job", "run_id", "sha")
DEPENDENCY_LOCKFILES = (
    "pyproject.toml",
    "uv.lock",
    "web/package-lock.json",
    "meshapp/frontend/package-lock.json",
)
BUILD_INPUTS = (
    "Dockerfile",
    "Dockerfile.stack.hermes",
    "Dockerfile.latentmas.cpu",
    "docker-compose.stack.yml",
    "docker-compose.prod.yml",
)
DOCKERFILES = (
    "Dockerfile",
    "Dockerfile.stack.hermes",
    "Dockerfile.latentmas.cpu",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the orbital-mesh release provenance packet."
    )
    parser.add_argument("--json", action="store_true", help="Print the packet as JSON.")
    parser.add_argument("--output", help="Write the packet to this JSON path.")
    parser.add_argument("--require-complete", action="store_true", help="Exit non-zero unless every pilot provenance gate passes.")
    parser.add_argument("--allow-dirty", action="store_true", help="Do not fail completeness on a dirty git tree.")
    parser.add_argument("--image-tag", default=os.getenv("MESH_STACK_IMAGE") or os.getenv("MESH_IMAGE") or DEFAULT_IMAGE_TAG)
    parser.add_argument(
        "--image-digest",
        default=os.getenv("MESH_IMAGE_DIGEST")
        or os.getenv("MESH_STACK_IMAGE_DIGEST")
        or os.getenv("MESH_BUILD_IMAGE_DIGEST")
        or "",
    )
    parser.add_argument("--sbom", default=os.getenv("MESH_SBOM_PATH") or "")
    parser.add_argument("--vulnerability-scan", default=os.getenv("MESH_VULNERABILITY_SCAN_PATH") or "")
    parser.add_argument("--ci-attestation", default=os.getenv("MESH_CI_ATTESTATION_PATH") or "")
    parser.add_argument("--migration-rehearsal", default=os.getenv("MESH_MIGRATION_REHEARSAL_PATH") or "")
    parser.add_argument("--build-command", default=os.getenv("MESH_BUILD_COMMAND") or "")
    parser.add_argument("--builder-identity", default=os.getenv("MESH_BUILDER_IDENTITY") or os.getenv("USER") or "")
    parser.add_argument("--readiness-profile", default=os.getenv("MESH_READINESS_PROFILE") or "pilot")
    parser.add_argument("--environment", default=os.getenv("MESH_ENVIRONMENT") or "production")
    parser.add_argument("--policy-signing-key", default=os.getenv("MESH_POLICY_SIGNING_KEY") or "")
    parser.add_argument("--policy-signing-key-path", default=os.getenv("MESH_POLICY_SIGNING_KEY_PATH") or "")
    parser.add_argument("--policy-signing-key-id", default=os.getenv("MESH_POLICY_SIGNING_KEY_ID") or "policy-lifecycle-hmac")
    parser.add_argument(
        "--policy-lifecycle-manifest",
        default=os.getenv("MESH_POLICY_LIFECYCLE_MANIFEST_PATH") or "config/policy-lifecycle.manifest.json",
    )
    parser.add_argument(
        "--connector-certification-registry",
        default=os.getenv("MESH_CONNECTOR_CERTIFICATION_REGISTRY_PATH") or "config/connector-certification.registry.json",
    )
    parser.add_argument(
        "--deployment-compatibility-registry",
        default=os.getenv("MESH_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH") or "config/deployment-compatibility.registry.json",
    )
    parser.add_argument(
        "--base-image-digest",
        action="append",
        default=[],
        metavar="IMAGE=sha256:...",
        help="Supply a digest for an unpinned base image. Repeatable.",
    )
    args = parser.parse_args()

    packet = build_packet(args)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if packet["status"] == "complete" or not args.require_complete else 1


def build_packet(args: argparse.Namespace) -> dict[str, Any]:
    from shared.mesh_runtime.connector_certification import build_connector_certification_matrix
    from shared.mesh_runtime.deployment_compatibility import build_deployment_compatibility_matrix
    from shared.mesh_runtime.policy_lifecycle import build_policy_lifecycle_packet

    git = _git_snapshot()
    ci_attestation_payload = _json_artifact_payload(args.ci_attestation)
    ci_attestation = _ci_attestation_record(
        args.ci_attestation,
        ci_attestation_payload,
        expected_git_commit=str(git.get("commit") or ""),
    )
    trusted_ci_attestation_payload = ci_attestation_payload if ci_attestation.get("valid") else {}
    base_digest_overrides = _parse_base_digest_overrides(args.base_image_digest)
    base_digest_overrides.update(_attested_base_image_digests(trusted_ci_attestation_payload))
    base_images = _base_images(base_digest_overrides)
    policies = _hash_directory("policies", "*.json")
    policy_signing_key = _read_policy_signing_key(args)
    policy_lifecycle = build_policy_lifecycle_packet(
        manifest_path=args.policy_lifecycle_manifest,
        signing_key=policy_signing_key,
        signing_key_id=args.policy_signing_key_id,
    )
    connector_certification = build_connector_certification_matrix(
        registry_path=args.connector_certification_registry,
    )
    deployment_compatibility = build_deployment_compatibility_matrix(
        args.deployment_compatibility_registry,
    )
    migrations = _hash_directory("migrations/postgres", "*.sql")
    migration_rehearsal = _migration_rehearsal_record(args.migration_rehearsal, migrations)
    dependency_locks = _hash_paths(DEPENDENCY_LOCKFILES)
    build_inputs = _hash_paths(BUILD_INPUTS)
    image_digest = args.image_digest.strip() or _attested_image_digest(trusted_ci_attestation_payload)
    sbom = _sbom_record(args.sbom, image_digest)
    vulnerability_scan = _vulnerability_scan_record(args.vulnerability_scan, image_digest)
    build_command = args.build_command or _attested_build_command(trusted_ci_attestation_payload)
    checks = _checks(
        args=args,
        git=git,
        image_digest=image_digest,
        build_command=build_command,
        base_images=base_images,
        policies=policies,
        policy_lifecycle=policy_lifecycle,
        connector_certification=connector_certification,
        deployment_compatibility=deployment_compatibility,
        migrations=migrations,
        migration_rehearsal=migration_rehearsal,
        dependency_locks=dependency_locks,
        sbom=sbom,
        vulnerability_scan=vulnerability_scan,
        ci_attestation=ci_attestation,
    )
    missing = [name for name, passed in checks.items() if not passed]
    packet: dict[str, Any] = {
        "schema_version": "mesh.release_provenance.v1",
        "generated_at": _timestamp(),
        "status": "complete" if not missing else "incomplete",
        "missing": missing,
        "checks": checks,
        "git": git,
        "image": {
            "tag": args.image_tag,
            "digest": image_digest or None,
        },
        "base_images": base_images,
        "dependency_locks": dependency_locks,
        "build_inputs": build_inputs,
        "policies": {
            "count": len(policies),
            "hashes": policies,
            "combined_sha256": _combined_hash(policies),
            "lifecycle": policy_lifecycle,
        },
        "connectors": {
            "certification": connector_certification,
        },
        "deployment": {
            "compatibility": deployment_compatibility,
        },
        "migrations": {
            "directory": "migrations/postgres",
            "version": _migration_version(migrations),
            "hashes": migrations,
            "combined_sha256": _combined_hash(migrations),
            "rehearsal": migration_rehearsal,
        },
        "sbom": sbom,
        "vulnerability_scan": vulnerability_scan,
        "ci": _ci_record(ci_attestation),
        "build": {
            "command": build_command or None,
            "builder_identity": args.builder_identity or None,
            "allow_dirty": bool(args.allow_dirty),
        },
        "deployment_profile": {
            "environment": args.environment,
            "readiness_profile": args.readiness_profile,
        },
    }
    packet["packet_sha256"] = _payload_hash(packet)
    return packet


def _checks(
    *,
    args: argparse.Namespace,
    git: dict[str, Any],
    image_digest: str,
    build_command: str,
    base_images: list[dict[str, Any]],
    policies: list[dict[str, str]],
    policy_lifecycle: dict[str, Any],
    connector_certification: dict[str, Any],
    deployment_compatibility: dict[str, Any],
    migrations: list[dict[str, str]],
    migration_rehearsal: dict[str, Any],
    dependency_locks: list[dict[str, str]],
    sbom: dict[str, Any],
    vulnerability_scan: dict[str, Any],
    ci_attestation: dict[str, Any],
) -> dict[str, bool]:
    return {
        "git_commit": bool(git.get("commit")),
        "clean_git_tree": bool(args.allow_dirty or not git.get("dirty")),
        "image_tag": bool(args.image_tag),
        "image_digest": _valid_digest(image_digest),
        "base_image_digests": bool(base_images) and all(_valid_digest(str(item.get("digest") or "")) for item in base_images),
        "dependency_lockfiles": {item["path"] for item in dependency_locks} == set(DEPENDENCY_LOCKFILES),
        "policy_hashes": bool(policies),
        "policy_lifecycle_signed": policy_lifecycle.get("status") == "complete",
        "connector_certification_registry": connector_certification.get("status") == "complete",
        "deployment_compatibility_registry": deployment_compatibility.get("status") == "complete",
        "migration_version": bool(_migration_version(migrations)),
        "migration_rehearsal": migration_rehearsal.get("status") == "pass",
        "sbom_path": bool(sbom.get("exists") and sbom.get("valid")),
        "vulnerability_scan_path": bool(vulnerability_scan.get("exists") and vulnerability_scan.get("valid")),
        "ci_attestation": bool(ci_attestation.get("exists") and ci_attestation.get("valid")),
        "build_command": bool(build_command),
        "builder_identity": bool(args.builder_identity),
        "readiness_profile": bool(args.readiness_profile),
        "environment": bool(args.environment),
    }


def _read_policy_signing_key(args: argparse.Namespace) -> str:
    raw = (args.policy_signing_key or "").strip()
    if raw:
        return raw
    path_value = (args.policy_signing_key_path or "").strip()
    if not path_value:
        return ""
    path = Path(path_value)
    resolved = path if path.is_absolute() else REPO_ROOT / path
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError:
        return ""


def _git_snapshot() -> dict[str, Any]:
    status = _git(["status", "--porcelain"], strip=False)
    return {
        "commit": _git(["rev-parse", "--verify", "HEAD"]),
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(status.strip()),
        "dirty_files": [line[3:] for line in status.splitlines() if line.strip()],
    }


def _git(args: list[str], *, strip: bool = True) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip() if strip else result.stdout.rstrip("\n")


def _base_images(overrides: dict[str, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    known_stages: set[str] = set()
    for rel in DOCKERFILES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            parts = raw.strip().split()
            if not parts or parts[0].upper() != "FROM":
                continue
            image_index = 1
            while image_index < len(parts) and parts[image_index].startswith("--"):
                image_index += 1
            if image_index >= len(parts):
                continue
            image_ref = parts[image_index]
            alias = _from_alias(parts)
            if image_ref in known_stages:
                if alias:
                    known_stages.add(alias)
                continue
            image, digest = _split_digest(image_ref)
            digest = digest or overrides.get(image) or overrides.get(image_ref) or ""
            key = f"{image}@{digest or 'unpinned'}"
            if key not in seen:
                records.append(
                    {
                        "image": image,
                        "digest": digest or None,
                        "source": rel,
                        "line": line_number,
                        "pinned": _valid_digest(digest),
                    }
                )
                seen.add(key)
            if alias:
                known_stages.add(alias)
    return records


def _from_alias(parts: list[str]) -> str | None:
    for index, part in enumerate(parts):
        if part.upper() == "AS" and index + 1 < len(parts):
            return parts[index + 1]
    return None


def _split_digest(image_ref: str) -> tuple[str, str]:
    if "@sha256:" not in image_ref:
        return image_ref, ""
    image, digest = image_ref.split("@", 1)
    return image, digest


def _parse_base_digest_overrides(raw_items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in raw_items:
        if "=" not in raw:
            raise SystemExit(f"invalid --base-image-digest {raw!r}; expected IMAGE=sha256:...")
        image, digest = raw.split("=", 1)
        image = image.strip()
        digest = digest.strip()
        if not image or not _valid_digest(digest):
            raise SystemExit(f"invalid --base-image-digest {raw!r}; digest must be sha256:<64 hex>")
        parsed[image] = digest
    return parsed


def _hash_paths(paths: tuple[str, ...]) -> list[dict[str, str]]:
    records = []
    for rel in paths:
        path = REPO_ROOT / rel
        if path.exists():
            records.append({"path": rel, "sha256": _sha256(path)})
    return records


def _hash_directory(rel_dir: str, pattern: str) -> list[dict[str, str]]:
    directory = REPO_ROOT / rel_dir
    if not directory.exists():
        return []
    return [
        {"path": str(path.relative_to(REPO_ROOT)), "sha256": _sha256(path)}
        for path in sorted(directory.glob(pattern))
        if path.is_file()
    ]


def _migration_rehearsal_record(raw_path: str, migrations: list[dict[str, str]]) -> dict[str, Any]:
    from shared.mesh_runtime.migration_rehearsal import verify_migration_rehearsal

    artifact = _artifact_record(raw_path)
    verification = verify_migration_rehearsal(
        raw_path or None,
        expected_migration_version=_migration_version(migrations),
        expected_migration_combined_sha256=_combined_hash(migrations),
    )
    artifact.update(
        {
            "status": verification.get("status"),
            "valid": verification.get("status") == "pass",
            "schema_version": verification.get("schema_version"),
            "rehearsal_id": verification.get("rehearsal_id"),
            "migration_version": verification.get("migration_version"),
            "checks": verification.get("checks", {}),
            "missing": [
                name
                for name, passed in (verification.get("checks") or {}).items()
                if passed is not True
            ],
            "error": verification.get("error"),
        }
    )
    return artifact


def _artifact_record(raw_path: str) -> dict[str, Any]:
    if not raw_path:
        return {"path": None, "exists": False, "sha256": None}
    path = Path(raw_path)
    resolved = path if path.is_absolute() else REPO_ROOT / path
    exists = resolved.exists() and resolved.is_file()
    return {
        "path": raw_path,
        "exists": exists,
        "sha256": _sha256(resolved) if exists else None,
    }


def _ci_attestation_record(
    raw_path: str,
    payload: dict[str, Any],
    *,
    expected_git_commit: str,
) -> dict[str, Any]:
    record = _artifact_record(raw_path)
    schema_valid = payload.get("schema_version") == "mesh.ci_attestation.v1"
    attestation_hash = payload.get("attestation_sha256") if isinstance(payload.get("attestation_sha256"), str) else ""
    hash_valid = bool(attestation_hash and attestation_hash == _attestation_payload_hash(payload))
    passed_checks = _passed_ci_checks(payload)
    missing_checks = sorted(REQUIRED_CI_CHECKS.difference(passed_checks))
    provider = _string_field(payload, "provider")
    provider_valid = provider == REQUIRED_CI_ATTESTATION_PROVIDER
    sha = _string_field(payload, "sha")
    expected_sha = expected_git_commit.strip()
    sha_matches_git_commit = bool(sha and expected_sha and sha == expected_sha)
    missing_metadata = [
        field
        for field in REQUIRED_CI_ATTESTATION_FIELDS
        if not _string_field(payload, field)
    ]
    valid = bool(
        record.get("exists")
        and schema_valid
        and hash_valid
        and provider_valid
        and sha_matches_git_commit
        and not missing_metadata
        and not missing_checks
    )
    record.update(
        {
            "valid": valid,
            "schema_version": payload.get("schema_version") if isinstance(payload.get("schema_version"), str) else None,
            "provider": provider,
            "workflow": _string_field(payload, "workflow"),
            "job": _string_field(payload, "job"),
            "run_id": _string_field(payload, "run_id"),
            "sha": sha,
            "expected_sha": expected_sha or None,
            "hash_valid": hash_valid,
            "sha_matches_git_commit": sha_matches_git_commit,
            "passed_checks": sorted(passed_checks),
            "missing_checks": missing_checks,
            "missing": [] if valid else _missing_ci_attestation_fields(
                record,
                schema_valid,
                hash_valid,
                provider_valid,
                sha_matches_git_commit,
                missing_metadata,
                missing_checks,
            ),
        }
    )
    return record


def _string_field(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _passed_ci_checks(payload: dict[str, Any]) -> set[str]:
    raw_checks = payload.get("checks")
    if not isinstance(raw_checks, list):
        return set()
    passed: set[str] = set()
    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        status = item.get("status")
        if isinstance(name, str) and status == "passed":
            passed.add(name)
    return passed


def _missing_ci_attestation_fields(
    record: dict[str, Any],
    schema_valid: bool,
    hash_valid: bool,
    provider_valid: bool,
    sha_matches_git_commit: bool,
    missing_metadata: list[str],
    missing_checks: list[str],
) -> list[str]:
    missing: list[str] = []
    if not record.get("exists"):
        missing.append("path")
    if not schema_valid:
        missing.append("schema_version:mesh.ci_attestation.v1")
    if not hash_valid:
        missing.append("attestation_sha256")
    if not provider_valid:
        missing.append(REQUIRED_CI_ATTESTATION_PROVIDER_REASON)
    missing.extend(missing_metadata)
    if "sha" not in missing_metadata and not sha_matches_git_commit:
        missing.append("sha_matches_git_commit")
    missing.extend(f"check:{name}" for name in missing_checks)
    return missing


def _attestation_payload_hash(payload: dict[str, Any]) -> str:
    unsigned_payload = dict(payload)
    unsigned_payload.pop("attestation_sha256", None)
    return _payload_hash(unsigned_payload)


def _sbom_record(raw_path: str, image_digest: str) -> dict[str, Any]:
    record = _artifact_record(raw_path)
    payload = _json_artifact_payload(raw_path)
    format_name = payload.get("bomFormat") if isinstance(payload.get("bomFormat"), str) else None
    components = payload.get("components")
    metadata = payload.get("metadata")
    rehearsal = _is_rehearsal_sbom(payload)
    artifact_image_digest = _artifact_image_digest(payload)
    image_digest_matches = _image_digest_matches(artifact_image_digest, image_digest)
    valid = bool(record.get("exists") and format_name == "CycloneDX" and not rehearsal and image_digest_matches)
    record.update(
        {
            "valid": valid,
            "format": format_name,
            "rehearsal": rehearsal,
            "image_digest": artifact_image_digest,
            "image_digest_matches": image_digest_matches,
            "component_count": len(components) if isinstance(components, list) else None,
            "metadata_present": isinstance(metadata, dict),
            "missing": [] if valid else _missing_sbom_fields(record, format_name, rehearsal, image_digest_matches),
        }
    )
    return record


def _artifact_image_digest(payload: dict[str, Any]) -> str | None:
    for key in ("image_digest", "subject_digest"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    image = payload.get("image")
    if isinstance(image, dict):
        digest = image.get("digest")
        if isinstance(digest, str) and digest.strip():
            return digest.strip()
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        properties = metadata.get("properties")
        if isinstance(properties, list):
            for item in properties:
                if isinstance(item, dict) and item.get("name") in {"mesh:image_digest", "image_digest"}:
                    value = item.get("value")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        component = metadata.get("component")
        if isinstance(component, dict):
            hashes = component.get("hashes")
            if isinstance(hashes, list):
                for item in hashes:
                    if not isinstance(item, dict):
                        continue
                    alg = str(item.get("alg") or item.get("algorithm") or "").lower()
                    content = item.get("content")
                    if alg in {"sha-256", "sha256"} and isinstance(content, str) and len(content.strip()) == 64:
                        return f"sha256:{content.strip()}"
    return None


def _image_digest_matches(artifact_image_digest: str | None, release_image_digest: str) -> bool:
    if not _valid_digest(release_image_digest):
        return True
    return artifact_image_digest == release_image_digest


def _is_rehearsal_sbom(payload: dict[str, Any]) -> bool:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    tools = metadata.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and tool.get("name") == REHEARSAL_SCANNER:
                return True
    return False


def _missing_sbom_fields(
    record: dict[str, Any],
    format_name: str | None,
    rehearsal: bool,
    image_digest_matches: bool,
) -> list[str]:
    missing: list[str] = []
    if not record.get("exists"):
        missing.append("path")
    if format_name != "CycloneDX":
        missing.append("bomFormat:CycloneDX")
    if rehearsal:
        missing.append("real_release_image_sbom")
    if not image_digest_matches:
        missing.append("release_image_digest_match")
    return missing


def _vulnerability_scan_record(raw_path: str, image_digest: str) -> dict[str, Any]:
    record = _artifact_record(raw_path)
    payload = _json_artifact_payload(raw_path)
    scanner = payload.get("scanner") if isinstance(payload.get("scanner"), str) else None
    rehearsal = _is_rehearsal_scan(payload, scanner)
    artifact_image_digest = _artifact_image_digest(payload)
    image_digest_matches = _image_digest_matches(artifact_image_digest, image_digest)
    findings = _scan_findings(payload)
    blocking_findings = [
        finding
        for finding in findings
        if _severity_rank(_finding_severity(finding)) >= _severity_rank("high")
        and not _valid_accepted_exception(finding)
    ]
    accepted_blocking_findings = [
        finding
        for finding in findings
        if _severity_rank(_finding_severity(finding)) >= _severity_rank("high")
        and _valid_accepted_exception(finding)
    ]
    valid = bool(record.get("exists") and scanner and not blocking_findings and not rehearsal and image_digest_matches)
    record.update(
        {
            "valid": valid,
            "scanner": scanner,
            "rehearsal": rehearsal,
            "image_digest": artifact_image_digest,
            "image_digest_matches": image_digest_matches,
            "finding_count": len(findings),
            "blocking_finding_count": len(blocking_findings),
            "accepted_exception_count": len(accepted_blocking_findings),
            "missing": [] if valid else _missing_vulnerability_scan_fields(
                record,
                scanner,
                blocking_findings,
                rehearsal,
                image_digest_matches,
            ),
        }
    )
    return record


def _valid_accepted_exception(finding: dict[str, Any]) -> bool:
    exception = finding.get("accepted_exception")
    if not isinstance(exception, dict):
        return False
    required = ("owner", "expires_at", "decision", "reason", "compensating_controls")
    for key in required:
        if key == "compensating_controls":
            controls = exception.get(key)
            if not isinstance(controls, list) or not all(isinstance(item, str) and item.strip() for item in controls):
                return False
            continue
        if not isinstance(exception.get(key), str) or not exception[key].strip():
            return False
    try:
        expires_at = time.strptime(str(exception["expires_at"]), "%Y-%m-%d")
    except ValueError:
        return False
    today = time.strptime(time.strftime("%Y-%m-%d", time.gmtime()), "%Y-%m-%d")
    return expires_at >= today


def _is_rehearsal_scan(payload: dict[str, Any], scanner: str | None) -> bool:
    if scanner == REHEARSAL_SCANNER:
        return True
    return payload.get("schema_version") == "mesh.raw_vulnerability_scan_rehearsal.v1"


def _scan_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("findings", "vulnerabilities", "results"):
        raw_findings = payload.get(key)
        if isinstance(raw_findings, list):
            return [item for item in raw_findings if isinstance(item, dict)]
    return []


def _finding_severity(finding: dict[str, Any]) -> str:
    severity = finding.get("severity")
    if isinstance(severity, str):
        return severity
    ratings = finding.get("ratings")
    if isinstance(ratings, list):
        for rating in ratings:
            if isinstance(rating, dict):
                rating_severity = rating.get("severity")
                if isinstance(rating_severity, str):
                    return rating_severity
    return ""


def _severity_rank(severity: str) -> int:
    normalized = severity.strip().lower()
    if normalized in {"critical", "crit"}:
        return 4
    if normalized == "high":
        return 3
    if normalized == "medium":
        return 2
    if normalized == "low":
        return 1
    return 0


def _missing_vulnerability_scan_fields(
    record: dict[str, Any],
    scanner: str | None,
    blocking_findings: list[dict[str, Any]],
    rehearsal: bool,
    image_digest_matches: bool,
) -> list[str]:
    missing: list[str] = []
    if not record.get("exists"):
        missing.append("path")
    if not scanner:
        missing.append("scanner")
    if blocking_findings:
        missing.append("no_high_or_critical_findings")
    if rehearsal:
        missing.append("real_release_image_vulnerability_scan")
    if not image_digest_matches:
        missing.append("release_image_digest_match")
    return missing


def _json_artifact_payload(raw_path: str) -> dict[str, Any]:
    if not raw_path:
        return {}
    path = Path(raw_path)
    resolved = path if path.is_absolute() else REPO_ROOT / path
    if not resolved.exists() or not resolved.is_file():
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _attested_image_digest(payload: dict[str, Any]) -> str:
    image = payload.get("image")
    if not isinstance(image, dict):
        return ""
    digest = image.get("digest")
    return digest.strip() if isinstance(digest, str) else ""


def _attested_build_command(payload: dict[str, Any]) -> str:
    build = payload.get("build")
    if not isinstance(build, dict):
        return ""
    command = build.get("command")
    return command.strip() if isinstance(command, str) else ""


def _attested_base_image_digests(payload: dict[str, Any]) -> dict[str, str]:
    build = payload.get("build")
    if not isinstance(build, dict):
        return {}
    raw_base_images = build.get("base_images")
    if not isinstance(raw_base_images, list):
        return {}
    digests: dict[str, str] = {}
    for item in raw_base_images:
        if not isinstance(item, dict):
            continue
        image = item.get("image")
        digest = item.get("digest")
        if isinstance(image, str) and image.strip() and isinstance(digest, str) and _valid_digest(digest.strip()):
            digests[image.strip()] = digest.strip()
    return digests


def _ci_record(attestation: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else os.getenv("MESH_CI_PROVIDER") or None,
        "workflow": os.getenv("GITHUB_WORKFLOW") or None,
        "run_id": os.getenv("GITHUB_RUN_ID") or None,
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT") or None,
        "job": os.getenv("GITHUB_JOB") or None,
        "ref": os.getenv("GITHUB_REF") or None,
        "sha": os.getenv("GITHUB_SHA") or None,
        "actor": os.getenv("GITHUB_ACTOR") or None,
        "repository": os.getenv("GITHUB_REPOSITORY") or None,
        "server_url": os.getenv("GITHUB_SERVER_URL") or None,
        "attestation": attestation,
    }


def _migration_version(records: list[dict[str, str]]) -> str | None:
    if not records:
        return None
    latest = sorted(records, key=lambda item: item["path"])[-1]["path"]
    return Path(latest).stem


def _combined_hash(records: list[dict[str, str]]) -> str | None:
    if not records:
        return None
    digest = hashlib.sha256()
    for record in records:
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_digest(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    tail = value[len("sha256:") :]
    return len(tail) == 64 and all(char in "0123456789abcdefABCDEF" for char in tail)


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    sys.exit(main())
