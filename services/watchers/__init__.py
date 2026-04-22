"""Typed watchers for multi-domain production monitoring.

Every watcher is a self-contained poller with its own cadence, dedup, and
run-creation logic.  The :class:`WatcherRegistry` owns the thread lifecycle
and surfaces a uniform status/start/stop API.

See ``docs/plans/sub-agent-specialization.md`` for the full design.
"""

from .base import Watcher, WatcherRegistry
from .kubernetes import KubernetesWatcher, WatchTarget

__all__ = [
    "KubernetesWatcher",
    "Watcher",
    "WatcherRegistry",
    "WatchTarget",
]
