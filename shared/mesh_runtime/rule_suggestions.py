"""Learn metric-action rules from operator overrides.

# The problem this solves

The first three decision layers (hardcoded branches, declarative rules, LLM
fallback) all require someone — an engineer, a rule author, or the LLM — to
know *in advance* what to do with a given signal. Real teams don't work that
way. An on-call engineer sees a page, looks at context the system didn't
have, and steers the decision. That moment of human judgment is the most
valuable data point in the stack, and today we throw it away.

Layer 4 captures it. Every time an operator uses ``override_decision`` or
``override_execution_parameters``, we:

1. **Fingerprint the signal** — reduce it to a stable key so "Kafka lag on
   payments in us-east" groups the same way across runs.
2. **Record the override** — what the decision engine proposed, what the
   operator changed it to, what outcome the run reached afterward.
3. **Synthesize candidate rules** — when N operators have made the same
   override ≥M times with successful outcomes, generate a rule that
   codifies their pattern.
4. **Surface suggestions** — expose candidates via the admin API so a human
   reviews, edits if needed, and approves. Suggestions never auto-apply;
   the human is the authority on which patterns to promote.

Over weeks of operation the rule catalog grows from whatever shipped in
``metric-actions.policy.json`` to whatever your team actually does when the
pager fires. This is the flywheel — Resolve.ai does this for topology via
their knowledge graph; we do it for decisions, which is arguably more
directly useful for the bounded-action model Mesh is built around.

# Fingerprinting design

A signal fingerprint must be:

* **Stable** across similar incidents. Two Kafka lag alerts on the same
  service 12 hours apart must produce the same fingerprint.
* **Specific enough** to separate different patterns. Lag on ``payments``
  and lag on ``notifications`` should not share a fingerprint unless the
  operator's override was identical — we don't want to blur signal.
* **Insensitive to noise**. Exact timestamps, pod names, IP addresses must
  not appear in the fingerprint.

We use four stable dimensions: ``metric_name`` (normalized), ``service``,
``namespace``, and the direction of regression. Everything else (values,
timestamps, pod-level attributes) is discarded. This is coarse by design —
we want more overrides to cluster, not fewer, so the synthesis threshold
fires.

# Synthesis strategy

For each fingerprint with ≥ ``min_observations`` (default 5) overrides:

1. Group the overrides by the action they proposed.
2. If ≥60% of overrides agree on the same action (majority vote), that
   becomes the suggested action.
3. For each parameter, use the median value across overrides. Median beats
   mean because operators occasionally type wrong numbers — the outliers
   shouldn't move the suggestion.
4. Filter by outcome: only include overrides that ended in ``successful``
   or ``unsuccessful`` runs (the feedback stage has labeled them). We
   exclude ``escalated`` and in-flight runs — those don't tell us whether
   the operator's instinct was right.
5. The suggestion is returned as a rule proposal (same shape as
   ``policies/metric-actions.policy.json``) ready for human review.

# Storage

Override records live alongside outcomes in the existing ``LearningStore``
file layout — JSON under ``<state_dir>/learning/overrides.json``. We reuse
the same ``_locked_json`` context manager the outcomes use, so concurrent
writes from multiple run threads are safe.
"""

from __future__ import annotations

import fcntl
import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# Keep the override log bounded so a runaway incident doesn't explode the
# file. The oldest entries roll off. 2000 is large enough to capture a full
# quarter of on-call history for most teams.
_MAX_OVERRIDES = 2000


