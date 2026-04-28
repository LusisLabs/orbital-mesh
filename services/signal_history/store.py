"""Per-target signal history store + trend extraction.

# Why this exists

Mesh's decision pipeline was tick-stateless: each signal envelope landed,
got triaged, produced a decision, and was forgotten. That meant the engine
genuinely couldn't tell:

* "peer_count just dipped to 1 once" (transient — usually fine) from
* "peer_count has been at 1 for the last 5 ticks" (real partition forming).

Both look identical at the snapshot level. The current policy escalates on
both, which burns operator trust on the transients and is correct only
incidentally on the real cascades.

# What this gives the engine

A bounded per-target ring buffer of recent ``EventEnvelope`` payloads, plus
a ``Trend`` extractor that pulls a (timestamp, value) series at any JSON
path and exposes statistics + duration predicates. The decision service
and the LLM observer both query the same store; agreement on what
"sustained" means is enforced by passing the same predicates to both.

# Generality

The store doesn't know about reth vs k8s vs otel. It stores envelopes by
``target_id`` — a string the caller provides. ``derive_target_id`` is the
one signal-type-specific bit, and it's a small dispatch table over
``signal_type``. Adding a new signal type means adding one branch there;
no changes to the store itself.

# Storage backing

Two layers, mirroring ``AlertStore``:

* **In-memory ring buffer** per target — fast O(1) append, O(N) trend scan.
  Bounded by ``records_per_target`` (default 60 ≈ 1 hour at 60s ticks).
* **JSONL on disk** under ``<state_dir>/signal_history/<target_id>/events.jsonl``,
  append-only with file locking. Lets a Mesh restart hydrate a few minutes
  of warm context instead of starting cold.

Both layers are bounded — the in-memory tail is fixed; the on-disk log
prunes lines older than ``retention_seconds`` on each load (lazy GC, not
a separate sweeper).

# Concurrency

Single ``threading.Lock`` for the in-memory tail dict. Watcher threads
write; the decision service reads. Read holds the lock long enough to
copy out the slice it needs, releases, then reasons over the copy.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Iterable

try:
    import fcntl  # type: ignore[import-not-found]
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover — non-POSIX platforms
    _HAS_FCNTL = False


_LOG = logging.getLogger("mesh.signal_history")

DEFAULT_RECORDS_PER_TARGET = 60
DEFAULT_MAX_TARGETS = 1024
DEFAULT_RETENTION_SECONDS = 3600  # 1 hour rolling window


@dataclass
class SignalRecord:
    """One envelope, stored. Decoupled from ``EventEnvelope`` so the store
    can outlive schema migrations of the envelope itself.

    ``observed_at`` is the wall-clock at the *signal source* — pulled from
    the envelope's ``emitted_at`` field. We use it for both retention and
    trend windowing, so trend math is grounded in observation time, not
    in when Mesh got around to processing the signal.
    """

    target_id: str
    signal_type: str
    observed_at: datetime
    payload: dict[str, Any]
    summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = dict(asdict(self))
        d["observed_at"] = self.observed_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SignalRecord":
        observed_at = raw["observed_at"]
        if isinstance(observed_at, str):
            observed_at = _parse_iso(observed_at)
        return cls(
            target_id=str(raw["target_id"]),
            signal_type=str(raw["signal_type"]),
            observed_at=observed_at,
            payload=dict(raw.get("payload") or {}),
            summary=dict(raw["summary"]) if raw.get("summary") else None,
        )


@dataclass
class Trend:
    """A (timestamp, value) series extracted at a JSON path across a window.

    The class is deliberately stat-rich and predicate-rich rather than
    forcing every caller to compute its own min/max/duration math. The
    decision service and the LLM observer both want compact summaries
    in slightly different shapes; ``to_summary`` returns one canonical
    view that both can share.
    """

    target_id: str
    path: str
    window_start: datetime
    window_end: datetime
    samples: list[tuple[datetime, Any]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def numeric_values(self) -> list[float]:
        out: list[float] = []
        for _, v in self.samples:
            if isinstance(v, bool):
                # Booleans are technically numeric in Python; we intentionally
                # exclude them — caller should use boolean predicates instead.
                continue
            if isinstance(v, (int, float)):
                out.append(float(v))
        return out

    @property
    def current(self) -> Any:
        return self.samples[-1][1] if self.samples else None

    @property
    def min(self) -> float | None:
        nums = self.numeric_values
        return min(nums) if nums else None

    @property
    def max(self) -> float | None:
        nums = self.numeric_values
        return max(nums) if nums else None

    @property
    def mean(self) -> float | None:
        nums = self.numeric_values
        return statistics.fmean(nums) if nums else None

    @property
    def p95(self) -> float | None:
        nums = self.numeric_values
        if not nums:
            return None
        if len(nums) == 1:
            return nums[0]
        return statistics.quantiles(sorted(nums), n=20)[18]  # ~95th percentile

    @property
    def is_monotonic_decreasing(self) -> bool:
        nums = self.numeric_values
        return len(nums) >= 2 and all(a >= b for a, b in zip(nums, nums[1:]))

    @property
    def is_monotonic_increasing(self) -> bool:
        nums = self.numeric_values
        return len(nums) >= 2 and all(a <= b for a, b in zip(nums, nums[1:]))

    def duration_at_or_below(self, threshold: float) -> timedelta:
        """How long has the value continuously been ≤ threshold, counting
        backward from the most recent sample?

        Returns ``timedelta(0)`` if the most recent sample is above the
        threshold (the condition isn't currently true), or if no numeric
        samples are available. This is the predicate the rule ladder
        wants: "has peer_count been ≤ 2 for 240 seconds?"
        """
        return self._tail_duration(lambda v: v <= threshold)

    def duration_at_or_above(self, threshold: float) -> timedelta:
        """Symmetric companion. "Has engine_api_p99_ms been ≥ 4000 for 180s?" """
        return self._tail_duration(lambda v: v >= threshold)

    def duration_equal_to(self, expected: Any) -> timedelta:
        """Non-numeric variant. "Has rollout_status been 'failed' for N seconds?"
        Compares with ``==`` so it works for booleans, strings, ints alike."""
        return self._tail_duration_generic(lambda v: v == expected)

    def _tail_duration(self, predicate) -> timedelta:
        """Walk backward from the most-recent sample; while each numeric
        sample satisfies ``predicate``, extend the duration. Stop at the
        first violation. Returns the span between the earliest qualifying
        sample and the most recent one (zero if the tail doesn't qualify).
        """
        if not self.samples:
            return timedelta(0)
        latest_ts, latest_v = self.samples[-1]
        if not isinstance(latest_v, (int, float)) or isinstance(latest_v, bool):
            return timedelta(0)
        if not predicate(float(latest_v)):
            return timedelta(0)
        # Walk backward while the predicate continues to hold.
        earliest_ts = latest_ts
        for ts, v in reversed(self.samples[:-1]):
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                break
            if not predicate(float(v)):
                break
            earliest_ts = ts
        return latest_ts - earliest_ts

    def _tail_duration_generic(self, predicate) -> timedelta:
        if not self.samples:
            return timedelta(0)
        latest_ts, latest_v = self.samples[-1]
        if not predicate(latest_v):
            return timedelta(0)
        earliest_ts = latest_ts
        for ts, v in reversed(self.samples[:-1]):
            if not predicate(v):
                break
            earliest_ts = ts
        return latest_ts - earliest_ts

    def to_summary(self) -> dict[str, Any]:
        """Compact dict suitable for the LLM observer prompt. Skips noisy
        derived stats when there's < 2 samples — at one sample we have a
        snapshot, not a trend, and the LLM should know that."""
        out: dict[str, Any] = {
            "path": self.path,
            "window_seconds": int((self.window_end - self.window_start).total_seconds()),
            "count": self.count,
            "current": self.current,
        }
        if self.count >= 2 and self.numeric_values:
            out["min"] = self.min
            out["max"] = self.max
            out["mean"] = round(self.mean, 4) if self.mean is not None else None
            if self.is_monotonic_decreasing:
                out["trend"] = "decreasing"
            elif self.is_monotonic_increasing:
                out["trend"] = "increasing"
            else:
                out["trend"] = "fluctuating"
        return out


# ---------------------------------------------------------------------- store


class SignalHistoryStore:
    """Bounded per-target signal history with on-disk persistence.

    Thread-safe: a single lock guards the in-memory tail dict. Reads copy
    out the slice they need under the lock and reason over the copy
    outside, so contention is minimal.
    """

    def __init__(
        self,
        state_directory: str | Path | None = None,
        *,
        records_per_target: int = DEFAULT_RECORDS_PER_TARGET,
        max_targets: int = DEFAULT_MAX_TARGETS,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
        persist: bool = True,
    ):
        self.records_per_target = records_per_target
        self.max_targets = max_targets
        self.retention_seconds = retention_seconds
        self._persist = persist and state_directory is not None
        self.root: Path | None = None
        if self._persist:
            self.root = Path(state_directory) / "signal_history"
            self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tails: dict[str, Deque[SignalRecord]] = {}
        # LRU-ish eviction: maintain insertion order so the oldest
        # *most-recently-written* target gets dropped if we exceed
        # ``max_targets``. Python dicts preserve insertion order since
        # 3.7, which is exactly the behavior we want.

    # ------------------------------------------------------------- write

    def add(self, record: SignalRecord) -> None:
        """Append a record to the target's tail. Evicts the LRU target if
        we'd exceed ``max_targets``."""
        with self._lock:
            tail = self._tails.get(record.target_id)
            if tail is None:
                if len(self._tails) >= self.max_targets:
                    # Evict the least-recently-touched target.
                    evicted_id, _ = next(iter(self._tails.items()))
                    del self._tails[evicted_id]
                    _LOG.info("signal_history: evicted target %s (cap %d)", evicted_id, self.max_targets)
                tail = deque(maxlen=self.records_per_target)
                self._tails[record.target_id] = tail
            else:
                # Touch — re-insert so it moves to the end of the LRU order.
                self._tails[record.target_id] = self._tails.pop(record.target_id)
                tail = self._tails[record.target_id]
            tail.append(record)

        if self._persist:
            self._persist_record(record)

    def _persist_record(self, record: SignalRecord) -> None:
        assert self.root is not None
        target_dir = self.root / _safe_dir_name(record.target_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "events.jsonl"
        line = json.dumps(record.to_dict(), sort_keys=True) + "\n"
        try:
            with path.open("a", encoding="utf-8") as handle:
                if _HAS_FCNTL:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    handle.write(line)
                    handle.flush()
                finally:
                    if _HAS_FCNTL:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            # Persistence is best-effort. A disk error must not break the
            # in-memory path the decision service relies on.
            _LOG.warning("signal_history: persist failed for %s: %s", record.target_id, exc)

    # ------------------------------------------------------------- read

    def recent(
        self,
        target_id: str,
        *,
        seconds: int | None = None,
        ticks: int | None = None,
    ) -> list[SignalRecord]:
        """Return records for the target. ``seconds`` filters by
        ``observed_at``; ``ticks`` slices the most-recent N. If both are
        None the full tail is returned."""
        with self._lock:
            tail = self._tails.get(target_id)
            if not tail:
                return []
            records = list(tail)
        if seconds is not None:
            cutoff = _utcnow() - timedelta(seconds=seconds)
            records = [r for r in records if r.observed_at >= cutoff]
        if ticks is not None:
            records = records[-ticks:]
        return records

    def trend(
        self,
        target_id: str,
        path: str,
        *,
        window_seconds: int = 600,
    ) -> Trend:
        """Extract (timestamp, value) samples at ``path`` across the window.

        Returns an empty ``Trend`` (count=0) if the target is unknown or no
        record in the window has the path. Callers should check ``count``
        before relying on the predicates."""
        records = self.recent(target_id, seconds=window_seconds)
        now = _utcnow()
        window_start = now - timedelta(seconds=window_seconds)
        samples: list[tuple[datetime, Any]] = []
        for record in records:
            value = _extract_path(record.payload, path)
            if value is None:
                continue
            samples.append((record.observed_at, value))
        return Trend(
            target_id=target_id,
            path=path,
            window_start=window_start,
            window_end=now,
            samples=samples,
        )

    def hydrate_from_disk(self, target_id: str | None = None) -> int:
        """Replay JSONL into the in-memory tail. Optional — Mesh works
        from cold; this just shortens the warm-up window after a restart.

        Returns the count of records loaded."""
        if not self._persist or self.root is None or not self.root.exists():
            return 0
        cutoff = _utcnow() - timedelta(seconds=self.retention_seconds)
        loaded = 0
        targets: Iterable[Path]
        if target_id is not None:
            targets = [self.root / _safe_dir_name(target_id)]
        else:
            targets = [p for p in self.root.iterdir() if p.is_dir()]
        for target_dir in targets:
            events_path = target_dir / "events.jsonl"
            if not events_path.exists():
                continue
            try:
                lines = events_path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                _LOG.warning("signal_history: hydrate read failed for %s: %s", target_dir, exc)
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip corrupt lines silently — best effort
                try:
                    record = SignalRecord.from_dict(raw)
                except (KeyError, TypeError, ValueError):
                    continue
                if record.observed_at < cutoff:
                    continue  # outside retention window
                with self._lock:
                    tail = self._tails.setdefault(
                        record.target_id, deque(maxlen=self.records_per_target),
                    )
                    tail.append(record)
                loaded += 1
        return loaded


# ---------------------------------------------------------- target id derivation


def derive_target_id(envelope_or_payload: Any) -> str | None:
    """Map an ingested envelope/payload to a stable per-target key.

    Accepts either an ``EventEnvelope``-like object (with a ``payload``
    attribute) or a raw payload dict. Returns ``None`` if the signal
    type isn't recognized — callers should treat that as "skip history".

    Adding a new signal type means adding one branch here. The store
    itself is signal-agnostic.
    """
    payload = getattr(envelope_or_payload, "payload", None)
    if payload is None and isinstance(envelope_or_payload, dict):
        payload = envelope_or_payload
    if not isinstance(payload, dict):
        return None
    signal_type = payload.get("signal_type")

    if signal_type == "reth_node":
        service = payload.get("service") or "unknown"
        return f"reth:{service}"

    if signal_type == "kubernetes_deployment_issue":
        cluster = payload.get("cluster", "unknown")
        namespace = payload.get("namespace", "default")
        deployment = (payload.get("deployment") or {}).get("name") or payload.get("service", "unknown")
        return f"k8s:{cluster}:{namespace}:{deployment}"

    if signal_type == "otel_metric_regression":
        service = payload.get("service") or "unknown"
        endpoint = payload.get("endpoint") or "unknown"
        return f"otel:{service}:{endpoint}"

    # Future signal types: add a branch above. Returning None means "no
    # history" rather than crashing — better degraded path than no path.
    return None


# ---------------------------------------------------------------- internals


def _safe_dir_name(target_id: str) -> str:
    """Filesystem-safe rendering of a target_id. Colons and slashes are
    preserved logically by replacing with ``_`` so two targets that
    differ only in those characters don't collide."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", target_id)


def _extract_path(payload: dict[str, Any], dotted: str) -> Any:
    """Walk ``payload`` along the dotted path and return the leaf, or
    ``None`` if any segment is missing.

    Supports list indexing via ``[N]`` segments — e.g. ``pods.items[0].name``
    — though we don't use it in practice yet."""
    node: Any = payload
    for segment in dotted.split("."):
        if node is None:
            return None
        # Optional ``key[N]`` form
        m = re.match(r"^([^\[]+)\[(\d+)\]$", segment)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if not isinstance(node, dict):
                return None
            node = node.get(key)
            if not isinstance(node, list) or idx >= len(node):
                return None
            node = node[idx]
            continue
        if isinstance(node, dict):
            node = node.get(segment)
        else:
            return None
    return node


def _parse_iso(s: str) -> datetime:
    """Tolerant ISO-8601 parser. Handles trailing 'Z' (which Python's
    fromisoformat doesn't accept until 3.11, and even there is brittle)."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
