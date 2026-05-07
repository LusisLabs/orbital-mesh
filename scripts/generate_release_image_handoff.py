#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


CONFIRMATION = "EXPORT_RELEASE_IMAGE"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a manifest for an operator-approved release image handoff artifact."
    )
    parser.add_argument("--image-tag", required=True, help="Docker image tag included in the archive.")
    parser.add_argument("--image-digest", required=True, help="sha256 digest from release image metadata.")
    parser.add_argument("--git-commit", required=True, help="Git commit used to build the image.")
    parser.add_argument("--image-archive", required=True, help="Path to the docker save archive.")
    parser.add_argument("--output", required=True, help="Write mesh.release_image_handoff.v1 JSON here.")
    parser.add_argument("--confirmation", required=True, help=f"Must be {CONFIRMATION}.")
    parser.add_argument("--release-provenance", default="", help="Optional release provenance draft path.")
    parser.add_argument("--ci-attestation", default="", help="Optional CI attestation path.")
    parser.add_argument("--sbom", default="", help="Optional SBOM path.")
    parser.add_argument("--vulnerability-scan", default="", help="Optional vulnerability scan path.")
    args = parser.parse_args()

    try:
        packet = build_handoff_manifest(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


def build_handoff_manifest(args: argparse.Namespace) -> dict[str, Any]:
    image_archive = Path(args.image_archive)
    git_commit = args.git_commit.strip()
    image_digest = args.image_digest.strip()
    confirmation = args.confirmation.strip()

    missing: list[str] = []
    checks = {
        "confirmation": confirmation == CONFIRMATION,
        "git_commit": _valid_git_commit(git_commit),
        "image_digest": _valid_digest(image_digest),
        "image_archive_exists": image_archive.is_file(),
        "image_archive_non_empty": image_archive.is_file() and image_archive.stat().st_size > 0,
    }
    missing.extend(name for name, passed in checks.items() if not passed)
    if missing:
        raise ValueError("release image handoff manifest incomplete: " + ", ".join(missing))

    packet: dict[str, Any] = {
        "schema_version": "mesh.release_image_handoff.v1",
        "generated_at": _timestamp(),
        "status": "ready",
        "approval": {
            "required": True,
            "confirmation_required": CONFIRMATION,
            "confirmation_observed": confirmation,
        },
        "git": {
            "commit": git_commit,
        },
        "image": {
            "tag": args.image_tag,
            "digest": image_digest,
            "archive": str(image_archive),
            "archive_sha256": _file_sha256(image_archive),
            "archive_bytes": image_archive.stat().st_size,
        },
        "artifacts": _artifact_paths(args),
        "checks": checks,
        "missing": [],
    }
    packet["handoff_sha256"] = _payload_hash(packet)
    return packet


def _artifact_paths(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "release_provenance": _optional_path(args.release_provenance),
        "ci_attestation": _optional_path(args.ci_attestation),
        "sbom": _optional_path(args.sbom),
        "vulnerability_scan": _optional_path(args.vulnerability_scan),
    }


def _optional_path(value: str) -> str | None:
    raw = value.strip()
    return raw or None


def _valid_git_commit(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value)


def _valid_digest(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    tail = value[len("sha256:") :]
    return len(tail) == 64 and all(char in "0123456789abcdefABCDEF" for char in tail)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    sys.exit(main())
