"""Breakthrough-threshold accounting for incident-corpus evidence."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


REQUIRED_COVERAGE = (
    "reth",
    "geth",
    "lighthouse",
    "validator",
    "rpc_gateway",
    "indexer",
    "kubernetes_service",
)

MEASURED_DELTA_FIELDS = {
    "false_positive_reduction",
    "false_positive_reduction_pct",
    "time_to_diagnosis_reduction_seconds",
    "diagnosis_time_reduction_seconds",
    "unsafe_action_reduction",
    "unsafe_actions_prevented",
}

RETRIEVAL_IMPACT_FIELDS = {
    "retrieval_improved_decision",
    "memory_improved_decision",
    "retrieval_changed_decision",
    "retrieval_prevented_unsafe_action",
    "retrieval_reduced_diagnosis_time",
}


@dataclass(frozen=True)
class BreakthroughThresholds:
    """Minimum evidence required before claiming Breakthrough readiness."""

    row_minimum: int = 100
    row_target: int = 1000
    measured_delta_minimum: int = 1
    promotion_candidate_minimum: int = 3
    repeated_promotion_pattern_minimum: int = 1
    retrieval_improved_decision_minimum: int = 1
    required_coverage: tuple[str, ...] = REQUIRED_COVERAGE


@dataclass(frozen=True)
class BreakthroughCriterion:
    """One threshold check with observed evidence."""

    name: str
    passed: bool
    observed: int
    threshold: int
    details: dict[str, Any]


def breakthrough_threshold_report(
    rows: list[dict[str, Any]],
    *,
    thresholds: BreakthroughThresholds | None = None,
) -> dict[str, Any]:
    """Score normalized incident-corpus rows against Breakthrough criteria."""

    active_thresholds = thresholds or BreakthroughThresholds()
    qualifying_rows = [row for row in rows if _is_real_internal_row(row)]
    row_count = len(qualifying_rows)
    measured_delta_rows = [row for row in qualifying_rows if _has_measured_delta(row)]
    promotion_rows = [row for row in qualifying_rows if _is_promotion_candidate(row)]
    repeated_promotions = repeated_promotion_patterns(promotion_rows)
    coverage = coverage_counts(qualifying_rows, active_thresholds.required_coverage)
    retrieval_improved_rows = [row for row in qualifying_rows if _retrieval_improved_decision(row)]

    criteria = (
        BreakthroughCriterion(
            name="incident_volume",
            passed=row_count >= active_thresholds.row_minimum,
            observed=row_count,
            threshold=active_thresholds.row_minimum,
            details={"target": active_thresholds.row_target, "target_met": row_count >= active_thresholds.row_target},
        ),
        BreakthroughCriterion(
            name="measured_operational_reduction",
            passed=len(measured_delta_rows) >= active_thresholds.measured_delta_minimum,
            observed=len(measured_delta_rows),
            threshold=active_thresholds.measured_delta_minimum,
            details={"row_ids": _row_ids(measured_delta_rows)},
        ),
        BreakthroughCriterion(
            name="repeated_promotion",
            passed=(
                len(promotion_rows) >= active_thresholds.promotion_candidate_minimum
                and len(repeated_promotions) >= active_thresholds.repeated_promotion_pattern_minimum
            ),
            observed=len(promotion_rows),
            threshold=active_thresholds.promotion_candidate_minimum,
            details={"patterns": repeated_promotions},
        ),
        BreakthroughCriterion(
            name="cross_client_coverage",
            passed=all(coverage.get(name, 0) > 0 for name in active_thresholds.required_coverage),
            observed=sum(1 for name in active_thresholds.required_coverage if coverage.get(name, 0) > 0),
            threshold=len(active_thresholds.required_coverage),
            details={"coverage": coverage, "missing": tuple(name for name in active_thresholds.required_coverage if coverage.get(name, 0) == 0)},
        ),
        BreakthroughCriterion(
            name="retrieval_improved_live_decisions",
            passed=len(retrieval_improved_rows) >= active_thresholds.retrieval_improved_decision_minimum,
            observed=len(retrieval_improved_rows),
            threshold=active_thresholds.retrieval_improved_decision_minimum,
            details={"row_ids": _row_ids(retrieval_improved_rows)},
        ),
    )

    criteria_payload = {criterion.name: asdict(criterion) for criterion in criteria}
    return {
        "schema_version": "mesh.breakthrough_threshold_report.v1",
        "status": "breakthrough" if all(criterion.passed for criterion in criteria) else "below_threshold",
        "ready": all(criterion.passed for criterion in criteria),
        "thresholds": asdict(active_thresholds),
        "criteria": criteria_payload,
        "row_count": row_count,
        "input_row_count": len(rows),
        "promotion_candidate_count": len(promotion_rows),
        "measured_delta_count": len(measured_delta_rows),
        "retrieval_improved_decision_count": len(retrieval_improved_rows),
        "coverage": coverage,
    }


def _is_real_internal_row(row: dict[str, Any]) -> bool:
    raw_source = row.get("source")
    source = raw_source if isinstance(raw_source, dict) else {}
    environment = str(row.get("environment") or "").lower()
    return source.get("kind") == "internal_corpus" and environment in {"production", "development", "testnet"}


def _is_promotion_candidate(row: dict[str, Any]) -> bool:
    fact = row.get("training_fact")
    return isinstance(fact, dict) and fact.get("promotion_candidate") is True


def _has_measured_delta(row: dict[str, Any]) -> bool:
    for payload in _measurement_payloads(row):
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in MEASURED_DELTA_FIELDS and _positive_number(value):
                return True
    return False


def _retrieval_improved_decision(row: dict[str, Any]) -> bool:
    for key, value in _walk_items(row):
        normalized = str(key).lower()
        if normalized in RETRIEVAL_IMPACT_FIELDS and value is True:
            return True
    return False


def _measurement_payloads(row: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for _, value in _walk_items(row):
        if isinstance(value, dict):
            key_set = {str(key).lower() for key in value}
            if "measurements" in key_set or key_set & MEASURED_DELTA_FIELDS or key_set & RETRIEVAL_IMPACT_FIELDS:
                payloads.append(value)
            nested = value.get("measurements")
            if isinstance(nested, dict):
                payloads.append(nested)
    return payloads


def coverage_counts(rows: list[dict[str, Any]], required: tuple[str, ...] = REQUIRED_COVERAGE) -> dict[str, int]:
    """Count normalized Breakthrough coverage labels across corpus rows."""

    counts = {name: 0 for name in required}
    for row in rows:
        labels = normalize_coverage_labels(row)
        for name in required:
            if name in labels:
                counts[name] += 1
    return counts


def normalize_coverage_labels(row: dict[str, Any]) -> set[str]:
    """Return explicit and legacy Breakthrough coverage labels for a row."""

    explicit = _explicit_coverage_labels(row)
    strings = tuple(_walk_strings(_coverage_scan_payload(row)))
    text = " ".join(strings).lower()
    tokens = set(re.split(r"[^a-z0-9]+", text))
    labels: set[str] = set(explicit)
    if "reth" in tokens:
        labels.add("reth")
    if "geth" in tokens:
        labels.add("geth")
    if "lighthouse" in tokens:
        labels.add("lighthouse")
    if "validator" in tokens or "validators" in tokens or "missed_attestations" in text:
        labels.add("validator")
    if "rpc_gateway" in text or ("rpc" in tokens and ("gateway" in tokens or "gateway" in text)):
        labels.add("rpc_gateway")
    if "indexer" in tokens or "indexers" in tokens or "indexing_lag" in text:
        labels.add("indexer")
    if "kubernetes_service" in text or "kubernetes" in tokens or "k8s" in tokens:
        labels.add("kubernetes_service")
    return labels


def repeated_promotion_patterns(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Return repeated promotion patterns keyed by target/profile/decision."""

    return {key: count for key, count in promotion_pattern_counts(rows).items() if count >= 2}


