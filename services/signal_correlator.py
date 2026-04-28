"""Cross-signal correlation engine for detecting cascading and blast-wave failures.

Today each signal is processed independently.  If three deployments in the same
namespace degrade within two minutes, the system creates three independent runs.
The SignalCorrelator maintains a sliding time window of recent signals and
produces a ``CorrelationContext`` that the watch daemon attaches to each run.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CorrelationContext:
    """Summarises how a new signal relates to recent signals in the window."""

    correlation_type: str  # none | same_namespace | cascading | blast_wave
    affected_services: list[str] = field(default_factory=list)
    correlated_signals: list[dict[str, Any]] = field(default_factory=list)
    correlation_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.correlation_type,
            "affected_services": self.affected_services,
            "correlated_signal_count": len(self.correlated_signals),
            "correlated_signals": list(self.correlated_signals),
            "signatures": sorted(
                {
                    str(signal.get("error_signature"))
                    for signal in self.correlated_signals
                    if signal.get("error_signature")
                }
            ),
            "correlation_confidence": self.correlation_confidence,
        }


@dataclass
class _SignalRecord:
    """An entry in the sliding time window."""

    timestamp: float
    deployment_name: str
    namespace: str
    service: str
    error_signature: str


class SignalCorrelator:
    """Maintains a sliding time window and detects correlated failures."""

    def __init__(
        self,
        window_seconds: int = 300,
        min_signals: int = 2,
    ) -> None:
        self.window_seconds = max(window_seconds, 10)
        self.min_signals = max(min_signals, 2)
        self._lock = threading.Lock()
        self._window: list[_SignalRecord] = []

    def correlate(
        self,
        deployment_name: str,
        namespace: str,
        service: str,
        error_signature: str,
    ) -> CorrelationContext:
        now = time.monotonic()
        record = _SignalRecord(
            timestamp=now,
            deployment_name=deployment_name,
            namespace=namespace,
            service=service,
            error_signature=error_signature,
        )
        with self._lock:
            self._prune(now)
            self._window.append(record)
            return self._analyse(record)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._window = [r for r in self._window if r.timestamp >= cutoff]

    def _analyse(self, current: _SignalRecord) -> CorrelationContext:
        others = [r for r in self._window if r is not current]
        if not others:
            return CorrelationContext(correlation_type="none")

        same_namespace = [r for r in others if r.namespace == current.namespace and r.deployment_name != current.deployment_name]
        different_namespace = [r for r in others if r.namespace != current.namespace]

        all_services = {current.service}
        for r in others:
            all_services.add(r.service)

        # Blast wave: 3+ services across namespaces degraded
        cross_ns_services = {r.service for r in different_namespace}
        total_affected = len(all_services)
        if total_affected >= 3 and len(cross_ns_services) >= 1:
            return CorrelationContext(
                correlation_type="blast_wave",
                affected_services=sorted(all_services),
                correlated_signals=[_record_to_dict(r) for r in others],
                correlation_confidence=min(0.9, 0.5 + 0.1 * total_affected),
            )

        # Same namespace: 2+ deployments in same namespace
        if len(same_namespace) >= self.min_signals - 1:
            ns_services = {current.service} | {r.service for r in same_namespace}
            return CorrelationContext(
                correlation_type="same_namespace",
                affected_services=sorted(ns_services),
                correlated_signals=[_record_to_dict(r) for r in same_namespace],
                correlation_confidence=min(0.8, 0.4 + 0.15 * len(same_namespace)),
            )

        # Cascading: any other signal in the window (different deployment)
        other_deployments = [r for r in others if r.deployment_name != current.deployment_name]
        if other_deployments:
            cascade_services = {current.service} | {r.service for r in other_deployments}
            return CorrelationContext(
                correlation_type="cascading",
                affected_services=sorted(cascade_services),
                correlated_signals=[_record_to_dict(r) for r in other_deployments],
                correlation_confidence=0.5,
            )

        return CorrelationContext(correlation_type="none")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "window_seconds": self.window_seconds,
                "min_signals": self.min_signals,
                "signals_in_window": len(self._window),
            }


def _record_to_dict(r: _SignalRecord) -> dict[str, Any]:
    return {
        "deployment_name": r.deployment_name,
        "namespace": r.namespace,
        "service": r.service,
        "error_signature": r.error_signature,
    }
