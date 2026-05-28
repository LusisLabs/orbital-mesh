#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from verify_release_runtime_binding import verify_release_runtime_binding


SCHEMA_VERSION = "mesh.release_artifact_bundle_verification.v1"
DEFAULT_RUNTIME_RELEASE_PROVENANCE_PATH = "/app/.mesh-runtime-state/release-provenance.json"

ARTIFACT_PATHS = {
    "ci_attestation": Path("ci-attestation/ci-attestation.json"),
    "release_provenance": Path("release-provenance-draft/release-provenance-draft.json"),
    "release_image_metadata": Path("release-provenance-draft/release-image-metadata.json"),
    "migration_rehearsal": Path("release-provenance-draft/migration-rehearsal.json"),
    "sbom": Path("release-assurance-artifacts/release-assurance/sbom.cdx.json"),
    "vulnerability_scan": Path("release-assurance-artifacts/release-assurance/vulnerability-scan.json"),
}

HANDOFF_ARTIFACT_PATHS = {
    "ci_attestation": Path("ci-attestation.json"),
    "release_provenance": Path("release-provenance-draft.json"),
    "release_image_metadata": Path("release-image-metadata.json"),
    "migration_rehearsal": Path("migration-rehearsal.json"),
    "sbom": Path("release-assurance/sbom.cdx.json"),
    "vulnerability_scan": Path("release-assurance/vulnerability-scan.json"),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a downloaded CI release artifact bundle and optional runtime binding env."
    )
    parser.add_argument("--artifact-root", required=True, help="Directory produced by `gh run download`.")
    parser.add_argument("--expected-head", default="", help="Expected git commit for the bundle.")
    parser.add_argument(
        "--runtime-release-provenance-path",
        default=DEFAULT_RUNTIME_RELEASE_PROVENANCE_PATH,
        help="Container-readable MESH_RELEASE_PROVENANCE_PATH for generated runtime env.",
    )
    parser.add_argument("--image-ref", default="", help="Optional loaded Docker image ref to bind.")
    parser.add_argument("--health-url", default="", help="Optional live /api/health URL to bind.")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="Timeout for --health-url.")
    parser.add_argument("--env-output", default="", help="Write runtime dotenv after bundle and binding checks pass.")
    parser.add_argument(
        "--allow-unverified-env-output",
        action="store_true",
        help="Allow env output without --image-ref or --health-url when an external deployer verifies the image.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable verification JSON.")
    args = parser.parse_args()

    result = verify_release_artifact_bundle(
        artifact_root=Path(args.artifact_root),
        expected_head=args.expected_head,
        runtime_release_provenance_path=args.runtime_release_provenance_path,
        image_ref=args.image_ref,
        health_url=args.health_url,
        timeout_seconds=args.timeout_seconds,
        env_output=Path(args.env_output) if args.env_output else None,
        allow_unverified_env_output=args.allow_unverified_env_output,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {', '.join(result['missing']) or 'release artifact bundle verified'}")
    return 0 if result["status"] == "pass" else 1


def verify_release_artifact_bundle(
    *,
    artifact_root: Path,
    expected_head: str = "",
    runtime_release_provenance_path: str = DEFAULT_RUNTIME_RELEASE_PROVENANCE_PATH,
    image_ref: str = "",
    health_url: str = "",
    timeout_seconds: float = 10.0,
    env_output: Path | None = None,
    allow_unverified_env_output: bool = False,
) -> dict[str, Any]:
    artifact_root = artifact_root.resolve()
    bundle_root, relative_paths, layout = _resolve_artifact_layout(artifact_root)
    paths = {name: bundle_root / relative for name, relative in relative_paths.items()}
    checks: dict[str, bool] = {
        "artifact_root_present": artifact_root.is_dir(),
        "artifact_layout_supported": layout != "unsupported",
    }
    missing: list[str] = []
    payloads: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    for name, path in paths.items():
        checks[f"{name}_exists"] = path.is_file()
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors[name] = str(exc)
            checks[f"{name}_json"] = False
            continue
        checks[f"{name}_json"] = isinstance(payload, dict)
        if isinstance(payload, dict):
            payloads[name] = payload

    release = payloads.get("release_provenance", {})
    ci = payloads.get("ci_attestation", {})
    metadata = payloads.get("release_image_metadata", {})

    git_commit = _normalized_git_commit(_nested(release, "git", "commit"))
    image_digest = _normalized_digest(_nested(release, "image", "digest"))
    release_ci = _nested_dict(release, "ci", "attestation")

    checks.update(
        {
            "release_schema": release.get("schema_version") == "mesh.release_provenance.v1",
            "release_complete": release.get("status") == "complete",
            "release_missing_empty": release.get("missing") == [],
            "release_checks_all_pass": _embedded_checks_pass(release),
            "release_packet_hash": _packet_hash_matches(release, "packet_sha256"),
            "release_git_commit": bool(git_commit),
            "release_image_digest": bool(image_digest),
            "expected_head_match": not expected_head or git_commit == expected_head,
            "ci_schema": ci.get("schema_version") == "mesh.ci_attestation.v1",
            "ci_provider": ci.get("provider") == "github-actions",
            "ci_sha_matches_release": ci.get("sha") == git_commit and release_ci.get("sha") == git_commit,
            "ci_release_sha_bound": release_ci.get("sha_matches_git_commit") is True,
            "ci_image_digest_matches_release": _normalized_digest(_nested(ci, "image", "digest")) == image_digest
            and _normalized_digest(release_ci.get("image_digest")) == image_digest,
            "ci_release_image_bound": release_ci.get("image_digest_matches") is True,
            "ci_file_hash_matches_release": _hash_matches(paths["ci_attestation"], release_ci.get("sha256")),
            "sbom_file_hash_matches_release": _hash_matches(paths["sbom"], _nested(release, "sbom", "sha256")),
            "vulnerability_scan_file_hash_matches_release": _hash_matches(
                paths["vulnerability_scan"], _nested(release, "vulnerability_scan", "sha256")
            ),
            "migration_rehearsal_file_hash_matches_release": _hash_matches(
                paths["migration_rehearsal"], _nested(release, "migrations", "rehearsal", "sha256")
            ),
            "sbom_valid": _nested(release, "sbom", "valid") is True,
            "vulnerability_scan_valid": _nested(release, "vulnerability_scan", "valid") is True,
            "vulnerability_scan_no_blocking_findings": int(_nested(release, "vulnerability_scan", "blocking_finding_count") or 0)
            == 0,
            "migration_rehearsal_valid": _nested(release, "migrations", "rehearsal", "status") == "pass"
            and _nested(release, "migrations", "rehearsal", "valid") is True,
            "metadata_schema": metadata.get("schema_version") == "mesh.release_image_metadata.v1",
            "metadata_image_digest_matches_release": _normalized_digest(_nested(metadata, "image", "digest")) == image_digest,
        }
    )

    runtime_binding: dict[str, Any] | None = None
    if image_ref or health_url or env_output:
        runtime_binding = verify_release_runtime_binding(
            release_provenance=paths["release_provenance"],
            runtime_release_provenance_path=runtime_release_provenance_path,
            image_ref=image_ref,
            health_url=health_url,
            timeout_seconds=timeout_seconds,
        )
        checks["runtime_binding"] = runtime_binding.get("status") == "pass"
        if env_output and not (image_ref or health_url or allow_unverified_env_output):
            checks["env_output_binding_evidence"] = False
        elif env_output and runtime_binding.get("status") == "pass":
            _write_env_output(env_output, _runtime_env(runtime_binding))

    missing = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if not missing else "fail",
        "artifact_root": str(artifact_root),
        "artifact_bundle_root": str(bundle_root),
        "artifact_layout": layout,
        "checks": checks,
        "missing": missing,
        "errors": errors,
        "release": {
            "git_commit": git_commit,
            "image_digest": image_digest,
            "packet_sha256": release.get("packet_sha256"),
            "ci_run_id": release_ci.get("run_id"),
            "ci_workflow": release_ci.get("workflow"),
        },
        "resolved_paths": {name: str(path) for name, path in paths.items()},
        "runtime_binding": runtime_binding,
    }