# Metric-name normalization: strip common provider prefixes and collapse
# separators so ``kafka.consumer.lag`` and ``kafka_consumer_lag`` fingerprint
# identically. We deliberately lowercase here because OTel name casing
# varies between exporters.
_NAME_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def fingerprint_signal(signal: dict[str, Any]) -> str:
    """Produce a stable fingerprint for an OTel-style signal.

    Takes a signal view (same shape the rule matcher sees) and returns a
    short string. Keeping the string short and human-readable is useful
    when operators inspect the admin API — ``lag:payments:default:up`` is
    clearly different from ``cpu:payments:default:up`` at a glance.

    We normalize the metric name aggressively: ``kafka.consumer.lag``,
    ``consumer_lag_total``, and ``ConsumerLag`` all collapse to ``lag``.
    That's intentional — overrides on any of these variants should group
    together because from the operator's standpoint they mean the same
    thing.
    """
    metric_regression = signal.get("metric_regression") or {}
    raw_metric_name = str(metric_regression.get("metric_name") or "unknown")
    normalized_metric = _normalize_metric_name(raw_metric_name)

    service = str(signal.get("service") or "unknown")
    namespace = str(signal.get("namespace") or signal.get("resource_attributes", {}).get("k8s.namespace.name") or "default")

    observed = metric_regression.get("observed_value")
    baseline = metric_regression.get("baseline_value")
    direction = "up"
    if observed is not None and baseline is not None:
        try:
            direction = "up" if float(observed) > float(baseline) else "down"
        except (TypeError, ValueError):
            pass

    return f"{normalized_metric}:{service}:{namespace}:{direction}"


def _normalize_metric_name(name: str) -> str:
    """Collapse a metric name to the last meaningful segment.

    ``kafka.consumer.lag`` → ``lag``
    ``http_server_duration_ms`` → ``duration``
    ``node_memory_utilization_percent`` → ``utilization``

    We strip numeric-only and unit-only segments because those vary between
    exporters but don't change the signal's meaning. The result is a single
    token that captures *what* is being measured, discarding *how* it's
    labeled by the provider.
    """
    # Split camelCase first (ConsumerLag → Consumer Lag) so camelcase metric
    # names group with their snake_case and dotted equivalents. Then lowercase
    # and collapse other separators.
    camel_split = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name)
    lowered = camel_split.lower()
    # Collapse any non-alphanumeric into a single separator, then split.
    segments = [s for s in _NAME_NORMALIZE_RE.split(lowered) if s]
    # Units and numeric-only tokens provide no signal; drop them.
    _unit_tokens = {"ms", "seconds", "s", "percent", "pct", "bytes", "count", "total", "per"}
    filtered = [seg for seg in segments if not seg.isdigit() and seg not in _unit_tokens]
    if not filtered:
        return "unknown"
    # The last meaningful token is usually the "what" — "lag", "duration",
    # "utilization", "rate". This beats first-segment because providers
    # prefix their own vendor name ("aws", "kafka", "node_") which is noise.
    return filtered[-1]


