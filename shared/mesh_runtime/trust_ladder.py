"""Per-(action_class, service) trust ladder.

Tracks, per action class × service pair, the learned autonomy level.

Levels:
    suggest  — the agent writes the hypothesis to the run log; humans act.
    draft    — the agent proposes a concrete decision; human approves before actuation.
    approve  — the agent executes unless a human cancels within a grace window.
    auto     — the agent executes; humans review after the fact.

Graduation:
    suggest → draft   when runs ≥ MIN_DRAFT_RUNS   and success_rate ≥ 0.5
    draft   → approve when runs ≥ MIN_APPROVE_RUNS and success_rate ≥ 0.7
    approve → auto    when runs ≥ MIN_AUTO_RUNS    and success_rate ≥ 0.85

Demotion:
    After 2 consecutive failures (outcome != "successful"), drop one level.

Human overrides via steering remain available; they bypass the ladder without
affecting its tracked stats (annotated ``override=True``).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .json_store import LockedJsonFile


TRUST_LEVELS = ("suggest", "draft", "approve", "auto")

_LEVEL_ORDER = {level: idx for idx, level in enumerate(TRUST_LEVELS)}
_RATIONALE_FIELDS = {
    "next_level",
    "autonomy_ceiling_reason",
    "promotion_blockers",
    "promotion_requirements",
}


class TrustLadder:
    """File-locked JSON-backed per-(action_class, service) trust ladder."""

    def __init__(
        self,
        state_directory: str | Path,
        *,
        min_draft_runs: int = 3,
        min_approve_runs: int = 10,
        min_auto_runs: int = 30,
        draft_success_rate: float = 0.5,
        approve_success_rate: float = 0.7,
        auto_success_rate: float = 0.85,
    ) -> None:
        self._dir = Path(state_directory) / "learning"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "trust_ladder.json"
        self.min_draft_runs = min_draft_runs
        self.min_approve_runs = min_approve_runs
        self.min_auto_runs = min_auto_runs
        self.draft_success_rate = draft_success_rate
        self.approve_success_rate = approve_success_rate
        self.auto_success_rate = auto_success_rate
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_level(self, action_class: str, service: str) -> str:
        entry = self._get_entry(action_class, service)
        return entry["level"] if entry else "suggest"

    def get_entry(self, action_class: str, service: str) -> dict[str, Any]:
        entry = self._get_entry(action_class, service)
        return self._annotate_entry(entry or _default_entry(action_class, service))

    def list_entries(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with LockedJsonFile(self._path) as payload:
            return [self._annotate_entry(entry) for entry in payload.get("ladder", {}).values()]

    def _get_entry(self, action_class: str, service: str) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        key = _entry_key(action_class, service)
        with LockedJsonFile(self._path) as payload:
            return payload.get("ladder", {}).get(key)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        action_class: str,
        service: str,
        outcome: str,
        *,
        override: bool = False,
    ) -> dict[str, Any]:
        """Record a single-run outcome. Returns the updated entry.

        If ``override=True``, the run bypassed the ladder (operator override)
        and does not affect counts.
        """
        key = _entry_key(action_class, service)
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            with LockedJsonFile(self._path) as payload:
                ladder = payload.setdefault("ladder", {})
                entry = ladder.get(key) or _default_entry(action_class, service)
                if override:
                    entry["last_override_at"] = now
                    entry["override_count"] = int(entry.get("override_count", 0)) + 1
                    ladder[key] = _persisted_entry(entry)
                    return self._annotate_entry(entry)

                entry["total_runs"] = int(entry.get("total_runs", 0)) + 1
                if outcome == "successful":
                    entry["successful_runs"] = int(entry.get("successful_runs", 0)) + 1
                    entry["consecutive_failures"] = 0
                else:
                    entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
                entry["last_outcome"] = outcome
                entry["last_outcome_at"] = now
                entry["success_rate"] = _round(
                    entry["successful_runs"] / entry["total_runs"]
                    if entry["total_runs"] > 0 else 0.0
                )

                # Apply graduation / demotion rules
                new_level = self._compute_level(entry)
                if new_level != entry["level"]:
                    entry["level"] = new_level
                    entry["last_level_change_at"] = now
                    if _LEVEL_ORDER[new_level] > _LEVEL_ORDER.get(entry.get("previous_level", "suggest"), 0):
                        entry["promotion_count"] = int(entry.get("promotion_count", 0)) + 1
                    else:
                        entry["demotion_count"] = int(entry.get("demotion_count", 0)) + 1
                    entry["previous_level"] = new_level

                ladder[key] = _persisted_entry(entry)
                return self._annotate_entry(entry)

    def _compute_level(self, entry: dict[str, Any]) -> str:
        # Demote first on consecutive failures
        if entry.get("consecutive_failures", 0) >= 2:
            current_idx = _LEVEL_ORDER.get(entry.get("level", "suggest"), 0)
            return TRUST_LEVELS[max(0, current_idx - 1)]

        total = entry.get("total_runs", 0)
        rate = entry.get("success_rate", 0.0)
        if total >= self.min_auto_runs and rate >= self.auto_success_rate:
            return "auto"
        if total >= self.min_approve_runs and rate >= self.approve_success_rate:
            return "approve"
        if total >= self.min_draft_runs and rate >= self.draft_success_rate:
            return "draft"
        return "suggest"

    def override_level(
        self,
        action_class: str,
        service: str,
        level: str,
        *,
        reason: str = "operator_override",
    ) -> dict[str, Any]:
        """Force a level (manual operator action). Persists until next promotion/demotion."""
        if level not in _LEVEL_ORDER:
            raise ValueError(f"unknown trust level: {level!r}")
        key = _entry_key(action_class, service)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with LockedJsonFile(self._path) as payload:
                ladder = payload.setdefault("ladder", {})
                entry = ladder.get(key) or _default_entry(action_class, service)
                entry["level"] = level
                entry["last_level_change_at"] = now
                entry["manual_override_reason"] = reason
                ladder[key] = _persisted_entry(entry)
                return self._annotate_entry(entry)

    def _annotate_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        annotated = dict(entry)
        current = str(annotated.get("level") or "suggest")
        next_level = _next_level(current)
        annotated["next_level"] = next_level

        requirements = self._requirements_for(next_level)
        annotated["promotion_requirements"] = requirements

        blockers: list[str] = []
        total_runs = int(annotated.get("total_runs") or 0)
        success_rate = float(annotated.get("success_rate") or 0.0)
        consecutive_failures = int(annotated.get("consecutive_failures") or 0)
        if next_level:
            required_runs = int(requirements["min_runs"])
            required_rate = float(requirements["min_success_rate"])
            if total_runs < required_runs:
                blockers.append(f"{required_runs - total_runs} more successful or reviewed runs before {next_level}")
            if success_rate < required_rate:
                blockers.append(f"success rate {success_rate:.0%} below {required_rate:.0%} for {next_level}")
            if consecutive_failures > 0:
                blockers.append(f"{consecutive_failures} recent failure(s) must be cleared by successful feedback")
        if annotated.get("manual_override_reason"):
            blockers.append(f"manual override: {annotated['manual_override_reason']}")
        annotated["promotion_blockers"] = blockers

        if current == "auto":
            reason = "auto ceiling reached; production authority still requires policy, allowlist, evaluation, approval-mode, and rollback gates"
        elif blockers:
            reason = "; ".join(blockers)
        elif next_level:
            reason = f"eligible for {next_level} after the next successful feedback update"
        else:
            reason = "no higher autonomy level is defined"
        annotated["autonomy_ceiling_reason"] = reason
        return annotated

    def _requirements_for(self, level: str | None) -> dict[str, Any]:
        if level == "draft":
            return {"min_runs": self.min_draft_runs, "min_success_rate": self.draft_success_rate}
        if level == "approve":
            return {"min_runs": self.min_approve_runs, "min_success_rate": self.approve_success_rate}
        if level == "auto":
            return {"min_runs": self.min_auto_runs, "min_success_rate": self.auto_success_rate}
        return {"min_runs": 0, "min_success_rate": 0.0}


# ----------------------------------------------------------------------


def _entry_key(action_class: str, service: str) -> str:
    return f"{action_class}::{service}"


def _next_level(level: str) -> str | None:
    idx = _LEVEL_ORDER.get(level, 0)
    if idx >= len(TRUST_LEVELS) - 1:
        return None
    return TRUST_LEVELS[idx + 1]


def _persisted_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key not in _RATIONALE_FIELDS}


def _default_entry(action_class: str, service: str) -> dict[str, Any]:
    return {
        "action_class": action_class,
        "service": service,
        "level": "suggest",
        "previous_level": "suggest",
        "total_runs": 0,
        "successful_runs": 0,
        "success_rate": 0.0,
        "consecutive_failures": 0,
        "promotion_count": 0,
        "demotion_count": 0,
        "override_count": 0,
        "last_outcome": None,
        "last_outcome_at": None,
        "last_level_change_at": None,
    }


def _round(value: float) -> float:
    return round(float(value), 3)