def promotion_pattern_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count promotion patterns keyed by target/profile/decision."""

    counts: dict[str, int] = {}
    for row in rows:
        raw_fact = row.get("training_fact")
        raw_source = row.get("source")
        fact = raw_fact if isinstance(raw_fact, dict) else {}
        source = raw_source if isinstance(raw_source, dict) else {}
        profile = source.get("profile") or _first_label(row, "fault_profile") or "unknown_profile"
        decision_type = fact.get("decision_type") or "unknown_decision"
        target = row.get("target_class") or "unknown_target"
        key = f"{target}:{profile}:{decision_type}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _explicit_coverage_labels(row: dict[str, Any]) -> set[str]:
    raw_labels = row.get("labels")
    labels = raw_labels if isinstance(raw_labels, dict) else {}
    raw = labels.get("coverage")
    values: list[Any]
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list | tuple | set):
        values = list(raw)
    else:
        values = []
    normalized = {str(value).strip().lower().replace("-", "_") for value in values if str(value).strip()}
    return {value for value in normalized if value in REQUIRED_COVERAGE}


def _coverage_scan_payload(row: dict[str, Any]) -> dict[str, Any]:
    raw_envelope = row.get("evidence_envelope")
    envelope: dict[str, Any] = raw_envelope if isinstance(raw_envelope, dict) else {}
    return {
        "service": row.get("service"),
        "target_class": row.get("target_class"),
        "labels": row.get("labels"),
        "inbound_signal": envelope.get("inbound_signal"),
        "current_probe_pack": envelope.get("current_probe_pack"),
        "topology_context": envelope.get("topology_context"),
        "node": row.get("node"),
    }


def _first_label(row: dict[str, Any], name: str) -> str | None:
    labels = row.get("labels")
    if isinstance(labels, dict):
        value = labels.get(name)
        if value is not None:
            return str(value)
    return None


def _row_ids(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(str(row.get("row_id")) for row in rows[:20] if row.get("row_id"))


def _positive_number(value: Any) -> bool:
    return isinstance(value, int | float) and value > 0


def _walk_items(value: Any) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            items.append((str(key), nested))
            items.extend(_walk_items(nested))
    elif isinstance(value, list | tuple):
        for nested in value:
            items.extend(_walk_items(nested))
    return items


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, nested in value.items():
            strings.append(str(key))
            strings.extend(_walk_strings(nested))
        return strings
    if isinstance(value, list | tuple):
        strings = []
        for nested in value:
            strings.extend(_walk_strings(nested))
        return strings
    return []
