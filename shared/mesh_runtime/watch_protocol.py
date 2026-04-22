"""Structural protocols used by WatchDaemon to avoid a services <-> services import cycle.

WatchDaemon previously imported ``RunCoordinator`` and ``SignalCorrelator`` from
``services.control_plane`` and ``services.signal_correlator`` under ``TYPE_CHECKING``.
That formed a latent cycle (control_plane imports watch_daemon at module scope).
These Protocols describe the minimal surface WatchDaemon actually uses so it can
be type-checked without importing either concrete service.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from shared.mesh_runtime.config import RuntimeConfig


@runtime_checkable
class CorrelationLike(Protocol):
    correlation_type: str

    def to_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class SignalCorrelatorLike(Protocol):
    def correlate(
        self,
        deployment_name: str,
        namespace: str,
        service: str,
        error_signature: str,
    ) -> CorrelationLike: ...


@runtime_checkable
class RunCoordinatorLike(Protocol):
    config: RuntimeConfig

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]: ...
