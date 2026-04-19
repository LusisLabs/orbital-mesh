"""Continuous Kubernetes deployment watcher that auto-generates remediation signals."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from shared.mesh_runtime.watch_protocol import RunCoordinatorLike, SignalCorrelatorLike

_LOG = logging.getLogger("mesh.watch_daemon")


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


class WatchDaemon:
    def __init__(
        self,
        coordinator: RunCoordinatorLike,
        targets: list[WatchTarget],
        interval_seconds: int = 60,
        default_cooldown_seconds: int = 300,
        correlator: SignalCorrelatorLike | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.targets = list(targets)
        self.interval_seconds = max(interval_seconds, 10)
        self.default_cooldown_seconds = default_cooldown_seconds
        self.correlator = correlator
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._dedup: dict[tuple[str, str], _DeduplicationEntry] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="mesh-watch-daemon",
        )
        self._thread.start()
        _LOG.info(
            "Watch daemon started with %d target(s), interval=%ds",
            len(self.targets),
            self.interval_seconds,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "targets": [
                {
                    "deployment_name": t.deployment_name,
                    "namespace": t.namespace,
                    "kube_context": t.kube_context,
                }
                for t in self.targets
            ],
            "interval_seconds": self.interval_seconds,
            "dedup_entries": len(self._dedup),
        }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            for target in self.targets:
                if self._stop_event.is_set():
                    break
                try:
                    self._poll_target(target)
                except Exception:
                    _LOG.exception(
                        "Watch daemon error polling %s/%s",
                        target.namespace,
                        target.deployment_name,
                    )
            self._stop_event.wait(timeout=self.interval_seconds)

    def _poll_target(self, target: WatchTarget) -> None:
        dedup_key = (target.namespace, target.deployment_name)
        entry = self._dedup.setdefault(dedup_key, _DeduplicationEntry())

        if entry.active_run_id is not None:
            active_run = self.coordinator.get_run(entry.active_run_id)
            if active_run and active_run.get("status") not in (
                "completed",
                "failed",
                "cancelled",
            ):
                return
            entry.active_run_id = None

        cooldown = target.cooldown_seconds if target.cooldown_seconds is not None else self.default_cooldown_seconds
        if time.monotonic() - entry.last_run_time < cooldown:
            return

        from services.ingest.kubernetes_live_signal import collect_kubernetes_signal

        signal = collect_kubernetes_signal(
            deployment_name=target.deployment_name,
            namespace=target.namespace,
            kube_context=target.kube_context,
            kubectl_command=self.coordinator.config.kubectl_command,
        )

        if not self._is_actionable(signal):
            return

        error_sig = self._extract_error_signature(signal)
        if error_sig == entry.last_error_signature and entry.last_run_id is not None:
            return

        run_payload: dict[str, Any] = {
            "live_signal": {
                "source": "kubernetes",
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
                run_payload["live_signal"]["correlation"] = correlation.to_dict()

        run = self.coordinator.create_run(run_payload)

        entry.last_run_id = run.get("run_id")
        entry.active_run_id = run.get("run_id")
        entry.last_run_time = time.monotonic()
        entry.last_error_signature = error_sig
        _LOG.info(
            "Watch daemon created run %s for %s/%s",
            run.get("run_id"),
            target.namespace,
            target.deployment_name,
        )

    @staticmethod
    def _is_actionable(signal: dict[str, Any]) -> bool:
        deployment = signal.get("deployment", {})
        if deployment.get("rollout_status") in ("degraded", "failed"):
            return True
        pods = signal.get("pods", [])
        for pod in pods:
            if not pod.get("ready", True):
                return True
            if int(pod.get("restarts", 0)) > 0:
                return True
        return False

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
