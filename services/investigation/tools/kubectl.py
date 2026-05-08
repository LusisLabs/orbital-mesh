"""Live kubectl read-only domain pack for the investigation harness.

Three tools, all read-only, all run ``kubectl`` as a subprocess:

* ``kubectl_get`` — list resources, like ``kubectl get pods -n NS``.
* ``kubectl_describe`` — describe a single resource.
* ``kubectl_logs`` — recent container logs (``--tail=N``).

Why subprocess and not the kubernetes Python client:

* ``kubectl`` is the universal contract; every cluster operator has
  a working kubeconfig. Adding the ~12 MB ``kubernetes`` package as a
  hard dependency is heavier than the value it adds for read-only
  access.
* The CloudOps domain pack already deals in kubectl-shaped output
  (snapshot tool_cache stores literal ``kubectl get`` text). Live
  tools producing the same shape lets a single planner work against
  either source.

Read-only enforcement (defense in depth, like AWS):

* Critic blocks anything not classified ``read_only``.
* Each invoke fn is a wrapper that builds an explicit argv with a
  fixed verb (``get`` / ``describe`` / ``logs``). User-supplied args
  flow only into resource selectors / namespaces / names — never into
  the kubectl verb. There is no "exec arbitrary kubectl" tool here.
* Output is bounded to ``MAX_OUTPUT_BYTES`` so a misconfigured query
  can't drown the loop in megabytes of YAML.

This is the first domain pack that talks to a live operator-grade
cluster. The same pack works against a local kind cluster, a remote
EKS, or a CI cluster — kubectl resolves the context.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from ..harness import (
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)


DOMAIN = "kubectl"

MAX_OUTPUT_BYTES = 64 * 1024  # 64 KiB per tool call

_BASE_ARGS_SCHEMA: dict[str, Any] = {
    "context": {"type": "str", "required": False, "nullable": True},
    "namespace": {"type": "str", "required": False, "nullable": True},
}


def _build_definitions() -> list[ToolDefinition]:
    get_args = {
        **_BASE_ARGS_SCHEMA,
        "resource_type": {"type": "str", "required": True},
        "name": {"type": "str", "required": False, "nullable": True},
        "label_selector": {"type": "str", "required": False, "nullable": True},
        "output_wide": {"type": "bool", "required": False},
        "show_labels": {"type": "bool", "required": False},
        "all_namespaces": {"type": "bool", "required": False},
    }
    describe_args = {
        **_BASE_ARGS_SCHEMA,
        "resource_type": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
    }
    logs_args = {
        **_BASE_ARGS_SCHEMA,
        "name": {"type": "str", "required": True},
        "container": {"type": "str", "required": False, "nullable": True},
        "tail_lines": {"type": "int", "required": False},
        "previous": {"type": "bool", "required": False},
    }
    descriptions = {
        "kubectl_get": "List Kubernetes resources of a given kind, optionally filtered by namespace / label selector.",
        "kubectl_describe": "Describe a specific Kubernetes resource (events, status, conditions).",
        "kubectl_logs": "Read recent container logs (bounded to tail_lines).",
    }
    schemas = {
        "kubectl_get": get_args,
        "kubectl_describe": describe_args,
        "kubectl_logs": logs_args,
    }
    return [
        ToolDefinition(
            name=name,
            domain=DOMAIN,
            description=description,
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=10.0,
            budget_cost=1.0,
            citations_kind="kubectl_live",
        )
        for name, description in descriptions.items()
    ]


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(_build_definitions())
TOOL_NAMES: tuple[str, ...] = tuple(d.name for d in TOOL_DEFINITIONS)


_NO_KUBECTL_PATH_PROVIDED = object()


def register(
    registry: ToolRegistry,
    *,
    kubectl_path: str | None = _NO_KUBECTL_PATH_PROVIDED,  # type: ignore[assignment]
    default_context: str | None = None,
    default_namespace: str | None = None,
) -> None:
    """Register the three live kubectl read tools.

    ``kubectl_path`` overrides the binary used (test fixtures pass a
    fake script). If unset, ``shutil.which("kubectl")`` is used. An
    explicit empty string or ``None`` disables kubectl invocation —
    callers can register-but-disable for "harness contract present,
    binary intentionally unavailable" cases (tests). Missing kubectl
    produces a clean failed ToolResult, never a FileNotFoundError.
    """
    if kubectl_path is _NO_KUBECTL_PATH_PROVIDED:
        resolved_path = shutil.which("kubectl")
    else:
        resolved_path = kubectl_path or None
    for definition in TOOL_DEFINITIONS:
        registry.register(
            definition,
            _make_kubectl_invoker(
                tool_name=definition.name,
                kubectl_path=resolved_path,
                default_context=default_context,
                default_namespace=default_namespace,
            ),
        )


def _make_kubectl_invoker(
    *,
    tool_name: str,
    kubectl_path: str | None,
    default_context: str | None,
    default_namespace: str | None,
):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        if not kubectl_path:
            return _failure(tool_name, "kubectl binary not found in PATH")
        argv = _build_argv(tool_name, args, default_context, default_namespace)
        if argv is None:
            return _failure(tool_name, "could not build kubectl argv (missing required args)")
        try:
            result = subprocess.run(
                [kubectl_path, *argv],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _failure(tool_name, "kubectl timed out after 10s")
        except OSError as exc:
            return _failure(tool_name, f"kubectl exec error: {exc}")
        stdout = (result.stdout or "")[:MAX_OUTPUT_BYTES]
        stderr = (result.stderr or "")[:1024]
        if result.returncode != 0:
            return _failure(tool_name, stderr.strip() or f"kubectl exited {result.returncode}", argv=argv)
        return RawToolOutput(
            output={"argv": list(argv), "stdout": stdout, "stderr": stderr if stderr else None},
            output_summary=f"kubectl {' '.join(argv)} -> {stdout[:400]}",
            citations=[{"source_type": "kubectl_live", "source_ref": " ".join(argv)}],
            valid=bool(stdout),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _build_argv(
    tool_name: str,
    args: dict[str, Any],
    default_context: str | None,
    default_namespace: str | None,
) -> list[str] | None:
    context = args.get("context") or default_context
    namespace = args.get("namespace") or default_namespace
    base: list[str] = []
    if context:
        base.extend(["--context", str(context)])

    if tool_name == "kubectl_get":
        resource_type = str(args.get("resource_type") or "").strip()
        if not resource_type:
            return None
        argv = [*base, "get", resource_type]
        name = args.get("name")
        if name:
            argv.append(str(name))
        if args.get("all_namespaces"):
            argv.append("--all-namespaces")
        elif namespace:
            argv.extend(["-n", str(namespace)])
        if args.get("label_selector"):
            argv.extend(["-l", str(args["label_selector"])])
        if args.get("output_wide"):
            argv.extend(["-o", "wide"])
        if args.get("show_labels"):
            argv.append("--show-labels")
        return argv

    if tool_name == "kubectl_describe":
        resource_type = str(args.get("resource_type") or "").strip()
        name = str(args.get("name") or "").strip()
        if not resource_type or not name:
            return None
        argv = [*base, "describe", resource_type, name]
        if namespace:
            argv.extend(["-n", str(namespace)])
        return argv

    if tool_name == "kubectl_logs":
        name = str(args.get("name") or "").strip()
        if not name:
            return None
        argv = [*base, "logs", name]
        if namespace:
            argv.extend(["-n", str(namespace)])
        if args.get("container"):
            argv.extend(["-c", str(args["container"])])
        tail = args.get("tail_lines")
        if isinstance(tail, int) and tail > 0:
            argv.extend(["--tail", str(tail)])
        else:
            argv.extend(["--tail", "200"])
        if args.get("previous"):
            argv.append("--previous")
        return argv

    return None


def _failure(tool_name: str, message: str, *, argv: list[str] | None = None) -> RawToolOutput:
    return RawToolOutput(
        output={"argv": argv or [], "error": message},
        output_summary=f"{tool_name} failed: {message[:400]}",
        citations=[{"source_type": "kubectl_live", "source_ref": tool_name}],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )


def maybe_register_at_root(registry: ToolRegistry) -> bool:
    """Register kubectl tools at the engine root iff a kubeconfig is in scope.

    Returns True if registration happened. Used by the runtime engine
    to wire kubectl tools into the root registry without taking
    kubernetes as a hard dep.
    """
    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")
    if not os.path.exists(kubeconfig):
        return False
    if shutil.which("kubectl") is None:
        return False
    register(
        registry,
        default_context=os.environ.get("MESH_KUBECTL_CONTEXT") or None,
        default_namespace=os.environ.get("MESH_KUBECTL_NAMESPACE") or None,
    )
    return True
