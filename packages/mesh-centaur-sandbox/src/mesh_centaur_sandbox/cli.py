from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mesh_centaur_sandbox._cli_util import emit, exit_code
from mesh_centaur_sandbox._version import __version__
from mesh_centaur_sandbox.centaur_deployment import (
    verify_centaur_kubernetes_live_proof,
    verify_centaur_kubernetes_profile,
)
from mesh_centaur_sandbox.verify_e2e import PACKAGE_ROOT, list_manifests, verify_live_with_fake_cluster, verify_package_e2e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mesh-centaur-sandbox",
        description="Centaur-style proposal sandbox manifests, profile checks, and live proof helpers.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-manifests", help="List bundled Kubernetes manifest overlays").add_argument("--json", action="store_true")

    vp = sub.add_parser("verify-profile", help="Verify static K8s manifest profile checks")
    vp.add_argument("--manifest", type=Path, default=PACKAGE_ROOT / "manifests" / "centaur-sandbox-runtime.k8s.yaml")
    vp.add_argument("--json", action="store_true")

    vl = sub.add_parser("verify-live", help="Verify live cluster or local fake-cluster proof")
    vl.add_argument("--manifest", type=Path, default=PACKAGE_ROOT / "manifests" / "centaur-sandbox-runtime.k8s.yaml")
    vl.add_argument("--kubectl-command", default="kubectl")
    vl.add_argument("--credential-proxy-url", default="")
    vl.add_argument("--allow-blocked", action="store_true", help="Exit 0 when proof is blocked but structured")
    vl.add_argument("--fake-cluster", action="store_true", help="Use bundled fake kubectl/proxy for local proof")
    vl.add_argument("--json", action="store_true")

    ve = sub.add_parser("verify-e2e", help="Verify static profile plus local fake-cluster live proof")
    ve.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "list-manifests":
        payload = list_manifests()
        emit(payload, json_mode=args.json)
        return 0

    if args.command == "verify-profile":
        payload = verify_centaur_kubernetes_profile(str(args.manifest))
        payload["summary"] = "verify profile"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "verify-live":
        if args.fake_cluster or not args.credential_proxy_url:
            payload = verify_live_with_fake_cluster(manifest_path=args.manifest)
        else:
            payload = verify_centaur_kubernetes_live_proof(
                manifest_path=str(args.manifest),
                kubectl_command=args.kubectl_command,
                credential_proxy_url=args.credential_proxy_url,
            )
            payload["summary"] = "verify live"
        if args.allow_blocked and payload.get("status") == "blocked":
            payload["status"] = "pass"
            payload["summary"] = "verify live (blocked allowed)"
        emit(payload, json_mode=args.json)
        return 0 if payload.get("status") == "pass" else 1

    if args.command == "verify-e2e":
        payload = verify_package_e2e()
        payload["summary"] = "verify-e2e"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
