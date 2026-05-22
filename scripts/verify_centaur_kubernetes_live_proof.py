from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.centaur_deployment import verify_centaur_kubernetes_live_proof


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify live Centaur Kubernetes sandbox isolation and credential-proxy proof."
    )
    parser.add_argument("--manifest", default="config/centaur-sandbox-runtime.k8s.yaml")
    parser.add_argument("--namespace", default="mesh-centaur-sandboxes")
    parser.add_argument("--kubectl-command", default="kubectl")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--output", default="")
    parser.add_argument("--allow-blocked", action="store_true")
    argv = sys.argv[1:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    args = parser.parse_args(argv)

    proof = verify_centaur_kubernetes_live_proof(
        manifest_path=args.manifest,
        namespace=args.namespace,
        kubectl_command=args.kubectl_command,
        timeout_seconds=args.timeout_seconds,
    )
    body = json.dumps(proof, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(body + "\n", encoding="utf-8")
    print(body)
    if proof.get("status") == "pass" or args.allow_blocked:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