@dataclass
class OverrideRecord:
    """One override observation stored in the learning log.

    Kept small — we avoid serializing the full signal because the log grows
    over time and we only need enough to reconstruct intent. The
    ``signal_fingerprint`` is our grouping key; the full signal lives in
    the run's vault entry if someone needs to dig deeper.
    """

    fingerprint: str
    recorded_at: str
    run_id: str
    original_decision_type: str
    override_decision_type: str | None
    override_parameters: dict[str, Any]
    original_parameters: dict[str, Any]
    service: str
    metric_name: str
    outcome: str | None = None  # filled in when feedback completes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleSuggestion:
    """A candidate rule synthesized from override history.

    Matches the format expected by ``metric-actions.policy.json`` — an
    operator reviewing a suggestion can paste the ``rule`` field directly
    into the policy file. ``supporting_evidence`` explains why this
    suggestion was generated so humans aren't staring at opaque output.
    """

    fingerprint: str
    rule: dict[str, Any]
    observation_count: int
    success_rate: float | None
    supporting_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OverrideLearningStore:
    """Read/write operator override records and synthesize rule suggestions.

    Parallel to ``LearningStore`` — we keep it separate because the override
    data model is different enough (keyed by fingerprint, not by service)
    that sharing storage would muddy both. Same file layout conventions,
    same locking primitive, so it's familiar to anyone already using
    ``LearningStore``.
    """

    def __init__(self, state_directory: str | Path):
        self._learning_dir = Path(state_directory) / "learning"
        self._learning_dir.mkdir(parents=True, exist_ok=True)
        self._overrides_path = self._learning_dir / "overrides.json"

    def record_override(
        self,
        *,
        signal: dict[str, Any],
        run_id: str,
        original_decision_type: str,
        override_decision_type: str | None,
        override_parameters: dict[str, Any],
        original_parameters: dict[str, Any],
    ) -> OverrideRecord:
        """Persist one override event. Fires from control_plane._apply_override.

        ``override_decision_type`` is None for ``override_execution_parameters``
        (which only changes parameters, not the decision type). ``outcome``
        is not set here — the feedback stage writes it via
        :meth:`update_override_outcome` once the run concludes.
        """
        metric_regression = signal.get("metric_regression") or {}
        record = OverrideRecord(
            fingerprint=fingerprint_signal(signal),
            recorded_at=_timestamp(),
            run_id=run_id,
            original_decision_type=original_decision_type,
            override_decision_type=override_decision_type,
            override_parameters=dict(override_parameters or {}),
            original_parameters=dict(original_parameters or {}),
            service=str(signal.get("service") or "unknown"),
            metric_name=str(metric_regression.get("metric_name") or "unknown"),
        )
        with _locked_json(self._overrides_path) as payload:
            records = payload.setdefault("overrides", [])
            records.append(record.to_dict())
            if len(records) > _MAX_OVERRIDES:
                payload["overrides"] = records[-_MAX_OVERRIDES:]
        return record

    def update_override_outcome(self, run_id: str, outcome: str) -> None:
        """Backfill the outcome on any override records for this run.

        Called from the feedback stage so the learning log knows which
        overrides led to successful runs. Without this we'd count every
        override equally, which would promote bad instincts alongside good
        ones.
        """
        with _locked_json(self._overrides_path) as payload:
            records = payload.get("overrides") or []
            for record in records:
                if record.get("run_id") == run_id and record.get("outcome") is None:
                    record["outcome"] = outcome

    def list_overrides(self, max_age_days: int | None = None) -> list[OverrideRecord]:
        """Return all override records, optionally filtered by age.

        Age filtering matters for rule suggestion — an override from 90 days
        ago on a now-deprecated metric shouldn't weigh as heavily as a fresh
        observation. 30 days is a reasonable default for most teams.
        """
        if not self._overrides_path.exists():
            return []
        with _locked_json(self._overrides_path) as payload:
            raw_records = payload.get("overrides") or []
        records: list[OverrideRecord] = []
        cutoff: datetime | None = None
        if max_age_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        for raw in raw_records:
            try:
                record = OverrideRecord(**raw)
            except TypeError:
                # Schema drift on an old record — skip rather than crash. In
                # practice this only happens if someone hand-edits the file.
                continue
            if cutoff is not None:
                recorded = _parse_timestamp(record.recorded_at)
                if recorded is None or recorded < cutoff:
                    continue
            records.append(record)
        return records

    def synthesize_suggestions(
        self,
        min_observations: int = 5,
        agreement_threshold: float = 0.6,
        max_age_days: int | None = 30,
    ) -> list[RuleSuggestion]:
        """Turn override history into candidate rule proposals.

        See the module docstring for the strategy. Returns one suggestion
        per fingerprint that meets the threshold. Returns an empty list
        when there isn't enough data — we never force suggestions out of
        thin observations.
        """
        records = self.list_overrides(max_age_days=max_age_days)
        if not records:
            return []
        by_fingerprint: dict[str, list[OverrideRecord]] = {}
        for record in records:
            by_fingerprint.setdefault(record.fingerprint, []).append(record)

        suggestions: list[RuleSuggestion] = []
        for fingerprint, group in by_fingerprint.items():
            if len(group) < min_observations:
                continue
            suggestion = self._synthesize_group(fingerprint, group, agreement_threshold)
            if suggestion is not None:
                suggestions.append(suggestion)
        # Stable ordering: by observation count desc, then fingerprint asc.
        # Operators reviewing the list see the highest-signal suggestions
        # first, which is usually what they want to act on.
        suggestions.sort(key=lambda s: (-s.observation_count, s.fingerprint))
        return suggestions

    def _synthesize_group(
        self,
        fingerprint: str,
        records: list[OverrideRecord],
        agreement_threshold: float,
    ) -> RuleSuggestion | None:
        """Produce a single RuleSuggestion from a group of same-fingerprint overrides."""
        # Tally action votes. We only consider records where the operator
        # actually proposed a decision type — "tweak parameters only" lives
        # in override_parameters and doesn't vote on the action itself.
        action_votes: dict[str, int] = {}
        for record in records:
            if record.override_decision_type:
                action_votes[record.override_decision_type] = action_votes.get(record.override_decision_type, 0) + 1
        if not action_votes:
            return None
        winning_action, winning_count = max(action_votes.items(), key=lambda pair: pair[1])
        if winning_count / len(records) < agreement_threshold:
            return None

        # Gather successful outcomes among the winning group. "successful"
        # and "rolled_back" both signal that the action worked; the latter
        # just means it also tripped a guardrail. "escalated" / "failed" /
        # None are excluded from the success numerator.
        winning_records = [r for r in records if r.override_decision_type == winning_action]
        completed = [r for r in winning_records if r.outcome is not None]
        successes = [r for r in completed if r.outcome in {"successful", "rolled_back"}]
        success_rate = (len(successes) / len(completed)) if completed else None

        # Median parameters from the winning group. Median handles both
        # numeric outliers (someone typed 100 when they meant 10) and
        # missing keys (some overrides set replicas_delta, others didn't).
        merged_parameters = _merge_parameters_by_median(winning_records)

        # Pick the first example as the metric_name template — we want the
        # actual metric name in the rule, not the fingerprint's normalized
        # form. The fingerprint groups, but the rule must match against
        # real incoming signals.
        sample = records[0]
        # Derive a reasonable pattern: the metric name literal plus an
        # anchor-relaxed wildcard so close variants match. Operators can
        # edit this before approving.
        metric_pattern = re.escape(_normalize_metric_name(sample.metric_name))

        rule = {
            "name": f"learned: {winning_action} on {fingerprint}",
            "$doc": (
                f"Synthesized from {len(winning_records)} operator overrides on signals "
                f"fingerprinted as {fingerprint!r}. Review parameter defaults before approving."
            ),
            "match": {
                "metric_name_pattern": f"({metric_pattern})",
                "direction": "increasing" if fingerprint.endswith(":up") else "decreasing",
                "delta_pct_min": 20,
            },
            "propose": {
                "decision_type": winning_action,
                "system": _infer_system_for_action(winning_action),
                "action": winning_action,
                "parameters": merged_parameters,
            },
            "bounds": _bounds_for_action(winning_action),
            "confidence": _confidence_from_success_rate(success_rate, len(winning_records)),
            "risk_level": "medium",
            "rollback_plan": f"undo the last {winning_action} action and escalate for human review",
        }

        return RuleSuggestion(
            fingerprint=fingerprint,
            rule=rule,
            observation_count=len(records),
            success_rate=success_rate,
            supporting_evidence={
                "action_votes": action_votes,
                "winning_action_count": winning_count,
                "agreement_threshold": agreement_threshold,
                "completed_outcomes": len(completed),
                "successful_outcomes": len(successes),
                "sample_run_ids": [r.run_id for r in records[:5]],
            },
        )


