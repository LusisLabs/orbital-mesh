"""Backward-compat shim: translate legacy ``MESH_WATCH_TARGETS`` into a
registered :class:`KubernetesWatcher`.

This lets operators who were running the old ``WatchDaemon`` migrate without
touching env vars — as soon as the control plane imports the new registry,
their existing config wires up a ``kubernetes`` watcher under the name
``legacy-k8s``.  The behavior is byte-identical to the old daemon.

When an operator migrates to the richer ``MESH_WATCHER_CONFIG_PATH`` file
(Phase 2+), this shim quietly steps aside — it is a pure no-op if the new
config file is provided.
"""

from __future__ import annotations

import logging
import os

from shared.mesh_runtime.watch_protocol import RunCoordinatorLike, SignalCorrelatorLike

from .base import WatcherRegistry
from .kubernetes import KubernetesWatcher, WatchTarget


_LOG = logging.getLogger("mesh.watcher_compat")

LEGACY_WATCHER_NAME = "legacy-k8s"


def register_legacy_watchers(
    *,
    coordinator: RunCoordinatorLike,
    registry: WatcherRegistry,
    correlator: SignalCorrelatorLike | None = None,
) -> bool:
    """Register a KubernetesWatcher from legacy config if applicable.

    Returns True iff a watcher was registered by this call.
    """
    config = coordinator.config
    # Operator has migrated — respect their explicit config, skip shim.
    if os.getenv("MESH_WATCHER_CONFIG_PATH"):
        return False

    if not getattr(config, "watch_enabled", False):
        return False
    legacy_targets = getattr(config, "watch_targets", None) or ()
    if not legacy_targets:
        return False

    watch_targets = [
        WatchTarget(
            deployment_name=target["deployment_name"],
            namespace=target.get("namespace", "default"),
            kube_context=target.get("kube_context"),
            cooldown_seconds=target.get("cooldown_seconds"),
        )
        for target in legacy_targets
        if isinstance(target, dict) and target.get("deployment_name")
    ]
    if not watch_targets:
        return False

    watcher = KubernetesWatcher(
        name=LEGACY_WATCHER_NAME,
        coordinator=coordinator,
        targets=watch_targets,
        kubectl_command=config.kubectl_command,
        interval_seconds=getattr(config, "watch_interval_seconds", 60),
        default_cooldown_seconds=getattr(config, "watch_cooldown_seconds", 300),
        correlator=correlator,
    )
    registry.register(watcher)
    _LOG.info(
        "Registered legacy Kubernetes watcher %r with %d target(s)",
        LEGACY_WATCHER_NAME,
        len(watch_targets),
    )
    return True
