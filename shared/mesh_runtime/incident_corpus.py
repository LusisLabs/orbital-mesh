"""Normalize Mesh run artifacts into incident-corpus training rows.

Single-tenant by design. See ``corpus_store.py`` for the same caveat —
rows produced here flow into the corpus DB without a tenant predicate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .breakthrough import (
    MEASURED_DELTA_FIELDS,
    RETRIEVAL_IMPACT_FIELDS,
    normalize_coverage_labels,
    promotion_pattern_counts,
    repeated_promotion_patterns,
)


TrainingOutcome = Literal[
    "false_positive",
    "human_hold",
    "executed",
    "successful",
    "failed",
    "worsened",
    "recovered_without_action",
    "skipped",
    "unknown",
]


@dataclass(frozen=True)
class CorpusWriteResult:
    """Paths written by a corpus export operation."""

    row_paths: tuple[Path, ...]
    jsonl_path: Path
    report_path: Path
    row_count: int
    promotion_candidate_count: int


def build_incident_corpus_row(cycle_dir: Path, *, session_dir: Path | None = None) -> dict[str, Any]:
    """Build one normalized training row from a Reth/Kurtosis cycle directory."""

    cycle_dir = Path(cycle_dir)
    session_dir = Path(session_dir) if session_dir is not None else cycle_dir.parent
    summary = _read_json(cycle_dir / "summary.json", default={})
    signal_payload = _read_json(cycle_dir / "signal_payload.json", default={})
    live_signal = _read_json(cycle_dir / "live_signal.json", default={})
    signal_collection = _read_json(cycle_dir / "signal_collection.json", default={})
    run_final = _read_json(cycle_dir / "run_final.json", default={})
    if not run_final:
        run_final = _read_json(cycle_dir / "run.json", default={})
    scenario_analysis = _read_json(cycle_dir / "scenario_analysis.json", default={})
    evidence_graph = _read_json(cycle_dir / "evidence_graph.json", default={})
    merkle = _read_json(cycle_dir / "merkle.json", default={})
    events = _read_json(cycle_dir / "events.json", default={})

    artifacts = run_final.get("artifacts") if isinstance(run_final.get("artifacts"), dict) else {}
    decision = _first_dict(artifacts.get("decision"), run_final.get("decision"))
    evaluation = _first_dict(artifacts.get("evaluation"), run_final.get("evaluation"))
    execution = _first_dict(artifacts.get("execution"), run_final.get("execution"))
    feedback = _first_dict(artifacts.get("feedback"), run_final.get("feedback"))
    evidence_pack = _first_dict(
        artifacts.get("evidence_pack"),
        _nested_dict(decision, ("reasoning", "evidence_pack")),
        live_signal,
        signal_payload,
    )

    outcome = classify_training_outcome(
        summary=summary,
        run=run_final,
        decision=decision,
        evaluation=evaluation,
        execution=execution,
        feedback=feedback,
    )
    service = signal_payload.get("service") or live_signal.get("service") or _nested_dict(evidence_pack, ("node",)).get("name")
    target_class = _target_class(signal_payload, evidence_pack)
    labels = _labels(summary, signal_payload, evidence_pack, decision, evaluation, execution, feedback, outcome)
    explicit_coverage = _explicit_coverage_from_signal(summary, signal_payload, evidence_pack, target_class)
    if explicit_coverage:
        labels["coverage"] = tuple(sorted(explicit_coverage))
    coverage = normalize_coverage_labels(
        {
            "service": service,
            "target_class": target_class,
            "labels": labels,
            "evidence_envelope": {
                "inbound_signal": signal_payload,
                "current_probe_pack": evidence_pack,
                "topology_context": _topology_context(signal_payload, evidence_pack, run_final),
            },
        }
    )
    if coverage:
        labels["coverage"] = tuple(sorted(coverage))
    row: dict[str, Any] = {
        "schema_version": "mesh.incident_corpus.v1",
        "row_id": _row_id(session_dir, cycle_dir, summary, signal_payload),
        "created_at": _now_iso(),
        "source": {
            "kind": "internal_corpus",
            "collector": _collector(summary, signal_payload, live_signal),
            "session_id": session_dir.name,
            "cycle_dir": cycle_dir.name,
            "profile": summary.get("profile") or _profile_from_dir(cycle_dir),
            "cycle": summary.get("cycle"),
            "run_id": summary.get("run_id") or run_final.get("run_id"),
        },
        "domain": "crypto",
        "environment": signal_payload.get("environment") or live_signal.get("environment") or "unknown",
        "service": service,
        "target_class": target_class,
        "labels": labels,
        "evidence_envelope": {
            "inbound_signal": signal_payload,
            "current_probe_pack": evidence_pack,
            "topology_context": _topology_context(signal_payload, evidence_pack, run_final),
            "scenario_analysis": scenario_analysis,
            "decision": decision,
            "evaluation": evaluation,
            "action": execution,
            "feedback": feedback,
            "post_action_observations": _post_action_observations(signal_payload, evidence_pack, execution, feedback),
        },
        "training_fact": {
            "outcome": outcome,
            "decision_type": summary.get("decision_type") or decision.get("decision_type"),
            "evaluation_recommendation": summary.get("evaluation_recommendation") or evaluation.get("final_recommendation"),
            "execution_status": summary.get("execution_status") or execution.get("status"),
            "feedback_outcome": summary.get("feedback_outcome") or feedback.get("outcome"),
            "stage": summary.get("stage") or run_final.get("stage"),
            "status": summary.get("status") or run_final.get("status"),
            "confidence": _first_number(scenario_analysis.get("confidence"), decision.get("confidence")),
            "risk_level": scenario_analysis.get("risk_level") or _nested_dict(decision, ("risk",)).get("level"),
            "quality_measurements": _quality_measurements(summary, run_final, scenario_analysis, decision, evaluation, execution, feedback),
            "promotion_candidate": False,
            "promotion_reasons": (),
        },
        "audit": {
            "signal_collection": signal_collection,
            "evidence_graph": evidence_graph,
            "merkle": merkle,
            "run_event_count": _event_count(events),
            "artifact_files": tuple(sorted(path.name for path in cycle_dir.glob("*.json"))),
        },
    }
    promote, reasons = promotion_candidate(row)
    row["training_fact"]["promotion_candidate"] = promote
    row["training_fact"]["promotion_reasons"] = reasons
    return row


def classify_training_outcome(
    *,
    summary: dict[str, Any],
    run: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    execution: dict[str, Any],
    feedback: dict[str, Any],
) -> TrainingOutcome:
    """Classify a run into the finite outcomes used for training facts."""

    stage = str(summary.get("stage") or run.get("stage") or "")
    status = str(summary.get("status") or run.get("status") or "")
    decision_type = str(summary.get("decision_type") or decision.get("decision_type") or "")
    recommendation = str(summary.get("evaluation_recommendation") or evaluation.get("final_recommendation") or "")
    execution_status = str(summary.get("execution_status") or execution.get("status") or "")
    feedback_outcome = str(summary.get("feedback_outcome") or feedback.get("outcome") or "")

    if stage == "signal_unavailable" or status == "skipped":
        return "skipped"
    if stage == "no_trigger":
        return "false_positive"
    if feedback_outcome in {"worsened", "regressed"}:
        return "worsened"
    if feedback_outcome in {"successful", "success", "recovered"}:
        return "successful"
    if feedback_outcome in {"failed", "failure", "unsuccessful"}:
        return "failed"
    if execution_status in {"failed", "failure"}:
        return "failed"
    if execution_status in {"succeeded", "success"}:
        return "executed"
    if recommendation in {"human_review", "hold", "review"} or status == "policy_held":
        return "human_hold"
    if decision_type in {"no_action", "observe"} and stage in {"completed", "evaluation_ready"}:
        return "recovered_without_action"
    return "unknown"


def promotion_candidate(row: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return whether a row is strong enough to promote into rules/templates."""

    fact = _first_dict(row.get("training_fact"))
    envelope = _first_dict(row.get("evidence_envelope"))
    evaluation = _first_dict(envelope.get("evaluation"))
    action = _first_dict(envelope.get("action"))
    outcome = fact.get("outcome")
    reasons: list[str] = []

    if outcome != "successful":
        return False, ("outcome_not_successful",)
    if evaluation.get("passed") is not True or evaluation.get("final_recommendation") != "execute":
        return False, ("evaluation_not_execute",)
    if action.get("status") not in {"succeeded", "success"}:
        return False, ("action_not_successful",)
    confidence = fact.get("confidence")
    if isinstance(confidence, int | float) and confidence < 0.75:
        return False, ("confidence_below_0.75",)
    reasons.append("successful_feedback")
    reasons.append("evaluation_execute")
    reasons.append("action_succeeded")
    if confidence is not None:
        reasons.append("confidence_threshold_met")
    return True, tuple(reasons)


