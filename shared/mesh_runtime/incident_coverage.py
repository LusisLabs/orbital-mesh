from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


INCIDENT_COVERAGE_PROOF_SCHEMA = "incident-coverage-proof.schema.json"
INCIDENT_COVERAGE_PROOF_VERSION = "mesh.incident_coverage_proof.v1"
INCIDENT_COVERAGE_VERIFICATION_VERSION = "mesh.incident_coverage_verification.v1"
REQUIRED_INCIDENT_CLASSES = (
    "crash_loop",
    "bad_deploy_image",
    "readiness_degradation",
    "config_drift",
    "feature_flag_regression",
    "telemetry_degradation",
    "queue_resource_pressure",
    "external_provider_failure",
    "partial_outage",
    "false_positive_controls",
)


def load_incident_coverage_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(INCIDENT_COVERAGE_PROOF_SCHEMA, payload)
    return payload


def verify_incident_coverage_proof(path: str | Path | None, *, require_live: bool = False) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_incident_coverage_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    class_results = _class_results(proof, require_live=require_live)
    checks = _proof_checks(proof, class_results, require_live=require_live)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": INCIDENT_COVERAGE_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "required_incident_classes": list(REQUIRED_INCIDENT_CLASSES),
        "covered_incident_classes": sorted(result["incident_class"] for result in class_results),
        "run_ids": sorted({run_id for result in class_results for run_id in result["run_ids"]}),
        "checks": checks,
        "class_results": class_results,
        "error": load_error,
    }


def _proof_checks(
    proof: dict[str, Any] | None,
    class_results: list[dict[str, Any]],
    *,
    require_live: bool,
) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "environment_present": False,
            "all_required_classes_present": False,
            "all_classes_have_signals": False,
            "all_classes_have_decisions": False,
            "all_classes_have_policy_refs": False,
            "all_classes_have_tests": False,
            "all_classes_have_artifacts": False,
            "fixture_and_live_separated": False,
            "live_evidence_required": not require_live,
            "false_positive_controls_pass": False,
        }
    covered = {result["incident_class"] for result in class_results}
    return {
        "proof_present": True,
        "schema_valid": True,
        "environment_present": bool(str(proof.get("environment") or "").strip()),
        "all_required_classes_present": set(REQUIRED_INCIDENT_CLASSES).issubset(covered),
        "all_classes_have_signals": all(result["checks"]["signal_refs_present"] for result in class_results),
        "all_classes_have_decisions": all(result["checks"]["decision_refs_present"] for result in class_results),
        "all_classes_have_policy_refs": all(result["checks"]["policy_refs_present"] for result in class_results),
        "all_classes_have_tests": all(result["checks"]["test_refs_present"] for result in class_results),
        "all_classes_have_artifacts": all(result["checks"]["artifact_refs_present"] for result in class_results),
        "fixture_and_live_separated": all(result["checks"]["fixture_and_live_separated"] for result in class_results),
        "live_evidence_required": all(result["checks"]["live_evidence_present"] for result in class_results)
        if require_live
        else True,
        "false_positive_controls_pass": any(
            result["incident_class"] == "false_positive_controls"
            and result["checks"]["false_positive_control_valid"]
            for result in class_results
        ),
    }


def _class_results(proof: dict[str, Any] | None, *, require_live: bool) -> list[dict[str, Any]]:
    if proof is None:
        return []
    results: list[dict[str, Any]] = []
    for entry in _entries(proof):
        incident_class = str(entry.get("incident_class") or "")
        checks = {
            "signal_refs_present": bool(_strings(entry.get("signal_refs"))),
            "decision_refs_present": bool(_strings(entry.get("decision_refs"))),
            "policy_refs_present": bool(_strings(entry.get("policy_refs"))),
            "test_refs_present": bool(_strings(entry.get("test_refs"))),
            "artifact_refs_present": bool(_strings(entry.get("artifact_refs"))),
            "fixture_and_live_separated": _fixture_and_live_separated(entry),
            "live_evidence_present": _live_evidence_present(entry) if require_live else True,
            "false_positive_control_valid": _false_positive_control_valid(entry),
        }
        blockers = [name for name, passed in checks.items() if not passed]
        results.append(
            {
                "incident_class": incident_class,
                "evidence_level": entry.get("evidence_level"),
                "expected_behavior": entry.get("expected_behavior"),
                "run_ids": _strings(entry.get("run_ids")),
                "allowed": not blockers,
                "checks": checks,
                "blockers": blockers,
            }
        )
    return results


def _entries(proof: dict[str, Any]) -> list[dict[str, Any]]:
    raw = proof.get("coverage")
    return [entry for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []


def _fixture_and_live_separated(entry: dict[str, Any]) -> bool:
    evidence_level = entry.get("evidence_level")
    has_live_ref = bool(str(entry.get("live_proof_ref") or "").strip())
    if evidence_level == "fixture":
        return not has_live_ref
    return evidence_level == "live" and has_live_ref


def _live_evidence_present(entry: dict[str, Any]) -> bool:
    return (
        entry.get("evidence_level") == "live"
        and bool(str(entry.get("live_proof_ref") or "").strip())
        and bool(_strings(entry.get("run_ids")))
    )


def _false_positive_control_valid(entry: dict[str, Any]) -> bool:
    if entry.get("incident_class") != "false_positive_controls":
        return True
    return (
        entry.get("false_positive_control") is True
        and entry.get("expected_behavior") == "no_action"
        and entry.get("false_positive_run_count") == 0
    )


def _strings(raw: Any) -> list[str]:
    return [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