def _merge_parameters_by_median(records: list[OverrideRecord]) -> dict[str, Any]:
    """Merge override parameter dicts using median for numeric values, mode for strings.

    Each operator's override might set a different subset of parameters;
    we union the keys across all records and pick a representative value
    per key. Numeric medians suppress outliers; string modes pick the most
    common label.
    """
    all_keys: set[str] = set()
    for record in records:
        all_keys.update(record.override_parameters.keys())
    merged: dict[str, Any] = {}
    for key in all_keys:
        values = [r.override_parameters[key] for r in records if key in r.override_parameters]
        if not values:
            continue
        numeric_values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(numeric_values) == len(values):
            merged[key] = float(statistics.median(numeric_values))
            # Preserve integer-ness when every observation was an int — no
            # point turning ``replicas_delta: 2`` into ``2.0``.
            if all(isinstance(v, int) for v in values):
                merged[key] = int(merged[key])
        else:
            # Mode for non-numeric values. If ties, statistics.mode picks the
            # first — deterministic enough for a suggestion pipeline.
            try:
                merged[key] = statistics.mode(values)
            except statistics.StatisticsError:
                merged[key] = values[0]
    return merged


def _infer_system_for_action(action: str) -> str:
    """Best-effort mapping of an action to its execution system.

    Used for synthesized rules where the operator set a decision_type but
    the system isn't recorded on the override record. The set of valid
    actions is small enough to hardcode; anything unmapped falls back to
    audit_log_sink, which the schema allows but the orchestrator treats as
    a no-op — safer default than guessing wrong.
    """
    return {
        "scale_deployment": "kubernetes_service",
        "patch_resources": "kubernetes_service",
        "rollback_deployment": "kubernetes_service",
        "restart_deployment": "kubernetes_service",
        "disable_flag": "feature_flag_service",
        "reduce_rollout": "feature_flag_service",
        "escalate": "incident_service",
        "no_action": "audit_log_sink",
    }.get(action, "audit_log_sink")


