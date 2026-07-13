"""Role-bound release artifact contract for the repo-patch beta service images."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .schema_validation import SchemaValidationError, validate_payload
from .release_vulnerability_evidence import (
    SCHEMA_VERSION as RELEASE_VULNERABILITY_EVIDENCE_VERSION,
    classify_supported_grype_match,
    file_sha256,
    grype_match_sha256,
    valid_verified_vex_summary,
    validate_release_vulnerability_evidence,
)


REPO_PATCH_SERVICE_IMAGE_BUNDLE_VERSION = "mesh.repo_patch_service_image_bundle.v1"
REPO_PATCH_SERVICE_IMAGE_BUNDLE_STATE_SLICE = "mesh.repo_patch_service_image_bundle.v1"
REPO_PATCH_SERVICE_IMAGE_BUNDLE_SCHEMA = "repo-patch-service-image-bundle.schema.json"
REPO_PATCH_VERIFIER_RECEIPT_SIGNING_PROFILE = "mesh-repo-patch-verifier-receipt-ed25519-v2"
REQUIRED_CI_ATTESTATION_CHECKS = frozenset(
    {
        "pnpm-lint",
        "image-source-binding",
        "prepublish-image-assurance",
        "published-image-assurance",
        "github-oidc-provenance",
    }
)

ROLE_ORDER = (
    "mesh_control_plane",
    "repo_patch_authority",
    "repo_patch_verifier",
)
ROLE_DOCKERFILES = {
    "mesh_control_plane": "Dockerfile",
    "repo_patch_authority": "docker/repo-patch-authority.Dockerfile",
    "repo_patch_verifier": "docker/repo-patch-verifier.Dockerfile",
}
ROLE_INPUT_FIELDS = frozenset(
    {
        "image_tag",
        "image_digest",
        "sbom_path",
        "raw_vulnerability_scan_path",
        "vulnerability_scan_path",
        "vulnerability_evidence_path",
        "ci_attestation_path",
    }
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class RepoPatchServiceImageBundleError(ValueError):
    """Raised when role-level release evidence is incomplete or inconsistent."""


def build_repo_patch_service_image_bundle(
    *,
    artifact_root: str | Path,
    git_commit: str,
    role_inputs: Mapping[str, Mapping[str, str]],
    verifier_sandbox_profile_digest: str,
    verifier_key_id: str,
    verifier_public_key_path: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a complete three-role bundle from files rooted under ``artifact_root``."""

    root = _require_artifact_root(artifact_root)
    commit = _require_git_commit(git_commit)
    if set(role_inputs) != set(ROLE_ORDER):
        raise RepoPatchServiceImageBundleError("role inputs must contain exactly the three release roles")
    if not _SHA256_DIGEST.fullmatch(verifier_sandbox_profile_digest):
        raise RepoPatchServiceImageBundleError("verifier sandbox profile digest must be sha256:<64 lowercase hex>")
    if not _KEY_ID.fullmatch(verifier_key_id):
        raise RepoPatchServiceImageBundleError("verifier key id is invalid")
    public_key_sha256 = ed25519_public_key_sha256(verifier_public_key_path)

    roles: dict[str, dict[str, Any]] = {}
    expected_role_images: dict[str, dict[str, str]] = {}
    for role in ROLE_ORDER:
        role_input = role_inputs[role]
        missing = ROLE_INPUT_FIELDS - set(role_input)
        unknown = set(role_input) - ROLE_INPUT_FIELDS
        if missing or unknown:
            raise RepoPatchServiceImageBundleError(
                f"{role} input fields invalid: missing={sorted(missing)!r}, unknown={sorted(unknown)!r}"
            )

        image_tag = str(role_input["image_tag"]).strip()
        image_digest = str(role_input["image_digest"]).strip()
        if not _immutable_image_ref_matches(image_tag, image_digest):
            raise RepoPatchServiceImageBundleError(
                f"{role} image tag must be an immutable @sha256 reference matching image_digest"
            )

        dockerfile_path = ROLE_DOCKERFILES[role]
        dockerfile = _resolve_recorded_file(root, dockerfile_path)
        sbom_path = _require_portable_path(str(role_input["sbom_path"]))
        raw_scan_path = _require_portable_path(str(role_input["raw_vulnerability_scan_path"]))
        scan_path = _require_portable_path(str(role_input["vulnerability_scan_path"]))
        evidence_path = _require_portable_path(str(role_input["vulnerability_evidence_path"]))
        ci_path = _require_portable_path(str(role_input["ci_attestation_path"]))
        sbom = _resolve_recorded_file(root, sbom_path)
        raw_scan = _resolve_recorded_file(root, raw_scan_path)
        scan = _resolve_recorded_file(root, scan_path)
        evidence = _resolve_recorded_file(root, evidence_path)
        ci_attestation = _resolve_recorded_file(root, ci_path)

        record: dict[str, Any] = {
            "role": role,
            "dockerfile": {"path": dockerfile_path, "sha256": _file_sha256(dockerfile)},
            "image": {"tag": image_tag, "digest": image_digest},
            "sbom": {"path": sbom_path, "sha256": _file_sha256(sbom)},
            "raw_vulnerability_scan": {
                "path": raw_scan_path,
                "sha256": _file_sha256(raw_scan),
            },
            "vulnerability_scan": {
                "path": scan_path,
                "sha256": _file_sha256(scan),
                "status": "pass",
            },
            "vulnerability_evidence": {
                "path": evidence_path,
                "sha256": _file_sha256(evidence),
            },
            "ci_attestation": {"path": ci_path, "sha256": _file_sha256(ci_attestation)},
        }
        if role == "repo_patch_verifier":
            record["verifier_policy"] = {
                "sandbox_profile_digest": verifier_sandbox_profile_digest,
                "receipt_signing_profile": REPO_PATCH_VERIFIER_RECEIPT_SIGNING_PROFILE,
                "signature_algorithm": "ed25519",
                "key_id": verifier_key_id,
                "public_key_sha256": public_key_sha256,
            }
        roles[role] = record
        expected_role_images[role] = {"tag": image_tag, "digest": image_digest}

    packet: dict[str, Any] = {
        "schema_version": REPO_PATCH_SERVICE_IMAGE_BUNDLE_VERSION,
        "state_slice": REPO_PATCH_SERVICE_IMAGE_BUNDLE_STATE_SLICE,
        "generated_at": generated_at or _timestamp(),
        "git_commit": commit,
        "roles": roles,
    }
    packet["bundle_sha256"] = repo_patch_service_image_bundle_sha256(packet)
    verification = verify_repo_patch_service_image_bundle(
        packet,
        artifact_root=root,
        expected_git_commit=commit,
        expected_role_images=expected_role_images,
        expected_verifier_sandbox_profile_digest=verifier_sandbox_profile_digest,
        expected_verifier_key_id=verifier_key_id,
        expected_verifier_public_key_path=verifier_public_key_path,
    )
    if verification["status"] != "pass":
        raise RepoPatchServiceImageBundleError(
            "repo-patch service image bundle incomplete: " + ", ".join(verification["missing"])
        )
    return packet


