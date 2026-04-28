"""Generalized per-target signal history.

Every signal that flows through the ingest pipeline (reth/geth, kubernetes,
otel — any future signal type) gets recorded by target. The decision service,
hypothesis engine, and LLM observer can then query trends across the recent
window to answer questions the current snapshot can't:

* "peer_count has been below the floor for 4+ minutes" — sustained, real
* "engine_api_p99_ms slope is increasing across the last 5 ticks" — building cascade
* "this deployment crashed 3 times in the last 30 minutes" — flapping pattern

Without history every tick is judged in isolation; the engine can't tell brief
noise from sustained degradation, and every 'escalate' looks identical to every
other 'escalate'.

Public surface:

* ``SignalHistoryStore`` — bounded ring buffer per target, with optional
  on-disk persistence so a Mesh restart doesn't blank the trend window.
* ``Trend`` — extracted (timestamp, value) samples plus stats / predicates.
* ``derive_target_id`` — the only signal-type-specific bit; returns a stable
  string that namespaces (kind, identifying-tuple) so different signal types
  don't collide.
"""

from __future__ import annotations

from .store import SignalHistoryStore, SignalRecord, Trend, derive_target_id


__all__ = [
    "SignalHistoryStore",
    "SignalRecord",
    "Trend",
    "derive_target_id",
]
