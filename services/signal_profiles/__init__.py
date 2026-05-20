"""Signal-profile registry — public entry point.

The runtime engine calls ``build_default_registry(config)`` once at
construction and uses the returned registry to dispatch every
signal-type-aware stage. The factory wires the five concrete
profiles (Reth, Kubernetes, OTel, feature-flag, webhook) plus the
generic agentic-fallback profile.

Adding a new signal type to Mesh is one new file under this
directory plus one line in ``build_default_registry`` — nothing else
changes.
"""

from __future__ import annotations

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.signal_profile import SignalProfileRegistry

from . import feature_flag, generic, kubernetes, otel, reth, webhook


def build_default_registry(config: RuntimeConfig | None = None) -> SignalProfileRegistry:
    """Wire every shipping signal profile + the generic fallback.

    Order does not matter for correctness — the registry validates
    uniqueness and completeness at construction time — but the
    listing here is also the canonical "what signal types does Mesh
    support today" index for new contributors.
    """
    return SignalProfileRegistry(
        profiles=[
            reth.build(config),
            kubernetes.build(config),
            otel.build(config),
            feature_flag.build(config),
            webhook.build(config),
        ],
        generic=generic.build(config),
    )


__all__ = ["build_default_registry"]