def write_cycle_corpus_artifacts(cycle_dir: Path, *, session_dir: Path | None = None) -> dict[str, Any]:
    """Write ``corpus_row.json`` for one cycle and refresh session corpus files."""

    cycle_dir = Path(cycle_dir)
    session_dir = Path(session_dir) if session_dir is not None else cycle_dir.parent
    row = build_incident_corpus_row(cycle_dir, session_dir=session_dir)
    _write_json(cycle_dir / "corpus_row.json", row)
    write_session_corpus(session_dir)
    return row


def write_session_corpus(session_dir: Path) -> CorpusWriteResult:
    """Build ``corpus.jsonl`` and ``corpus_report.json`` for all completed cycles."""

    session_dir = Path(session_dir)
    rows: list[dict[str, Any]] = []
    row_paths: list[Path] = []
    for cycle_dir in _cycle_dirs(session_dir):
        if not (cycle_dir / "summary.json").is_file():
            continue
        row = build_incident_corpus_row(cycle_dir, session_dir=session_dir)
        row_path = cycle_dir / "corpus_row.json"
        _write_json(row_path, row)
        row_paths.append(row_path)
        rows.append(row)

    jsonl_path = session_dir / "corpus.jsonl"
    jsonl_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    report = _session_report(session_dir, rows)
    report_path = session_dir / "corpus_report.json"
    _write_json(report_path, report)
    return CorpusWriteResult(
        row_paths=tuple(row_paths),
        jsonl_path=jsonl_path,
        report_path=report_path,
        row_count=len(rows),
        promotion_candidate_count=sum(1 for row in rows if row["training_fact"]["promotion_candidate"]),
    )


