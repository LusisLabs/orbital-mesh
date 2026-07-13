#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.repo_patch_service_image_bundle import (  # noqa: E402
    ROLE_ORDER,
    RepoPatchServiceImageBundleError,
    build_repo_patch_service_image_bundle,
)


ROLE_FLAGS = {
    "mesh_control_plane": "mesh-control-plane",
    "repo_patch_authority": "repo-patch-authority",
    "repo_patch_verifier": "repo-patch-verifier",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a commit-bound release artifact bundle for all repo-patch beta service images."
    )
    parser.add_argument("--artifact-root", required=True, help="Root for Dockerfiles and recorded release artifacts.")
    parser.add_argument("--git-commit", required=True, help="Exact 40-character source commit shared by all roles.")
    parser.add_argument("--output", required=True, help="Write mesh.repo_patch_service_image_bundle.v1 JSON here.")
    for role in ROLE_ORDER:
        flag = ROLE_FLAGS[role]
        destination = role
        parser.add_argument(
            f"--{flag}-image-tag",
            dest=f"{destination}_image_tag",
            required=True,
            help="Digest-pinned image reference in repository@sha256:... form.",
        )
        parser.add_argument(
            f"--{flag}-image-digest",
            dest=f"{destination}_image_digest",
            required=True,
            help="Exact sha256 image digest.",
        )
        parser.add_argument(
            f"--{flag}-sbom",
            dest=f"{destination}_sbom",
            required=True,
            help="Portable CycloneDX SBOM path under --artifact-root.",
        )
        parser.add_argument(
            f"--{flag}-raw-vulnerability-scan",
            dest=f"{destination}_raw_vulnerability_scan",
            required=True,
            help="Portable raw Grype vulnerability-scan path under --artifact-root.",
        )
        parser.add_argument(
            f"--{flag}-vulnerability-scan",
            dest=f"{destination}_vulnerability_scan",
            required=True,
            help="Portable normalized vulnerability-scan path under --artifact-root.",
        )
        parser.add_argument(
            f"--{flag}-vulnerability-evidence",
            dest=f"{destination}_vulnerability_evidence",
            required=True,
            help="Portable mesh.release_vulnerability_evidence.v1 path under --artifact-root.",
        )
        parser.add_argument(
            f"--{flag}-ci-attestation",
            dest=f"{destination}_ci_attestation",
            required=True,
            help="Portable GitHub Actions CI-attestation path under --artifact-root.",
        )
    parser.add_argument(
        "--verifier-sandbox-profile-digest",
        required=True,
        help="Authority-pinned verifier sandbox profile digest.",
    )
    parser.add_argument("--verifier-key-id", required=True, help="Authority-pinned Ed25519 verifier key id.")
    parser.add_argument(
        "--verifier-public-key",
        required=True,
        help="Trusted Ed25519 public-key PEM used to derive the bundle policy hash.",
    )
    args = parser.parse_args()

    role_inputs = {
        role: {
            "image_tag": getattr(args, f"{role}_image_tag"),
            "image_digest": getattr(args, f"{role}_image_digest"),
            "sbom_path": getattr(args, f"{role}_sbom"),
            "raw_vulnerability_scan_path": getattr(args, f"{role}_raw_vulnerability_scan"),
            "vulnerability_scan_path": getattr(args, f"{role}_vulnerability_scan"),
            "vulnerability_evidence_path": getattr(args, f"{role}_vulnerability_evidence"),
            "ci_attestation_path": getattr(args, f"{role}_ci_attestation"),
        }
        for role in ROLE_ORDER
    }
    try:
        packet = build_repo_patch_service_image_bundle(
            artifact_root=args.artifact_root,
            git_commit=args.git_commit,
            role_inputs=role_inputs,
            verifier_sandbox_profile_digest=args.verifier_sandbox_profile_digest,
            verifier_key_id=args.verifier_key_id,
            verifier_public_key_path=args.verifier_public_key,
        )
    except RepoPatchServiceImageBundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