def verify_repo_patch_service_image_bundle(
    packet: Mapping[str, Any],
    *,
    artifact_root: str | Path,
    expected_git_commit: str,
    expected_role_images: Mapping[str, Mapping[str, str]],
    expected_verifier_sandbox_profile_digest: str,
    expected_verifier_key_id: str,
    expected_verifier_public_key_path: str | Path,
) -> dict[str, Any]:
    """Verify the bundle against filesystem artifacts and external deployment policy."""

    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}

    def check(name: str, operation: Callable[[], bool]) -> None:
        try:
            checks[name] = bool(operation())
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            checks[name] = False
            errors[name] = str(exc)

    def check_path_binding(name: str, path: Path | None, operation: Callable[[Path], bool]) -> None:
        if path is None:
            checks[name] = False
            return
        try:
            checks[name] = bool(operation(path))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            checks[name] = False
            errors[name] = str(exc)

    raw_packet = dict(packet) if isinstance(packet, Mapping) else {}
    check("schema_valid", lambda: _schema_valid(raw_packet))
    check(
        "schema_version",
        lambda: raw_packet.get("schema_version") == REPO_PATCH_SERVICE_IMAGE_BUNDLE_VERSION,
    )
    check(
        "state_slice",
        lambda: raw_packet.get("state_slice") == REPO_PATCH_SERVICE_IMAGE_BUNDLE_STATE_SLICE,
    )
    check("generated_at", lambda: _valid_timestamp(raw_packet.get("generated_at")))
    check("git_commit_format", lambda: bool(_GIT_COMMIT.fullmatch(str(raw_packet.get("git_commit") or ""))))
    check("expected_git_commit_format", lambda: bool(_GIT_COMMIT.fullmatch(expected_git_commit)))
    check("git_commit_expected", lambda: raw_packet.get("git_commit") == expected_git_commit)
    check("bundle_sha256", lambda: _bundle_hash_matches(raw_packet))

    root: Path | None = None
    try:
        root = _require_artifact_root(artifact_root)
        checks["artifact_root"] = True
    except RepoPatchServiceImageBundleError as exc:
        checks["artifact_root"] = False
        errors["artifact_root"] = str(exc)

    roles_value = raw_packet.get("roles")
    roles = roles_value if isinstance(roles_value, dict) else {}
    checks["roles_exact"] = set(roles) == set(ROLE_ORDER) and len(roles) == len(ROLE_ORDER)
    checks["expected_role_images_exact"] = (
        set(expected_role_images) == set(ROLE_ORDER) and len(expected_role_images) == len(ROLE_ORDER)
    )

    for role in ROLE_ORDER:
        prefix = f"roles.{role}"
        role_value = roles.get(role)
        record = role_value if isinstance(role_value, dict) else {}
        checks[f"{prefix}.present"] = bool(record)
        checks[f"{prefix}.role"] = record.get("role") == role

        dockerfile_value = record.get("dockerfile")
        dockerfile = dockerfile_value if isinstance(dockerfile_value, dict) else {}
        checks[f"{prefix}.dockerfile.path_expected"] = dockerfile.get("path") == ROLE_DOCKERFILES[role]

        image_value = record.get("image")
        image = image_value if isinstance(image_value, dict) else {}
        image_tag = str(image.get("tag") or "")
        image_digest = str(image.get("digest") or "")
        checks[f"{prefix}.image.digest"] = bool(_SHA256_DIGEST.fullmatch(image_digest))
        checks[f"{prefix}.image.immutable_ref"] = _immutable_image_ref_matches(image_tag, image_digest)
        expected_image_value = expected_role_images.get(role)
        expected_image = expected_image_value if isinstance(expected_image_value, Mapping) else {}
        checks[f"{prefix}.image.expected_tag"] = image_tag == expected_image.get("tag")
        checks[f"{prefix}.image.expected_digest"] = image_digest == expected_image.get("digest")

        if root is not None:
            dockerfile_path = _verify_recorded_file(
                checks,
                errors,
                f"{prefix}.dockerfile",
                root,
                dockerfile,
            )
            sbom_value = record.get("sbom")
            sbom_record = sbom_value if isinstance(sbom_value, dict) else {}
            sbom_path = _verify_recorded_file(checks, errors, f"{prefix}.sbom", root, sbom_record)
            scan_value = record.get("vulnerability_scan")
            scan_record = scan_value if isinstance(scan_value, dict) else {}
            raw_scan_value = record.get("raw_vulnerability_scan")
            raw_scan_record = raw_scan_value if isinstance(raw_scan_value, dict) else {}
            raw_scan_path = _verify_recorded_file(
                checks,
                errors,
                f"{prefix}.raw_vulnerability_scan",
                root,
                raw_scan_record,
            )
            scan_path = _verify_recorded_file(
                checks,
                errors,
                f"{prefix}.vulnerability_scan",
                root,
                scan_record,
            )
            evidence_value = record.get("vulnerability_evidence")
            evidence_record = evidence_value if isinstance(evidence_value, dict) else {}
            evidence_path = _verify_recorded_file(
                checks,
                errors,
                f"{prefix}.vulnerability_evidence",
                root,
                evidence_record,
            )
            ci_value = record.get("ci_attestation")
            ci_record = ci_value if isinstance(ci_value, dict) else {}
            ci_path = _verify_recorded_file(
                checks,
                errors,
                f"{prefix}.ci_attestation",
                root,
                ci_record,
            )
            checks[f"{prefix}.dockerfile.bound"] = bool(
                dockerfile_path and dockerfile_path.is_file() and dockerfile.get("path") == ROLE_DOCKERFILES[role]
            )
            check_path_binding(
                f"{prefix}.sbom.binding",
                sbom_path,
                lambda path: _sbom_bound(path, image_digest),
            )
            check_path_binding(
                f"{prefix}.vulnerability_scan.binding",
                scan_path,
                lambda path: _scan_bound(path, image_digest),
            )
            if raw_scan_path is None or scan_path is None or evidence_path is None:
                checks[f"{prefix}.vulnerability_evidence.binding"] = False
            else:
                check(
                    f"{prefix}.vulnerability_evidence.binding",
                    lambda: _vulnerability_evidence_bound(
                        raw_scan_path,
                        scan_path,
                        evidence_path,
                        image_digest,
                    ),
                )
            checks[f"{prefix}.vulnerability_scan.status"] = scan_record.get("status") == "pass"
            check_path_binding(
                f"{prefix}.ci_attestation.binding",
                ci_path,
                lambda path: _ci_attestation_bound(
                    path,
                    str(raw_packet.get("git_commit") or ""),
                    image_tag,
                    image_digest,
                    ROLE_DOCKERFILES[role],
                ),
            )

        if role == "repo_patch_verifier":
            policy_value = record.get("verifier_policy")
            policy = policy_value if isinstance(policy_value, dict) else {}
            checks[f"{prefix}.verifier_policy.present"] = bool(policy)
            checks[f"{prefix}.verifier_policy.sandbox_digest"] = bool(
                _SHA256_DIGEST.fullmatch(str(policy.get("sandbox_profile_digest") or ""))
            )
            checks[f"{prefix}.verifier_policy.sandbox_expected"] = (
                policy.get("sandbox_profile_digest") == expected_verifier_sandbox_profile_digest
            )
            checks[f"{prefix}.verifier_policy.signing_profile"] = (
                policy.get("receipt_signing_profile") == REPO_PATCH_VERIFIER_RECEIPT_SIGNING_PROFILE
            )
            checks[f"{prefix}.verifier_policy.algorithm"] = policy.get("signature_algorithm") == "ed25519"
            checks[f"{prefix}.verifier_policy.key_id_format"] = bool(
                _KEY_ID.fullmatch(str(policy.get("key_id") or ""))
            )
            checks[f"{prefix}.verifier_policy.key_id_expected"] = policy.get("key_id") == expected_verifier_key_id
            check(
                f"{prefix}.verifier_policy.public_key_expected",
                lambda: policy.get("public_key_sha256")
                == ed25519_public_key_sha256(expected_verifier_public_key_path),
            )
            checks[f"{prefix}.verifier_policy.public_key_sha256"] = bool(
                _SHA256_HEX.fullmatch(str(policy.get("public_key_sha256") or ""))
            )

    missing = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "mesh.repo_patch_service_image_bundle_verification.v1",
        "state_slice": REPO_PATCH_SERVICE_IMAGE_BUNDLE_STATE_SLICE,
        "status": "pass" if not missing else "fail",
        "git_commit": raw_packet.get("git_commit"),
        "bundle_sha256": raw_packet.get("bundle_sha256"),
        "checks": checks,
        "errors": errors,
        "missing": missing,
    }