def _session_report(session_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    profiles: dict[str, int] = {}
    environments: dict[str, int] = {}
    services: dict[str, int] = {}
    target_classes: dict[str, int] = {}
    collectors: dict[str, int] = {}
    coverage: dict[str, int] = {}
    promotion_candidates = []
    for row in rows:
        outcome = str(row["training_fact"]["outcome"])
        profile = str(row["source"].get("profile") or "unknown")
        environment = str(row.get("environment") or "unknown")
        service = str(row.get("service") or "unknown")
        target_class = str(row.get("target_class") or "unknown")
        collector = str(row["source"].get("collector") or "unknown")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        profiles[profile] = profiles.get(profile, 0) + 1
        environments[environment] = environments.get(environment, 0) + 1
        services[service] = services.get(service, 0) + 1
        target_classes[target_class] = target_classes.get(target_class, 0) + 1
        collectors[collector] = collectors.get(collector, 0) + 1
        for label in normalize_coverage_labels(row):
            coverage[label] = coverage.get(label, 0) + 1
        if row["training_fact"]["promotion_candidate"]:
            promotion_candidates.append(
                {
                    "row_id": row["row_id"],
                    "profile": profile,
                    "decision_type": row["training_fact"].get("decision_type"),
                    "reasons": row["training_fact"].get("promotion_reasons", ()),
                }
            )
    return {
        "schema_version": "mesh.incident_corpus_report.v1",
        "generated_at": _now_iso(),
        "session_dir": str(session_dir),
        "row_count": len(rows),
        "outcomes": outcomes,
        "profiles": profiles,
        "environments": environments,
        "services": services,
        "target_classes": target_classes,
        "collectors": collectors,
        "coverage": dict(sorted(coverage.items())),
        "promotion_candidate_count": len(promotion_candidates),
        "promotion_candidates": promotion_candidates,
        "promotion_patterns": promotion_pattern_counts(
            [row for row in rows if row["training_fact"]["promotion_candidate"]]
        ),
        "repeated_promotion_patterns": repeated_promotion_patterns(
            [row for row in rows if row["training_fact"]["promotion_candidate"]]
        ),
    }


def _labels(
    summary: dict[str, Any],
    signal_payload: dict[str, Any],
    evidence_pack: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    execution: dict[str, Any],
    feedback: dict[str, Any],
    outcome: TrainingOutcome,
) -> dict[str, Any]:
    logs = _first_dict(signal_payload.get("logs"))
    signatures = {
        str(item)
        for item in (
            tuple(logs.get("error_signatures", ()))
            + tuple(evidence_pack.get("error_signatures", ()))
            + tuple(_nested_dict(decision, ("reasoning", "evidence_pack")).get("error_signatures", ()))
        )
        if item
    }
    return {
        "fault_profile": summary.get("profile"),
        "error_signatures": tuple(sorted(signatures)),
        "outcome": outcome,
        "decision_type": summary.get("decision_type") or decision.get("decision_type"),
        "evaluation_recommendation": summary.get("evaluation_recommendation") or evaluation.get("final_recommendation"),
        "execution_status": summary.get("execution_status") or execution.get("status"),
        "feedback_outcome": summary.get("feedback_outcome") or feedback.get("outcome"),
    }


def _topology_context(signal_payload: dict[str, Any], evidence_pack: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    resource_attributes = _first_dict(signal_payload.get("resource_attributes"), evidence_pack.get("resource_attributes"))
    related_context = _first_dict(signal_payload.get("related_context"), evidence_pack.get("related_context"))
    node = _first_dict(signal_payload.get("node"), evidence_pack.get("node"))
    return {
        "service": signal_payload.get("service") or resource_attributes.get("service.name") or node.get("name"),
        "environment": signal_payload.get("environment") or resource_attributes.get("deployment.environment"),
        "node": node,
        "resource_attributes": resource_attributes,
        "related_context": related_context,
        "scenario_key": run.get("scenario_key"),
        "latest_merkle_root": run.get("latest_merkle_root"),
    }


def _post_action_observations(
    signal_payload: dict[str, Any],
    evidence_pack: dict[str, Any],
    execution: dict[str, Any],
    feedback: dict[str, Any],
) -> dict[str, Any]:
    for candidate in (
        execution.get("post_action_observations") if isinstance(execution, dict) else None,
        feedback.get("post_action_observations") if isinstance(feedback, dict) else None,
        evidence_pack.get("post_action_observations"),
        signal_payload.get("post_action_observations"),
    ):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _quality_measurements(
    summary: dict[str, Any],
    run: dict[str, Any],
    scenario_analysis: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    execution: dict[str, Any],
    feedback: dict[str, Any],
) -> dict[str, Any]:
    measurements: dict[str, Any] = {}
    evidence_refs: list[str] = []
    for source_name, source in (
        ("summary", summary),
        ("run", run),
        ("scenario_analysis", scenario_analysis),
        ("decision", decision),
        ("evaluation", evaluation),
        ("execution", execution),
        ("feedback", feedback),
    ):
        for key in ("measurements", "quality_measurements", "impact", "operational_delta"):
            value = source.get(key)
            if isinstance(value, dict):
                _merge_quality_payload(measurements, evidence_refs, source_name, key, value)
        direct = {
            key: value
            for key, value in source.items()
            if str(key).lower() in MEASURED_DELTA_FIELDS or str(key).lower() in RETRIEVAL_IMPACT_FIELDS
        }
        if direct:
            _merge_quality_payload(measurements, evidence_refs, source_name, "direct", direct)
    if evidence_refs:
        existing = measurements.get("evidence_refs")
        refs = list(existing) if isinstance(existing, list) else []
        refs.extend(evidence_refs)
        measurements["evidence_refs"] = tuple(sorted({str(ref) for ref in refs if ref}))
    return measurements


def _merge_quality_payload(
    measurements: dict[str, Any],
    evidence_refs: list[str],
    source_name: str,
    source_key: str,
    payload: dict[str, Any],
) -> None:
    for key, value in payload.items():
        measurements[key] = value
        normalized = str(key).lower()
        if normalized in MEASURED_DELTA_FIELDS or normalized in RETRIEVAL_IMPACT_FIELDS:
            evidence_refs.append(f"{source_name}.{source_key}.{key}")


def _target_class(signal_payload: dict[str, Any], evidence_pack: dict[str, Any]) -> str:
    node = _first_dict(signal_payload.get("node"), evidence_pack.get("node"))
    metric = _first_dict(signal_payload.get("metric_regression"), evidence_pack.get("metric_regression"))
    kind = str(signal_payload.get("signal_type") or "")
    client = str(node.get("client_version") or "").lower()
    metric_name = str(metric.get("metric_name") or "").lower()
    node_kind = str(_nested_dict(signal_payload, ("related_context",)).get("node_kind") or "").lower()
    component_kind = _component_kind(signal_payload)
    if kind == "reth_node" or "reth" in client or node_kind == "reth":
        return "ethereum_execution_client"
    if node_kind == "geth" or metric_name.startswith("geth."):
        return "ethereum_execution_client"
    if component_kind in {"lighthouse", "validator"} or metric_name.startswith(("beacon.", "validator.")):
        return "ethereum_consensus_and_validator"
    if component_kind in {"rpc_gateway", "indexer"} or metric_name.startswith(("rpc.", "gateway.", "indexer.")):
        return "rpc_gateway_and_indexer"
    if kind == "kubernetes_deployment_issue":
        return "kubernetes_service"
    return "unknown"


def _explicit_coverage_from_signal(
    summary: dict[str, Any],
    signal_payload: dict[str, Any],
    evidence_pack: dict[str, Any],
    target_class: str,
) -> set[str]:
    coverage: set[str] = set()
    node = _first_dict(signal_payload.get("node"), evidence_pack.get("node"))
    consensus = _first_dict(signal_payload.get("consensus"), evidence_pack.get("consensus"))
    metric = _first_dict(signal_payload.get("metric_regression"), evidence_pack.get("metric_regression"))
    signal_type = str(signal_payload.get("signal_type") or "")
    node_kind = str(_nested_dict(signal_payload, ("related_context",)).get("node_kind") or "").lower()
    component_kind = _component_kind(signal_payload)
    metric_name = str(metric.get("metric_name") or "").lower()
    client = str(node.get("client_version") or "").lower()
    role = str(node.get("role") or signal_payload.get("role") or summary.get("role") or "").lower()
    consensus_client = str(consensus.get("client_kind") or consensus.get("consensus_client") or "").lower()

    if signal_type == "reth_node" or node_kind == "reth" or "reth" in client:
        coverage.add("reth")
    if node_kind == "geth" or metric_name.startswith("geth."):
        coverage.add("geth")
    if component_kind == "lighthouse" or consensus_client == "lighthouse" or "lighthouse" in client:
        coverage.add("lighthouse")
    if component_kind == "validator" or role == "validator" or metric_name.startswith("validator."):
        coverage.add("validator")
    if component_kind == "rpc_gateway" or metric_name.startswith(("rpc.", "gateway.")):
        coverage.add("rpc_gateway")
    if component_kind == "indexer" or metric_name.startswith("indexer."):
        coverage.add("indexer")
    if signal_type == "kubernetes_deployment_issue" or target_class == "kubernetes_service":
        coverage.add("kubernetes_service")
    return coverage


def _component_kind(signal_payload: dict[str, Any]) -> str:
    related_context = _nested_dict(signal_payload, ("related_context",))
    raw = (
        signal_payload.get("component_kind")
        or signal_payload.get("component")
        or related_context.get("component_kind")
        or related_context.get("component")
    )
    return str(raw or "").strip().lower().replace("-", "_")


def _collector(summary: dict[str, Any], signal_payload: dict[str, Any], live_signal: dict[str, Any]) -> str:
    if summary.get("collector"):
        return str(summary["collector"])
    if signal_payload.get("collector"):
        return str(signal_payload["collector"])
    signal_type = str(signal_payload.get("signal_type") or live_signal.get("signal_type") or "")
    node_kind = str(_nested_dict(signal_payload, ("related_context",)).get("node_kind") or "")
    if signal_type == "reth_node" or node_kind == "reth":
        return "reth_kurtosis_full_loop"
    if node_kind == "geth":
        return "geth_internal_loop"
    component_kind = _component_kind(signal_payload)
    if component_kind in {"lighthouse", "validator"}:
        return "consensus_validator_internal_loop"
    if component_kind in {"rpc_gateway", "indexer"}:
        return "rpc_indexer_internal_loop"
    if signal_type == "kubernetes_deployment_issue":
        return "kubernetes_live_loop"
    return "internal_corpus_loop"


def _row_id(session_dir: Path, cycle_dir: Path, summary: dict[str, Any], signal_payload: dict[str, Any]) -> str:
    run_id = summary.get("run_id")
    signal_id = signal_payload.get("signal_id")
    if run_id:
        return f"{session_dir.name}:{cycle_dir.name}:{run_id}"
    if signal_id:
        return f"{session_dir.name}:{cycle_dir.name}:{signal_id}"
    return f"{session_dir.name}:{cycle_dir.name}"


def _profile_from_dir(cycle_dir: Path) -> str:
    parts = cycle_dir.name.split("_", 1)
    return parts[1] if len(parts) == 2 else cycle_dir.name


def _cycle_dirs(session_dir: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (path for path in Path(session_dir).iterdir() if path.is_dir() and path.name[:6].isdigit()),
            key=lambda path: path.name,
        )
    )


def _event_count(events: Any) -> int:
    if isinstance(events, list):
        return len(events)
    if isinstance(events, dict):
        for key in ("events", "items", "data"):
            value = events.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _nested_dict(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    value: Any = source
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = value.get(key)
    return value if isinstance(value, dict) else {}


def _first_number(*values: Any) -> float | int | None:
    for value in values:
        if isinstance(value, int | float):
            return value
    return None


def _read_json(path: Path, *, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
