from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.ingest.kubernetes_live_signal import collect_kubernetes_signal


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a live Kubernetes deployment into the mesh signal contract.")
    parser.add_argument("--deployment", required=True, help="Deployment name")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace")
    parser.add_argument("--context", help="Optional kube context override")
    parser.add_argument("--environment", default="local", help="Mesh environment label")
    parser.add_argument("--cluster-label", help="Optional cluster label; defaults to the active kube context")
    parser.add_argument("--service", help="Optional service label; defaults to the deployment name")
    parser.add_argument("--kubectl-command", default="kubectl", help="kubectl command or wrapper")
    parser.add_argument("--tail-lines", type=int, default=20, help="Log lines to capture per pod")
    parser.add_argument("--max-log-pods", type=int, default=3, help="Maximum failing pods to capture logs from")
    parser.add_argument("--output", help="Optional output file path")
    parser.add_argument("--repo-path", help="Optional repo path for investigate-and-patch flows")
    parser.add_argument("--suspected-file", help="Optional suspected file path")
    parser.add_argument("--allowed-path", action="append", default=[], help="Optional allowed patch path; repeatable")
    parser.add_argument("--test-command", action="append", default=[], help="Optional bounded test command; repeatable")
    parser.add_argument("--patch-target-file", help="Optional patch target file")
    parser.add_argument("--patch-find", help="Optional patch search text")
    parser.add_argument("--patch-replace", help="Optional patch replacement text")
    args = parser.parse_args()

    patch_template = None
    if args.patch_target_file and args.patch_find and args.patch_replace:
        patch_template = {
            "target_file": args.patch_target_file,
            "find": args.patch_find,
            "replace": args.patch_replace,
        }

    signal = collect_kubernetes_signal(
        deployment_name=args.deployment,
        namespace=args.namespace,
        kube_context=args.context,
        environment=args.environment,
        cluster_label=args.cluster_label,
        service=args.service,
        kubectl_command=args.kubectl_command,
        tail_lines=args.tail_lines,
        max_log_pods=args.max_log_pods,
        repo_path=args.repo_path,
        suspected_file=args.suspected_file,
        allowed_paths=list(args.allowed_path),
        test_commands=list(args.test_command),
        patch_template=patch_template,
    )

    output = json.dumps(signal, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