def repo_patch_service_image_bundle_sha256(packet: Mapping[str, Any]) -> str:
    """Hash the canonical bundle payload, excluding its self-hash field."""

    payload = dict(packet)
    payload.pop("bundle_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ed25519_public_key_sha256(path: str | Path) -> str:
    """Hash the canonical SubjectPublicKeyInfo DER for an Ed25519 public key."""

    public_key_path = Path(path)
    if not public_key_path.is_file() or public_key_path.is_symlink():
        raise RepoPatchServiceImageBundleError("verifier public key must be a regular non-symlink file")
    try:
        key = serialization.load_pem_public_key(public_key_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RepoPatchServiceImageBundleError("verifier public key is not valid PEM") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise RepoPatchServiceImageBundleError("verifier public key must be Ed25519")
    der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def _schema_valid(packet: dict[str, Any]) -> bool:
    try:
        validate_payload(REPO_PATCH_SERVICE_IMAGE_BUNDLE_SCHEMA, packet)
    except SchemaValidationError:
        return False
    return True


def _verify_recorded_file(
    checks: dict[str, bool],
    errors: dict[str, str],
    prefix: str,
    root: Path,
    record: Mapping[str, Any],
) -> Path | None:
    raw_path = str(record.get("path") or "")
    raw_sha256 = str(record.get("sha256") or "")
    try:
        portable = _require_portable_path(raw_path)
        checks[f"{prefix}.path_portable"] = True
    except RepoPatchServiceImageBundleError as exc:
        checks[f"{prefix}.path_portable"] = False
        checks[f"{prefix}.exists"] = False
        checks[f"{prefix}.sha256"] = False
        errors[f"{prefix}.path_portable"] = str(exc)
        return None
    try:
        path = _resolve_recorded_file(root, portable)
        checks[f"{prefix}.exists"] = True
    except RepoPatchServiceImageBundleError as exc:
        checks[f"{prefix}.exists"] = False
        checks[f"{prefix}.sha256"] = False
        errors[f"{prefix}.exists"] = str(exc)
        return None
    checks[f"{prefix}.sha256"] = bool(_SHA256_HEX.fullmatch(raw_sha256)) and _file_sha256(path) == raw_sha256
    return path


def _sbom_bound(path: Path, image_digest: str) -> bool:
    payload = _load_json_object(path)
    metadata = payload.get("metadata")
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    return (
        payload.get("bomFormat") == "CycloneDX"
        and isinstance(properties, list)
        and any(
            isinstance(item, dict)
            and item.get("name") == "mesh:image_digest"
            and item.get("value") == image_digest
            for item in properties
        )
    )


def _scan_bound(path: Path, image_digest: str) -> bool:
    payload = _load_json_object(path)
    findings = payload.get("findings")
    if not isinstance(findings, list) or not all(isinstance(item, dict) for item in findings):
        return False
    blocking = [item for item in findings if _severity_rank(str(item.get("severity") or "")) >= 3]
    accepted = [item for item in blocking if _valid_accepted_exception(item)]
    verified = [
        item
        for item in blocking
        if valid_verified_vex_summary(
            item.get("verified_vex"),
            finding=item,
            image_digest=image_digest,
        )
    ]
    if any(_valid_accepted_exception(item) and item in verified for item in blocking):
        return False
    unaccepted = [item for item in blocking if item not in accepted and item not in verified]
    return (
        payload.get("schema_version") == "mesh.normalized_vulnerability_scan.v1"
        and payload.get("image_digest") == image_digest
        and isinstance(payload.get("scanner"), str)
        and bool(str(payload.get("scanner") or "").strip())
        and payload.get("blocking_finding_count") == len(blocking)
        and payload.get("accepted_exception_count") == len(accepted)
        and payload.get("verified_vex_count") == len(verified)
        and payload.get("unaccepted_blocking_finding_count") == len(unaccepted) == 0
    )


def _vulnerability_evidence_bound(
    raw_scan_path: Path,
    normalized_scan_path: Path,
    evidence_path: Path,
    image_digest: str,
) -> bool:
    raw_scan = _load_json_object(raw_scan_path)
    normalized_scan = _load_json_object(normalized_scan_path)
    evidence = _load_json_object(evidence_path)
    raw_scan_sha256 = file_sha256(raw_scan_path)
    records = validate_release_vulnerability_evidence(
        evidence,
        image_digest=image_digest,
        raw_scan_sha256=raw_scan_sha256,
    )
    matches = raw_scan.get("matches")
    if not isinstance(matches, list):
        return False
    supported_matches = {
        grype_match_sha256(match): (match, classify_supported_grype_match(match))
        for match in matches
        if isinstance(match, dict) and classify_supported_grype_match(match)
    }
    for record in records:
        match_value = supported_matches.get(str(record.get("raw_match_sha256") or ""))
        if match_value is None:
            return False
        match, profile = match_value
        vulnerability = match.get("vulnerability")
        artifact = match.get("artifact")
        if not isinstance(vulnerability, dict) or not isinstance(artifact, dict):
            return False
        if (
            profile != record.get("profile")
            or vulnerability.get("id") != record.get("vulnerability_id")
            or artifact.get("name") != record.get("package")
            or artifact.get("version") != record.get("version")
        ):
            return False

    findings = normalized_scan.get("findings")
    if not isinstance(findings, list):
        return False
    verified_fingerprints = {
        str(item.get("raw_match_sha256") or "")
        for item in findings
        if isinstance(item, dict)
        and valid_verified_vex_summary(
            item.get("verified_vex"),
            finding=item,
            image_digest=image_digest,
        )
    }
    record_fingerprints = {str(record.get("raw_match_sha256") or "") for record in records}
    summary = normalized_scan.get("vulnerability_evidence")
    return (
        verified_fingerprints == record_fingerprints
        and isinstance(summary, dict)
        and summary.get("schema_version") == RELEASE_VULNERABILITY_EVIDENCE_VERSION
        and summary.get("image_digest") == image_digest
        and summary.get("raw_scan_sha256") == raw_scan_sha256
        and summary.get("record_count") == len(records)
    )


def _valid_accepted_exception(finding: Mapping[str, Any]) -> bool:
    exception = finding.get("accepted_exception")
    if not isinstance(exception, dict):
        return False
    for key in ("owner", "decision", "reason"):
        if not isinstance(exception.get(key), str) or not str(exception[key]).strip():
            return False
    controls = exception.get("compensating_controls")
    if not isinstance(controls, list) or not controls or not all(
        isinstance(control, str) and control.strip() for control in controls
    ):
        return False
    try:
        expires_at = time.strptime(str(exception.get("expires_at") or ""), "%Y-%m-%d")
    except ValueError:
        return False
    today = time.strptime(time.strftime("%Y-%m-%d", time.gmtime()), "%Y-%m-%d")
    return expires_at >= today


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


def _ci_attestation_bound(
    path: Path,
    git_commit: str,
    image_tag: str,
    image_digest: str,
    dockerfile_path: str,
) -> bool:
    payload = _load_json_object(path)
    image_value = payload.get("image")
    image: dict[str, Any] = image_value if isinstance(image_value, dict) else {}
    build_value = payload.get("build")
    build: dict[str, Any] = build_value if isinstance(build_value, dict) else {}
    checks = payload.get("checks")
    attestation_sha256 = str(payload.get("attestation_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("attestation_sha256", None)
    return (
        payload.get("schema_version") == "mesh.ci_attestation.v1"
        and payload.get("provider") == "github-actions"
        and payload.get("sha") == git_commit
        and payload.get("run_sha") == git_commit
        and image.get("tag") == image_tag
        and image.get("digest") == image_digest
        and _SHA256_HEX.fullmatch(attestation_sha256) is not None
        and _canonical_payload_sha256(unsigned) == attestation_sha256
        and _ci_checks_bound(checks)
        and _build_command_binds_source(
            str(build.get("command") or ""),
            dockerfile_path=dockerfile_path,
            image_tag=image_tag,
            git_commit=git_commit,
        )
    )


def _ci_checks_bound(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    statuses: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            return False
        name = item.get("name")
        status = item.get("status")
        if not isinstance(name, str) or not name or name in statuses or status != "passed":
            return False
        statuses[name] = status
    return REQUIRED_CI_ATTESTATION_CHECKS.issubset(statuses)


def _build_command_binds_source(
    command: str,
    *,
    dockerfile_path: str,
    image_tag: str,
    git_commit: str,
) -> bool:
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if arguments[:2] != ["docker", "build"] or "--pull" not in arguments:
        return False
    expected_build_tag = f"{image_tag.rsplit('@', 1)[0]}:sha-{git_commit}"
    required_build_args = {
        f"MESH_BUILD_VERSION=sha-{git_commit}",
        f"MESH_BUILD_COMMIT={git_commit}",
    }
    observed_build_args: set[str] = set()
    dockerfile_bound = False
    tag_bound = False
    for index, argument in enumerate(arguments):
        if argument in {"-f", "--file"} and index + 1 < len(arguments):
            if arguments[index + 1] == dockerfile_path:
                dockerfile_bound = True
        if argument == f"--file={dockerfile_path}" or argument == f"-f{dockerfile_path}":
            dockerfile_bound = True
        if argument in {"-t", "--tag"} and index + 1 < len(arguments):
            tag_bound = arguments[index + 1] == expected_build_tag
        if argument == f"--tag={expected_build_tag}" or argument == f"-t{expected_build_tag}":
            tag_bound = True
        if argument == "--build-arg" and index + 1 < len(arguments):
            observed_build_args.add(arguments[index + 1])
        if argument.startswith("--build-arg="):
            observed_build_args.add(argument.split("=", 1)[1])
    return dockerfile_bound and tag_bound and required_build_args.issubset(observed_build_args)


def _require_artifact_root(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_dir() or root.is_symlink():
        raise RepoPatchServiceImageBundleError("artifact root must be a non-symlink directory")
    return root.resolve(strict=True)


def _require_portable_path(value: str) -> str:
    raw = value.strip()
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or path.is_absolute()
        or raw != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RepoPatchServiceImageBundleError(f"artifact path is not portable: {value!r}")
    return raw


def _resolve_recorded_file(root: Path, recorded_path: str) -> Path:
    portable = _require_portable_path(recorded_path)
    candidate = root
    for part in PurePosixPath(portable).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise RepoPatchServiceImageBundleError(f"artifact path traverses a symlink: {recorded_path!r}")
    if not candidate.is_file():
        raise RepoPatchServiceImageBundleError(f"artifact file is missing: {recorded_path!r}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RepoPatchServiceImageBundleError(f"artifact path escapes root: {recorded_path!r}") from exc
    return resolved


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _immutable_image_ref_matches(image_tag: str, image_digest: str) -> bool:
    if not _SHA256_DIGEST.fullmatch(image_digest) or image_tag.count("@") != 1:
        return False
    repository, reference_digest = image_tag.rsplit("@", 1)
    return bool(repository) and not any(char.isspace() for char in repository) and reference_digest == image_digest


def _bundle_hash_matches(packet: Mapping[str, Any]) -> bool:
    expected = str(packet.get("bundle_sha256") or "")
    return bool(_SHA256_HEX.fullmatch(expected)) and expected == repo_patch_service_image_bundle_sha256(packet)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_git_commit(value: str) -> str:
    commit = value.strip()
    if not _GIT_COMMIT.fullmatch(commit):
        raise RepoPatchServiceImageBundleError("git commit must be 40 lowercase hexadecimal characters")
    return commit


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
