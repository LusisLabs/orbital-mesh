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
DEFAULT_IMAGE_TAG = "orbital-mesh-stack:dev"
DEPENDENCY_LOCKFILES = (
    "pyproject.toml",
    "uv.lock",
    "web/package-lock.json",
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
    parser.add_argument("--image-digest", default=os.getenv("MESH_IMAGE_DIGEST") or os.getenv("MESH_STACK_IMAGE_DIGEST") or "")
    parser.add_argument("--sbom", default=os.getenv("MESH_SBOM_PATH") or "")
    parser.add_argument("--vulnerability-scan", default=os.getenv("MESH_VULNERABILITY_SCAN_PATH") or "")
    parser.add_argument("--build-command", default=os.getenv("MESH_BUILD_COMMAND") or "")
    parser.add_argument("--builder-identity", default=os.getenv("MESH_BUILDER_IDENTITY") or os.getenv("USER") or "")
    parser.add_argument("--readiness-profile", default=os.getenv("MESH_READINESS_PROFILE") or "pilot")
    parser.add_argument("--environment", default=os.getenv("MESH_ENVIRONMENT") or "production")
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
    base_digest_overrides = _parse_base_digest_overrides(args.base_image_digest)
    git = _git_snapshot()
    base_images = _base_images(base_digest_overrides)
    policies = _hash_directory("policies", "*.json")
    migrations = _hash_directory("migrations/postgres", "*.sql")
    dependency_locks = _hash_paths(DEPENDENCY_LOCKFILES)
    build_inputs = _hash_paths(BUILD_INPUTS)
    image_digest = args.image_digest.strip()
    sbom = _artifact_record(args.sbom)
    vulnerability_scan = _artifact_record(args.vulnerability_scan)
    checks = _checks(
        args=args,
        git=git,
        image_digest=image_digest,
        base_images=base_images,
        policies=policies,
        migrations=migrations,
        dependency_locks=dependency_locks,
        sbom=sbom,
        vulnerability_scan=vulnerability_scan,
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
        },
        "migrations": {
            "directory": "migrations/postgres",
            "version": _migration_version(migrations),
            "hashes": migrations,
            "combined_sha256": _combined_hash(migrations),
        },
        "sbom": sbom,
        "vulnerability_scan": vulnerability_scan,
        "build": {
            "command": args.build_command or None,
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
    base_images: list[dict[str, Any]],
    policies: list[dict[str, str]],
    migrations: list[dict[str, str]],
    dependency_locks: list[dict[str, str]],
    sbom: dict[str, Any],
    vulnerability_scan: dict[str, Any],
) -> dict[str, bool]:
    return {
        "git_commit": bool(git.get("commit")),
        "clean_git_tree": bool(args.allow_dirty or not git.get("dirty")),
        "image_tag": bool(args.image_tag),
        "image_digest": _valid_digest(image_digest),
        "base_image_digests": bool(base_images) and all(_valid_digest(str(item.get("digest") or "")) for item in base_images),
        "dependency_lockfiles": {item["path"] for item in dependency_locks} == set(DEPENDENCY_LOCKFILES),
        "policy_hashes": bool(policies),
        "migration_version": bool(_migration_version(migrations)),
        "sbom_path": bool(sbom.get("exists")),
        "vulnerability_scan_path": bool(vulnerability_scan.get("exists")),
        "build_command": bool(args.build_command),
        "builder_identity": bool(args.builder_identity),
        "readiness_profile": bool(args.readiness_profile),
        "environment": bool(args.environment),
    }


def _git_snapshot() -> dict[str, Any]:
    status = _git(["status", "--porcelain"])
    return {
        "commit": _git(["rev-parse", "--verify", "HEAD"]),
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(status.strip()),
        "dirty_files": [line[3:] for line in status.splitlines() if line.strip()],
    }


def _git(args: list[str]) -> str:
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
    return result.stdout.strip()


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
