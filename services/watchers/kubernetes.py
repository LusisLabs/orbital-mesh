"""KubernetesWatcher — polls deployments for unhealthy states.

Functionally equivalent to the legacy ``WatchDaemon`` per-target loop but
refactored to the :class:`Watcher` protocol so the same engine can host other
signal sources (feature flags, ArgoCD, Prometheus, etc.).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from shared.mesh_runtime.watch_protocol import RunCoordinatorLike, SignalCorrelatorLike
from services.trigger.service import kubernetes_signal_is_actionable


_LOG = logging.getLogger("mesh.kubernetes_watcher")


@dataclass
class WatchTarget:
    deployment_name: str
    namespace: str = "default"
    kube_context: str | None = None
    cooldown_seconds: int | None = None


@dataclass
class _DeduplicationEntry:
    last_run_id: str | None = None
    last_run_time: float = 0.0
    last_error_signature: str = ""
    active_run_id: str | None = None


class KubernetesWatcher:
    """Typed watcher that polls Kubernetes deployments and enqueues remediation runs.

    Each watcher instance can span one or more targets (deployments) — typically
    grouped by cluster / kube_context.  Dedup state is kept per (namespace,
    deployment) so the same watcher can host many targets without cross-talk.
    """

    signal_source = "kubernetes"

    def __init__(
        self,
        *,
        name: str,
        coordinator: RunCoordinatorLike,
        targets: list[WatchTarget],
        kubectl_command: str | None = None,
        interval_seconds: int = 60,
        default_cooldown_seconds: int = 300,
        correlator: SignalCorrelatorLike | None = None,
    ) -> None:
        self.name = name
        self.coordinator = coordinator
        self.targets = list(targets)
        self.interval_seconds = max(int(interval_seconds), 10)
        self.default_cooldown_seconds = default_cooldown_seconds
        self.correlator = correlator
        # Caller may override kubectl binary; otherwise take it from the
        # coordinator's config (same contract as the legacy daemon).
        self._kubectl_command = kubectl_command or coordinator.config.kubectl_command
        self._dedup: dict[tuple[str, str], _DeduplicationEntry] = {}
        self._dedup_lock = threading.Lock()
        self._last_error: str | None = None
        self._last_tick_at: float | None = None
        self._runs_created: int = 0

    # ------------------------------------------------------------------
    # Watcher protocol
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Poll every target once; internal dedup/cooldown gates run creation."""
        self._last_tick_at = time.monotonic()
        for target in self.targets:
            try:
                self._poll_target(target)
            except Exception as exc:
                self._last_error = f"{target.namespace}/{target.deployment_name}: {exc}"
                _LOG.exception(
                    "KubernetesWatcher %r poll error for %s/%s",
                    self.name,
                    target.namespace,
                    target.deployment_name,
                )

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "signal_source": self.signal_source,
            "interval_seconds": self.interval_seconds,
            "default_cooldown_seconds": self.default_cooldown_seconds,
            "target_count": len(self.targets),
            "targets": [
                {
                    "deployment_name": t.deployment_name,
                    "namespace": t.namespace,
                    "kube_context": t.kube_context,
                    "cooldown_seconds": t.cooldown_seconds,
                }
                for t in self.targets
            ],
            "dedup_entries": len(self._dedup),
            "runs_created": self._runs_created,
            "last_tick_monotonic": self._last_tick_at,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Per-target polling
    # ------------------------------------------------------------------

    def _poll_target(self, target: WatchTarget) -> None:
        dedup_key = (target.namespace, target.deployment_name)
        with self._dedup_lock:
            entry = self._dedup.setdefault(dedup_key, _DeduplicationEntry())

        # If the prior run is still in-flight, skip this target until it resolves.
        if entry.active_run_id is not None:
            active_run = self.coordinator.get_run(entry.active_run_id)
            if active_run and active_run.get("status") not in (
                "completed",
                "failed",
                "cancelled",
            ):
                return
            entry.active_run_id = None

        cooldown = (
            target.cooldown_seconds
            if target.cooldown_seconds is not None
            else self.default_cooldown_seconds
        )
        if entry.last_run_time and time.monotonic() - entry.last_run_time < cooldown:
            return

        # Lazy import to avoid pulling kubectl code paths at package import time.
        from services.ingest.kubernetes_live_signal import collect_kubernetes_signal

        signal = collect_kubernetes_signal(
            deployment_name=target.deployment_name,
            namespace=target.namespace,
            kube_context=target.kube_context,
            kubectl_command=self._kubectl_command,
        )

        if not self._is_actionable(signal):
            return

        error_sig = self._extract_error_signature(signal)
        if error_sig == entry.last_error_signature and entry.last_run_id is not None:
            return

        run_payload: dict[str, Any] = {
            "live_signal": {
                "source": "kubernetes",
                "watcher_name": self.name,
                "deployment_name": target.deployment_name,
                "namespace": target.namespace,
                "kube_context": target.kube_context,
            },
            "steering_mode": "interruptible_auto",
        }

        if self.correlator is not None:
            correlation = self.correlator.correlate(
                deployment_name=target.deployment_name,
                namespace=target.namespace,
                service=target.deployment_name,
                error_signature=error_sig,
            )
            if correlation.correlation_type != "none":
                correlation_payload = correlation.to_dict()
                run_payload["live_signal"]["correlation"] = correlation_payload
                run_payload["live_signal"]["correlation_key"] = _correlation_key(correlation_payload)
                run_payload["live_signal"]["co_signatures"] = sorted(
                    set(correlation_payload.get("signatures", [])) | {error_sig}
                )

        run = self.coordinator.create_run(run_payload)

        entry.last_run_id = run.get("run_id")
        entry.active_run_id = run.get("run_id")
        entry.last_run_time = time.monotonic()
        entry.last_error_signature = error_sig
        self._runs_created += 1
        _LOG.info(
            "KubernetesWatcher %r created run %s for %s/%s (signature=%s)",
            self.name,
            run.get("run_id"),
            target.namespace,
            target.deployment_name,
            error_sig,
        )

    # ------------------------------------------------------------------
    # Signal classification
    # ------------------------------------------------------------------

    @staticmethod
    def _is_actionable(signal: dict[str, Any]) -> bool:
        return kubernetes_signal_is_actionable(signal)

    @staticmethod
    def _extract_error_signature(signal: dict[str, Any]) -> str:
        pods = signal.get("pods", [])
        parts: list[str] = []
        for pod in pods:
            status = pod.get("container_status", "")
            if status and status != "Running":
                parts.append(status)
            reason = pod.get("last_state_reason", "")
            if reason:
                parts.append(reason)
        return "|".join(sorted(set(parts))) or "healthy"


def _correlation_key(correlation: dict[str, Any]) -> str:
    services = ",".join(str(s) for s in correlation.get("affected_services", []))
    return f"{correlation.get('type', 'none')}:{services}"
