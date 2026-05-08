"""AWS read-only domain pack for the investigation harness.

Single tool: ``execute_aws_operation`` — wraps a boto3 client call with
read-only enforcement. Modeled on opensre's ``execute_aws_operation``
(https://github.com/Tracer-Cloud/opensre/blob/main/app/tools/AWSOperationTool/__init__.py),
re-implemented in Mesh's ``ToolDefinition`` shape so we keep the
critic / redaction / citations contract.

Why one generic tool and not 119 per-service wrappers (à la opensre's
EKS×11, Lambda×4, S3×4):

* The boto3 surface is uniform: ``client(service).operation(**params)``.
  A single tool with ``service`` + ``operation`` args covers every
  ``Get``/``Describe``/``List`` call across every AWS service.
* Per-service wrappers add value when there's domain-specific
  post-processing (e.g. CloudWatch metric stats vs. raw Lambda
  config). Mesh doesn't have that yet — when it does, those become
  separate ``aws:cloudwatch_metric_stats`` etc. tools alongside
  this generic one.

Read-only enforcement:

* The critic blocks anything not classified ``read_only``.
* The implementation refuses operations whose verb is not ``Get``,
  ``Describe``, ``List``, or ``Search``. This is a defense in depth:
  even if a caller mis-classifies the tool's mutation_class, the
  invoke fn rejects mutating verbs at runtime.
* boto3 is imported lazily because Mesh doesn't depend on it as a
  hard requirement — most deployments don't run on AWS. Missing
  boto3 returns a clean failed ToolResult, never an ImportError up
  the stack.
"""

from __future__ import annotations

from typing import Any

from ..harness import (
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)


DOMAIN = "aws"


_READ_ONLY_VERB_PREFIXES: tuple[str, ...] = ("describe_", "get_", "list_", "search_", "lookup_")
# Accept both boto3 snake_case methods and AWS-API CamelCase verbs.
# A leading "Describe"/"Get"/"List"/"Search"/"Lookup" maps cleanly to
# the snake_case prefixes above after a normalizer strip.
_READ_ONLY_CAMEL_PREFIXES: tuple[str, ...] = ("Describe", "Get", "List", "Search", "Lookup")


def _build_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="execute_aws_operation",
            domain=DOMAIN,
            description=(
                "Execute a single read-only AWS SDK operation. "
                "Service + operation must resolve to a boto3 client "
                "method whose verb is describe/get/list/search/lookup."
            ),
            args_schema={
                "service": {"type": "str", "required": True},
                "operation": {"type": "str", "required": True},
                "parameters": {"type": "dict", "required": False, "nullable": True},
                "region": {"type": "str", "required": False, "nullable": True},
            },
            mutation_class="read_only",
            timeout_seconds=15.0,
            budget_cost=2.0,
            citations_kind="aws_sdk",
        ),
    ]


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(_build_definitions())


def register(registry: ToolRegistry, *, default_region: str | None = None) -> None:
    """Register the AWS execute_aws_operation tool.

    No client is constructed until the tool is invoked — boto3 is a
    soft dependency (imported lazily) so this registration succeeds on
    boto3-free deployments.
    """
    for definition in TOOL_DEFINITIONS:
        registry.register(definition, _make_invoker(default_region))


def maybe_register_at_root(registry: ToolRegistry) -> bool:
    """Register iff ``MESH_AWS_TOOLS_ENABLED=1``. Returns whether registration fired.

    Gated on env (not config) to keep AWS opt-in: most Mesh deployments
    don't run on AWS and shouldn't pay the boto3 import cost. Region
    defaults to ``MESH_AWS_DEFAULT_REGION`` then ``AWS_DEFAULT_REGION``.
    """
    import os

    enabled = os.environ.get("MESH_AWS_TOOLS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return False
    region = os.environ.get("MESH_AWS_DEFAULT_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    register(registry, default_region=region)
    return True


def _make_invoker(default_region: str | None):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        service = str(args.get("service") or "").strip()
        operation = str(args.get("operation") or "").strip()
        parameters = args.get("parameters") if isinstance(args.get("parameters"), dict) else {}
        region = str(args.get("region") or default_region or "").strip() or None

        if not service or not operation:
            return _error("service and operation are required", service, operation)

        if not _is_read_only_operation(operation):
            return _error(
                f"operation {operation!r} is not classified read-only "
                f"(allowed verb prefixes: {_READ_ONLY_VERB_PREFIXES})",
                service,
                operation,
            )

        try:
            import boto3  # ty: ignore[unresolved-import]
        except ImportError:
            return _error(
                "boto3 not installed; install boto3 to use AWS tools",
                service,
                operation,
            )

        try:
            client = boto3.client(service, region_name=region) if region else boto3.client(service)
            method = getattr(client, operation, None)
            if method is None:
                return _error(
                    f"operation {operation!r} not found on boto3 {service} client",
                    service,
                    operation,
                )
            response = method(**(parameters or {}))
        except Exception as exc:
            return _error(
                f"{type(exc).__name__}: {exc}",
                service,
                operation,
            )

        summary = f"aws {service}.{operation} ok keys={sorted(response.keys()) if isinstance(response, dict) else 'non-dict'}"
        return RawToolOutput(
            output={
                "service": service,
                "operation": operation,
                "response": _redact_aws_response(response),
            },
            output_summary=summary,
            citations=[{"source_type": "aws_sdk", "source_ref": f"{service}.{operation}"}],
            valid=True,
            redaction_status="partial",
            status="completed",
        )

    return invoke


def _is_read_only_operation(operation: str) -> bool:
    if any(operation.startswith(prefix) for prefix in _READ_ONLY_CAMEL_PREFIXES):
        return True
    lowered = operation.lower()
    return any(lowered.startswith(prefix) for prefix in _READ_ONLY_VERB_PREFIXES)


def _error(message: str, service: str, operation: str) -> RawToolOutput:
    return RawToolOutput(
        output={"service": service, "operation": operation, "error": message},
        output_summary=f"aws {service}.{operation} error: {message}",
        citations=[{"source_type": "aws_sdk", "source_ref": f"{service}.{operation}"}],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )


def _redact_aws_response(response: Any) -> Any:
    """Drop fields that commonly leak credentials or identity material.

    Conservative — when in doubt, drop. Callers who need a specific
    field can request it via a more specific operation rather than
    expecting it to survive redaction.
    """
    if isinstance(response, dict):
        redacted: dict[str, Any] = {}
        for key, value in response.items():
            lowered = key.lower()
            if any(token in lowered for token in ("secret", "password", "token", "credential", "private")):
                redacted[key] = "[redacted]"
                continue
            redacted[key] = _redact_aws_response(value)
        return redacted
    if isinstance(response, list):
        return [_redact_aws_response(item) for item in response]
    return response
