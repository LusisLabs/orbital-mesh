#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


REQUIRED_GITHUB_ACTIONS_ENV = ("GITHUB_WORKFLOW", "GITHUB_JOB", "GITHUB_RUN_ID", "GITHUB_SHA")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a CI attestation packet for release provenance.")
    parser.add_argument("--output", required=True, help="Write the attestation JSON to this path.")
    parser.add_argument("--check", action="append", default=[], help="Record a CI check or job name. Repeatable.")
    parser.add_argument("--image-tag", default=os.getenv("MESH_STACK_IMAGE") or os.getenv("MESH_IMAGE") or "")
    parser.add_argument("--image-digest", default=os.getenv("MESH_IMAGE_DIGEST") or os.getenv("MESH_STACK_IMAGE_DIGEST") or "")
    parser.add_argument("--build-command", default=os.getenv("MESH_BUILD_COMMAND") or "")
    parser.add_argument(
        "--base-image-digest",
        action="append",
        default=[],
        metavar="IMAGE=sha256:...",
        help="Record an attested base-image digest. Repeatable.",
    )
    parser.add_argument(
        "--require-github-actions",
        action="store_true",
        help="Fail unless the required GitHub Actions run metadata is available.",
    )
    args = parser.parse_args()

    if args.require_github_actions:
        missing_context = _missing_github_actions_context()
        if missing_context:
            print(
                "missing GitHub Actions attestation context: " + ", ".join(missing_context),
                file=sys.stderr,
            )
            return 1

    packet = build_attestation(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


def build_attestation(args: argparse.Namespace) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": "mesh.ci_attestation.v1",
        "generated_at": _timestamp(),
        "provider": "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else os.getenv("MESH_CI_PROVIDER") or "local",
        "workflow": os.getenv("GITHUB_WORKFLOW") or None,
        "job": os.getenv("GITHUB_JOB") or None,
        "run_id": os.getenv("GITHUB_RUN_ID") or None,
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT") or None,
        "repository": os.getenv("GITHUB_REPOSITORY") or None,
        "ref": os.getenv("GITHUB_REF") or None,
        "sha": os.getenv("GITHUB_SHA") or None,
        "actor": os.getenv("GITHUB_ACTOR") or None,
        "server_url": os.getenv("GITHUB_SERVER_URL") or None,
        "image": {
            "tag": args.image_tag or None,
            "digest": args.image_digest or None,
        },
        "build": {
            "command": args.build_command or None,
            "base_images": _parse_base_image_digests(args.base_image_digest),
        },
        "checks": [
            {"name": str(name), "status": "passed"}
            for name in args.check
        ],
    }
    packet["attestation_sha256"] = _payload_hash(packet)
    return packet


def _missing_github_actions_context() -> list[str]:
    missing: list[str] = []
    if os.getenv("GITHUB_ACTIONS") != "true":
        missing.append("GITHUB_ACTIONS=true")
    missing.extend(field for field in REQUIRED_GITHUB_ACTIONS_ENV if not _env_value(field))
    return missing


def _env_value(name: str) -> str:
    value = os.getenv(name) or ""
    return value.strip()


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_base_image_digests(raw_items: list[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for raw in raw_items:
        if "=" not in raw:
            raise SystemExit(f"invalid --base-image-digest {raw!r}; expected IMAGE=sha256:...")
        image, digest = raw.split("=", 1)
        image = image.strip()
        digest = digest.strip()
        if not image or not _valid_digest(digest):
            raise SystemExit(f"invalid --base-image-digest {raw!r}; digest must be sha256:<64 hex>")
        records.append({"image": image, "digest": digest})
    return records


def _valid_digest(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    tail = value[len("sha256:") :]
    return len(tail) == 64 and all(char in "0123456789abcdefABCDEF" for char in tail)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