def _bounds_for_action(action: str) -> dict[str, Any]:
    """Default safety bounds for a synthesized rule.

    These match the tighter end of what the curated starter policy uses —
    a learned rule should err on the conservative side until a human has
    reviewed it. The operator can relax bounds when approving the
    suggestion.
    """
    if action == "scale_deployment":
        return {"replicas_delta_max": 2, "cooldown_seconds": 600}
    if action == "patch_resources":
        return {"cooldown_seconds": 900}
    return {"cooldown_seconds": 300}


def _confidence_from_success_rate(success_rate: float | None, sample_size: int) -> float:
    """Map observed success rate + sample size to a confidence score.

    Small samples cap low even with 100% success — "5 of 5 worked" isn't
    the same evidence as "40 of 40 worked". We interpolate so confidence
    rises with sample size, then scale by success rate.
    """
    if success_rate is None:
        return 0.55
    # Sample-size factor: 0.5 at n=5, rising to 0.9 at n=40+.
    n_factor = min(0.9, 0.5 + (sample_size - 5) * 0.01)
    return round(max(0.5, min(0.85, n_factor * success_rate)), 2)


# ----------------------------------------------------------------- plumbing


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


class _locked_json:
    """Copy of the exclusive-locked JSON file helper from learning.py.

    Duplicated rather than imported to keep this module self-contained and
    avoid a cross-module dependency cycle between learning stores. Twenty
    lines is a small price for clean separation.
    """

    def __init__(self, path: Path):
        self.path = path
        self.handle = None
        self.payload: dict[str, Any] = {}

    def __enter__(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        self.handle.seek(0)
        raw = self.handle.read()
        self.payload = json.loads(raw) if raw.strip() else {}
        return self.payload

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        if exc_type is None:
            self.handle.seek(0)
            self.handle.truncate()
            json.dump(self.payload, self.handle, indent=2, sort_keys=True)
            self.handle.write("\n")
            self.handle.flush()
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


__all__ = [
    "OverrideLearningStore",
    "OverrideRecord",
    "RuleSuggestion",
    "fingerprint_signal",
]
