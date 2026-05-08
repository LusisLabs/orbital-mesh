#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


CONFIRMATION = "EXPORT_RELEASE_IMAGE"
SCHEMA_VERSION = "mesh.release_image_handoff.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a downloaded release image handoff artifact.")
    parser.add_argument("--manifest", required=True, help="Path to release-image-handoff.json.")
    parser.add_argument("--image-archive", default="", help="Override image archive path after artifact download.")
    parser.add_argument("--artifact-root", default="", help="Root directory for referenced handoff artifacts.")
    parser.add_argument("--image-ref", default="", help="Optional loaded Docker image ref to compare with the handoff digest.")
    parser.add_argument(
        "--complete-release-provenance",
        default="",
        help="Optional final complete release provenance packet to compare with the handoff digest and commit.",
    )
    parser.add_argument(
        "--runtime-release-provenance-path",
        default="",
        help="Container-readable MESH_RELEASE_PROVENANCE_PATH to write into --env-output.",
    )
    parser.add_argument(
        "--env-output",
        default="",
        help="Write runtime dotenv only after handoff, image-ref, and complete release provenance checks pass.",
    )
    parser.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Require and verify referenced CI attestation, release provenance, SBOM, and vulnerability scan paths.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON.")
    args = parser.parse_args()

    result = verify_handoff(
        manifest_path=Path(args.manifest),
        image_archive_override=args.image_archive,
        artifact_root=Path(args.artifact_root) if args.artifact_root else None,
        image_ref=args.image_ref,
        complete_release_provenance=Path(args.complete_release_provenance)
        if args.complete_release_provenance
        else None,
        runtime_release_provenance_path=args.runtime_release_provenance_path,
        env_output=Path(args.env_output) if args.env_output else None,
        require_artifacts=args.require_artifacts,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {', '.join(result['missing']) or 'release image handoff verified'}")
    return 0 if result["status"] == "pass" else 1


def verify_handoff(
    *,
    manifest_path: Path,
    image_archive_override: str = "",
    artifact_root: Path | None = None,
    image_ref: str = "",
    complete_release_provenance: Path | None = None,
    runtime_release_provenance_path: str = "",
    env_output: Path | None = None,
    require_artifacts: bool = False,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": "mesh.release_image_handoff_verification.v1",
        "status": "fail",
        "manifest": str(manifest_path),
        "checks": {},
        "missing": [],
        "resolved_paths": {},
        "runtime_env": {},
    }
    packet = _load_json(manifest_path)
    if packet is None:
        return _finalize(result, ["manifest_json"])
    if not isinstance(packet, dict):
        return _finalize(result, ["manifest_json"])

    checks = result["checks"]
    checks["schema_version"] = packet.get("schema_version") == SCHEMA_VERSION
    checks["status_ready"] = packet.get("status") == "ready"
    checks["missing_empty"] = packet.get("missing") == []
    checks["embedded_checks_passed"] = _embedded_checks_pass(packet)
    checks["handoff_sha256"] = _payload_hash_matches(packet)
    checks["operator_confirmation"] = _operator_confirmation_valid(packet)
    checks["git_commit"] = _valid_git_commit(_nested(packet, "git", "commit"))
    checks["image_digest"] = _valid_digest(_nested(packet, "image", "digest"))

    image_archive = _resolve_image_archive(
        packet=packet,
        manifest_path=manifest_path,
        override=image_archive_override,
        artifact_root=artifact_root,
    )
    result["resolved_paths"]["image_archive"] = str(image_archive) if image_archive else None
    checks["image_archive_exists"] = bool(image_archive and image_archive.is_file())
    checks["image_archive_bytes_match"] = _archive_bytes_match(packet, image_archive)
    checks["image_archive_sha256_match"] = _archive_hash_match(packet, image_archive)

    artifacts = _artifact_checks(
        packet=packet,
        manifest_path=manifest_path,
        artifact_root=artifact_root,
        require_artifacts=require_artifacts,
    )
    result["resolved_paths"]["artifacts"] = artifacts["resolved_paths"]
    checks.update(artifacts["checks"])

    if image_ref:
        image = _image_ref_record(
            image_ref=image_ref,
            expected_digest=_nested(packet, "image", "digest"),
            runner=runner or _run,
        )
        result["image_ref"] = image
        checks["image_ref_digest_match"] = image["digest_match"]
    elif env_output is not None:
        checks["env_output_image_ref"] = False

    if complete_release_provenance is not None:
        complete = _complete_release_provenance_record(
            path=complete_release_provenance,
            packet=packet,
        )
        result["complete_release_provenance"] = complete
        result["resolved_paths"]["complete_release_provenance"] = str(complete_release_provenance)
        checks.update(complete["checks"])
        result["runtime_env"] = _runtime_env(
            packet=packet,
            complete_release_provenance=complete_release_provenance,
            runtime_release_provenance_path=runtime_release_provenance_path,
            image_ref=image_ref,
        )
    elif env_output is not None:
        result["resolved_paths"]["complete_release_provenance"] = None
        checks["complete_release_provenance_present"] = False

    if env_output is not None:
        if not require_artifacts:
            checks["env_output_artifacts_required"] = False
        checks["env_output_binding_evidence"] = bool(
            checks.get("image_ref_digest_match")
            and checks.get("complete_release_provenance_complete")
            and checks.get("complete_release_provenance_commit_match")
            and checks.get("complete_release_provenance_image_digest_match")
        )

    finalized = _finalize(result, [name for name, passed in checks.items() if not passed])
    if env_output is not None and finalized["status"] == "pass":
        _write_env_output(env_output, finalized["runtime_env"])
        finalized["resolved_paths"]["env_output"] = str(env_output)
    return finalized


def _embedded_checks_pass(packet: dict[str, Any]) -> bool:
    raw = packet.get("checks")
    return isinstance(raw, dict) and bool(raw) and all(value is True for value in raw.values())


def _payload_hash_matches(packet: dict[str, Any]) -> bool:
    expected = packet.get("handoff_sha256")
    if not isinstance(expected, str) or not _valid_sha256(expected):
        return False
    payload = dict(packet)
    payload.pop("handoff_sha256", None)
    return _payload_hash(payload) == expected


def _operator_confirmation_valid(packet: dict[str, Any]) -> bool:
    approval = packet.get("approval")
    if not isinstance(approval, dict):
        return False
    return (
        approval.get("required") is True
        and approval.get("confirmation_required") == CONFIRMATION
        and approval.get("confirmation_observed") == CONFIRMATION
    )


def _resolve_image_archive(
    *,
    packet: dict[str, Any],
    manifest_path: Path,
    override: str,
    artifact_root: Path | None,
) -> Path | None:
    if override.strip():
        return Path(override.strip())
    raw = _nested(packet, "image", "archive")
    if not isinstance(raw, str):
        return None
    return _resolve_recorded_path(raw, manifest_path=manifest_path, artifact_root=artifact_root)


def _archive_bytes_match(packet: dict[str, Any], image_archive: Path | None) -> bool:
    if image_archive is None or not image_archive.is_file():
        return False
    expected = _nested(packet, "image", "archive_bytes")
    return isinstance(expected, int) and expected > 0 and image_archive.stat().st_size == expected


def _archive_hash_match(packet: dict[str, Any], image_archive: Path | None) -> bool:
    if image_archive is None or not image_archive.is_file():
        return False
    expected = _nested(packet, "image", "archive_sha256")
    return isinstance(expected, str) and _valid_sha256(expected) and _file_sha256(image_archive) == expected


def _artifact_checks(
    *,
    packet: dict[str, Any],
    manifest_path: Path,
    artifact_root: Path | None,
    require_artifacts: bool,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    resolved: dict[str, str | None] = {}
    raw_artifacts = packet.get("artifacts")
    artifacts = raw_artifacts if isinstance(raw_artifacts, dict) else {}
    for name in ("release_provenance", "ci_attestation", "sbom", "vulnerability_scan"):
        raw = artifacts.get(name)
        path = _resolve_recorded_path(str(raw), manifest_path=manifest_path, artifact_root=artifact_root) if raw else None
        resolved[name] = str(path) if path else None
        checks[f"{name}_present"] = not require_artifacts or bool(path and path.is_file())
        if path and path.is_file():
            checks[f"{name}_json"] = _load_json(path) is not None

    ci = _load_json(Path(resolved["ci_attestation"])) if resolved.get("ci_attestation") else None
    if isinstance(ci, dict):
        checks["ci_attestation_commit_match"] = _nested(ci, "sha") == _nested(packet, "git", "commit")
        checks["ci_attestation_image_digest_match"] = _nested(ci, "image", "digest") == _nested(packet, "image", "digest")
    elif require_artifacts:
        checks["ci_attestation_commit_match"] = False
        checks["ci_attestation_image_digest_match"] = False

    provenance = _load_json(Path(resolved["release_provenance"])) if resolved.get("release_provenance") else None
    if isinstance(provenance, dict):
        checks["release_provenance_commit_match"] = _nested(provenance, "git", "commit") == _nested(packet, "git", "commit")
        checks["release_provenance_image_digest_match"] = (
            _nested(provenance, "image", "digest") == _nested(packet, "image", "digest")
        )
    elif require_artifacts:
        checks["release_provenance_commit_match"] = False
        checks["release_provenance_image_digest_match"] = False

    return {"checks": checks, "resolved_paths": resolved}


def _image_ref_record(
    *,
    image_ref: str,
    expected_digest: Any,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    try:
        payload = _docker_image_inspect(image_ref, runner=runner)
    except RuntimeError as exc:
        return {
            "image_ref": image_ref,
            "error": str(exc),
            "digest_candidates": [],
            "digest_match": False,
        }
    expected = _normalized_digest(expected_digest)
    candidates = _image_digest_candidates(payload)
    return {
        "image_ref": image_ref,
        "image_id": _normalized_digest(payload.get("Id")),
        "repo_digests": [item for item in payload.get("RepoDigests", []) if isinstance(item, str)],
        "digest_candidates": candidates,
        "digest_match": bool(expected and expected in candidates),
    }


def _docker_image_inspect(
    image_ref: str,
    *,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    result = runner(["docker", "image", "inspect", image_ref])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"docker image inspect failed for {image_ref}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"docker image inspect returned invalid JSON for {image_ref}") from exc
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError(f"docker image inspect returned invalid payload for {image_ref}")
    return payload[0]


def _image_digest_candidates(payload: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    image_id = _normalized_digest(payload.get("Id"))
    if image_id:
        candidates.append(image_id)
    repo_digests = payload.get("RepoDigests")
    if isinstance(repo_digests, list):
        for item in repo_digests:
            if not isinstance(item, str) or "@sha256:" not in item:
                continue
            digest = _normalized_digest(item.split("@", 1)[1])
            if digest:
                candidates.append(digest)
    return _dedupe(candidates)


def _complete_release_provenance_record(*, path: Path, packet: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, bool] = {"complete_release_provenance_present": path.is_file()}
    payload = _load_json(path) if path.is_file() else None
    checks["complete_release_provenance_json"] = isinstance(payload, dict)
    if not isinstance(payload, dict):
        return {"path": str(path), "checks": checks}

    checks["complete_release_provenance_schema_version"] = (
        payload.get("schema_version") == "mesh.release_provenance.v1"
    )
    checks["complete_release_provenance_complete"] = payload.get("status") == "complete"
    checks["complete_release_provenance_missing_empty"] = payload.get("missing") == []
    checks["complete_release_provenance_checks_passed"] = _embedded_checks_pass(payload)
    checks["complete_release_provenance_commit_match"] = (
        _nested(payload, "git", "commit") == _nested(packet, "git", "commit")
    )
    checks["complete_release_provenance_image_digest_match"] = (
        _nested(payload, "image", "digest") == _nested(packet, "image", "digest")
    )
    checks["complete_release_provenance_ci_sha_matches_git_commit"] = _ci_sha_matches_git_commit(payload)
    return {
        "path": str(path),
        "packet_sha256": payload.get("packet_sha256"),
        "git_commit": _nested(payload, "git", "commit"),
        "image_digest": _nested(payload, "image", "digest"),
        "checks": checks,
    }


def _ci_sha_matches_git_commit(payload: dict[str, Any]) -> bool:
    direct = _nested(payload, "ci_attestation", "sha_matches_git_commit")
    nested = _nested(payload, "ci", "attestation", "sha_matches_git_commit")
    return direct is True or nested is True


def _runtime_env(
    *,
    packet: dict[str, Any],
    complete_release_provenance: Path,
    runtime_release_provenance_path: str,
    image_ref: str,
) -> dict[str, str]:
    verified_image_ref = image_ref.strip()
    return {
        "MESH_IMAGE": verified_image_ref,
        "MESH_STACK_IMAGE": verified_image_ref,
        "MESH_RELEASE_PROVENANCE_PATH": runtime_release_provenance_path or str(complete_release_provenance),
        "MESH_BUILD_COMMIT": str(_nested(packet, "git", "commit") or ""),
        "MESH_BUILD_IMAGE_DIGEST": str(_nested(packet, "image", "digest") or ""),
    }


def _write_env_output(path: Path, runtime_env: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in runtime_env.items() if isinstance(value, str) and value]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_recorded_path(raw: str, *, manifest_path: Path, artifact_root: Path | None) -> Path | None:
    value = raw.strip()
    if not value:
        return None
    path = Path(value)
    bases = [Path.cwd(), manifest_path.parent, manifest_path.parent.parent]
    if artifact_root is not None:
        bases.insert(0, artifact_root)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend(base / path for base in bases)
        if value.startswith("dist/"):
            stripped = Path(value[len("dist/") :])
            candidates.extend(base / stripped for base in bases)
        candidates.append(manifest_path.parent / path.name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0] if candidates else None


def _nested(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _valid_git_commit(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value)


def _valid_digest(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    tail = value[len("sha256:") :]
    return len(tail) == 64 and all(char in "0123456789abcdefABCDEF" for char in tail)


def _normalized_digest(value: Any) -> str | None:
    candidate = value.strip() if isinstance(value, str) else ""
    if not candidate.startswith("sha256:"):
        return None
    tail = candidate[len("sha256:") :]
    if len(tail) != 64 or any(char not in "0123456789abcdefABCDEF" for char in tail):
        return None
    return "sha256:" + tail.lower()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finalize(result: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    result["missing"] = _dedupe(missing)
    result["status"] = "fail" if result["missing"] else "pass"
    return result


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


if __name__ == "__main__":
    sys.exit(main())
