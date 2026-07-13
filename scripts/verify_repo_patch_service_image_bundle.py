#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.repo_patch_service_image_bundle import (  # noqa: E402
    ROLE_ORDER,
    verify_repo_patch_service_image_bundle,
)


ROLE_FLAGS = {
    "mesh_control_plane": "mesh-control-plane",
    "repo_patch_authority": "repo-patch-authority",
    "repo_patch_verifier": "repo-patch-verifier",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a repo-patch beta service image bundle against release artifacts and operator policy."
    )
    parser.add_argument("--bundle", required=True, help="Path to mesh.repo_patch_service_image_bundle.v1 JSON.")
    parser.add_argument("--artifact-root", required=True, help="Root for all paths recorded by the bundle.")
    parser.add_argument("--expected-git-commit", required=True, help="Externally expected 40-character source commit.")
    for role in ROLE_ORDER:
        flag = ROLE_FLAGS[role]
        parser.add_argument(
            f"--expected-{flag}-image-tag",
            dest=f"expected_{role}_image_tag",
            required=True,
            help="Externally expected digest-pinned image reference.",
        )
        parser.add_argument(
            f"--expected-{flag}-image-digest",
            dest=f"expected_{role}_image_digest",
            required=True,
            help="Externally expected image digest.",
        )
    parser.add_argument(
        "--expected-verifier-sandbox-profile-digest",
        required=True,
        help="Externally pinned verifier sandbox profile digest.",
    )
    parser.add_argument(
        "--expected-verifier-key-id",
        required=True,
        help="Externally pinned Ed25519 verifier key id.",
    )
    parser.add_argument(
        "--expected-verifier-public-key",
        required=True,
        help="Trusted Ed25519 public-key PEM used to verify the policy hash.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the full verification result as JSON.")
    args = parser.parse_args()

    try:
        packet = _load_json_object(Path(args.bundle))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"failed to read bundle: {exc}", file=sys.stderr)
        return 1

    expected_role_images = {
        role: {
            "tag": getattr(args, f"expected_{role}_image_tag"),
            "digest": getattr(args, f"expected_{role}_image_digest"),
        }
        for role in ROLE_ORDER
    }
    result = verify_repo_patch_service_image_bundle(
        packet,
        artifact_root=args.artifact_root,
        expected_git_commit=args.expected_git_commit,
        expected_role_images=expected_role_images,
        expected_verifier_sandbox_profile_digest=args.expected_verifier_sandbox_profile_digest,
        expected_verifier_key_id=args.expected_verifier_key_id,
        expected_verifier_public_key_path=args.expected_verifier_public_key,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {', '.join(result['missing']) or 'repo-patch service image bundle verified'}")
    return 0 if result["status"] == "pass" else 1


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("bundle JSON must be an object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