def _resolve_artifact_layout(artifact_root: Path) -> tuple[Path, dict[str, Path], str]:
    if _has_artifact_paths(artifact_root, ARTIFACT_PATHS):
        return artifact_root, ARTIFACT_PATHS, "ci-download"
    if _has_artifact_paths(artifact_root, HANDOFF_ARTIFACT_PATHS):
        return artifact_root, HANDOFF_ARTIFACT_PATHS, "release-image-handoff"

    handoff_roots = [
        child
        for child in artifact_root.iterdir()
        if child.is_dir() and child.name.startswith("release-image-handoff-")
    ] if artifact_root.is_dir() else []
    for child in sorted(handoff_roots, key=lambda path: path.name):
        if _has_artifact_paths(child, HANDOFF_ARTIFACT_PATHS):
            return child, HANDOFF_ARTIFACT_PATHS, "release-image-handoff"
    return artifact_root, ARTIFACT_PATHS, "unsupported"


def _has_artifact_paths(root: Path, paths: dict[str, Path]) -> bool:
    return root.is_dir() and all((root / relative).is_file() for relative in paths.values())


def _embedded_checks_pass(payload: dict[str, Any]) -> bool:
    checks = payload.get("checks")
    return isinstance(checks, dict) and bool(checks) and all(value is True for value in checks.values())


def _packet_hash_matches(payload: dict[str, Any], key: str) -> bool:
    expected = payload.get(key)
    if not isinstance(expected, str) or not expected:
        return False
    copy = dict(payload)
    copy.pop(key, None)
    raw = json.dumps(copy, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest() == expected


def _hash_matches(path: Path, expected: Any) -> bool:
    if not isinstance(expected, str) or not path.is_file():
        return False
    return _sha256(path) == expected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    value = _nested(payload, *keys)
    return value if isinstance(value, dict) else {}


def _normalized_git_commit(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value):
        return value
    return ""


def _normalized_digest(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("sha256:") and len(value) == 71 and all(
        char in "0123456789abcdefABCDEF" for char in value.removeprefix("sha256:")
    ):
        return value
    return ""


def _runtime_env(runtime_binding: dict[str, Any]) -> dict[str, str]:
    raw = runtime_binding.get("runtime_env")
    return {str(key): str(value) for key, value in raw.items()} if isinstance(raw, dict) else {}


def _write_env_output(path: Path, runtime_env: dict[str, str]) -> None:
    ordered = [
        "MESH_RELEASE_PROVENANCE_PATH",
        "MESH_BUILD_COMMIT",
        "MESH_BUILD_IMAGE_DIGEST",
        "MESH_IMAGE",
        "MESH_STACK_IMAGE",
    ]
    keys = [key for key in ordered if key in runtime_env]
    keys.extend(sorted(key for key in runtime_env if key not in set(keys)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}={runtime_env[key]}\n" for key in keys), encoding="utf-8")


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
