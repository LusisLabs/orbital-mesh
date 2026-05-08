"""Mesh investigation tool packs.

Each domain pack is one module in this directory and exposes a uniform
trio:

* ``TOOL_DEFINITIONS`` — the immutable tuple of ``ToolDefinition``s
  the pack registers.
* ``register(registry, ...)`` — the entrypoint per-run callers use to
  add the pack to a ``ToolRegistry`` with whatever per-run context
  the pack needs (CloudOps snapshot tools, Reth signal payload, etc.).
* ``maybe_register_at_root(registry)`` — for always-on packs only.
  Reads the deployment's config/env, registers iff backing config is
  present. The unified ``register_root_packs`` below calls every
  pack's helper in one shot.

The "always available" packs (Prometheus, AWS, kubectl, GitHub, Loki,
Jaeger, Postgres, MCP) auto-register at engine startup so the LLM
planner sees them on **every** trigger — not just CloudOpsBench
scenarios. Per-run packs (CloudOps snapshot tools, Reth peer-starvation
probes) are wired in by ``_auto_wire_investigation_harness`` when the
trigger shape calls for them.

Production deployments without a given backend pay zero cost for it:
the ``maybe_register_at_root`` helper checks for config/env presence
before constructing any client, so the registry stays empty for that
domain and the planner never sees its tools.
"""

from __future__ import annotations

from typing import Any

from ..harness import ToolRegistry


def register_root_packs(registry: ToolRegistry, config: Any) -> dict[str, bool]:
    """Auto-register every always-on diagnostic pack onto ``registry``.

    Single entrypoint replaces the per-pack ``maybe_register_X_at_root``
    calls scattered across the runtime engine. Cleaner to recall: one
    call configures everything Mesh has on this deployment.

    Each pack is gated on its own config/env signal:

    * ``prometheus``  — ``RuntimeConfig.prometheus_url`` set
    * ``aws``         — ``MESH_AWS_TOOLS_ENABLED=1``
    * ``kubectl``     — kubeconfig file exists and ``kubectl`` is on PATH
    * ``github``      — ``gh auth status`` succeeds
    * ``loki``        — ``MESH_LOKI_URL`` set
    * ``jaeger``      — ``MESH_JAEGER_URL`` set
    * ``postgres``    — ``MESH_PG_DSN`` set and ``psql`` on PATH
    * ``mcp``         — ``MESH_MCP_SERVERS`` set + caller-supplied
      ``client_factory`` (registered separately by the caller — MCP
      transport is opaque to Mesh)

    Per-pack failures are swallowed and logged; one mis-configured
    Prometheus URL must never keep the engine from starting. Returns
    a ``{domain: registered}`` dict so callers can log which packs
    came up.
    """
    import logging

    log = logging.getLogger("mesh.investigation.tools")
    results: dict[str, bool] = {}

    try:
        from . import prometheus

        results["prometheus"] = prometheus.maybe_register_at_root(registry, config)
    except Exception:
        log.exception("root tool registration: prometheus failed (non-fatal)")
        results["prometheus"] = False

    try:
        from . import aws

        results["aws"] = aws.maybe_register_at_root(registry)
    except Exception:
        log.exception("root tool registration: aws failed (non-fatal)")
        results["aws"] = False

    try:
        from . import kubectl

        results["kubectl"] = kubectl.maybe_register_at_root(registry)
    except Exception:
        log.exception("root tool registration: kubectl failed (non-fatal)")
        results["kubectl"] = False

    try:
        from . import github

        results["github"] = github.maybe_register_at_root(registry)
    except Exception:
        log.exception("root tool registration: github failed (non-fatal)")
        results["github"] = False

    try:
        from . import loki

        results["loki"] = loki.maybe_register_at_root(registry)
    except Exception:
        log.exception("root tool registration: loki failed (non-fatal)")
        results["loki"] = False

    try:
        from . import jaeger

        results["jaeger"] = jaeger.maybe_register_at_root(registry)
    except Exception:
        log.exception("root tool registration: jaeger failed (non-fatal)")
        results["jaeger"] = False

    try:
        from . import postgres

        results["postgres"] = postgres.maybe_register_at_root(registry)
    except Exception:
        log.exception("root tool registration: postgres failed (non-fatal)")
        results["postgres"] = False

    return results


__all__ = ["register_root_packs"]
