"""Legacy ``WatchDaemon`` shim.

Historical single-thread Kubernetes poller.  Preserved as a thin wrapper
around :class:`services.watchers.kubernetes.KubernetesWatcher` +
:class:`services.watchers.base.WatcherRegistry` so that existing callers,
tests, and external integrations continue to work byte-for-byte while the
richer multi-watcher architecture matures.

New code should prefer constructing watchers via the registry directly.
See ``docs/plans/sub-agent-specialization.md``.
"""

from __future__ import annotations

import warnings
from typing import Any

from shared.mesh_runtime.watch_protocol import RunCoordinatorLike, SignalCorrelatorLike

from services.watchers.base import WatcherRegistry
from services.watchers.kubernetes import KubernetesWatcher, WatchTarget, _DeduplicationEntry


_SHIM_WATCHER_NAME = "watch-daemon"


class WatchDaemon:
    """Legacy wrapper preserving the old WatchDaemon public API.

    All state lives inside the wrapped :class:`KubernetesWatcher`; this class
    only reproduces the previous lifecycle surface (``start``/``stop``/
    ``status``/``running``) so existing imports keep working.
    """

    def __init__(
        self,
        coordinator: RunCoordinatorLike,
        targets: list[WatchTarget],
        interval_seconds: int = 60,
        default_cooldown_seconds: int = 300,
        correlator: SignalCorrelatorLike | None = None,
    ) -> None:
        warnings.warn(
            "services.watch_daemon.WatchDaemon is deprecated; use "
            "services.watchers.base.WatcherRegistry + KubernetesWatcher.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._registry = WatcherRegistry()
        self._watcher = KubernetesWatcher(
            name=_SHIM_WATCHER_NAME,
            coordinator=coordinator,
            targets=list(targets),
            interval_seconds=interval_seconds,
            default_cooldown_seconds=default_cooldown_seconds,
            correlator=correlator,
        )
        self._registry.register(self._watcher)
        # Attributes exposed for backwards-compat test access.
        self.coordinator = coordinator
        self.targets = self._watcher.targets
        self.interval_seconds = self._watcher.interval_seconds
        self.default_cooldown_seconds = self._watcher.default_cooldown_seconds
        self.correlator = self._watcher.correlator

    # ------------------------------------------------------------------
    # Public API — matches the historical WatchDaemon surface
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._registry.is_running(_SHIM_WATCHER_NAME)

    def start(self) -> None:
        self._registry.start(_SHIM_WATCHER_NAME)

    def stop(self, timeout: float = 5.0) -> None:
        self._registry.stop(_SHIM_WATCHER_NAME, timeout=timeout)

    def status(self) -> dict[str, Any]:
        detail = self._watcher.status()
        return {
            "running": self.running,
            "targets": detail["targets"],
            "interval_seconds": detail["interval_seconds"],
            "dedup_entries": detail["dedup_entries"],
        }

    # Private helpers kept for tests that reach into the daemon internals.
    @property
    def _dedup(self) -> dict:  # type: ignore[override]
        return self._watcher._dedup

    def _poll_target(self, target: WatchTarget) -> None:
        self._watcher._poll_target(target)

    @staticmethod
    def _is_actionable(signal: dict[str, Any]) -> bool:
        return KubernetesWatcher._is_actionable(signal)

    @staticmethod
    def _extract_error_signature(signal: dict[str, Any]) -> str:
        return KubernetesWatcher._extract_error_signature(signal)


# Re-export WatchTarget + _DeduplicationEntry so legacy imports continue to work.
__all__ = ["WatchDaemon", "WatchTarget", "_DeduplicationEntry"]
