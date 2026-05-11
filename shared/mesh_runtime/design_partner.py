from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, cast

from .schema_validation import SchemaValidationError, validate_payload


DESIGN_PARTNER_PACKET_SCHEMA = "design-partner-packet.schema.json"
DESIGN_PARTNER_PACKET_VERSION = "mesh.design_partner_packet.v1"
DESIGN_PARTNER_VERIFICATION_VERSION = "mesh.design_partner_packet_verification.v1"
_NONLOCAL_ENVIRONMENTS = frozenset({"staging", "pilot", "production"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_design_partner_packet(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    packet_path = Path(path)
    if not packet_path.exists():
        return None
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    validate_payload(DESIGN_PARTNER_PACKET_SCHEMA, payload)
    return cast(dict[str, Any], payload)


def design_partner_packet_ready(path: str | Path | None, *, require_go_evidence: bool = True) -> bool:
    return str(verify_design_partner_packet(path, require_go_evidence=require_go_evidence).get("status")) == "pass"


def verify_design_partner_packet(
    path: str | Path | None,
    *,
    require_go_evidence: bool = True,
    expected_go_no_go_sha: str | None = None,
    expected_release_provenance_sha: str | None = None,
) -> dict[str, Any]:
    packet_path = Path(path) if path else None
    load_error: str | None = None
    try:
        packet = load_design_partner_packet(packet_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        packet = None
        load_error = str(exc)

    checks = _packet_checks(
        packet,
        expected_go_no_go_sha=expected_go_no_go_sha,
        expected_release_provenance_sha=expected_release_provenance_sha,
    )
    if packet is None:
        checks["packet_present"] = False
    if load_error:
        checks["schema_valid"] = False
    required_checks = set(checks)
    advisory_checks: set[str] = set()
    if not require_go_evidence:
        required_checks.discard("evidence_summary_go")
        advisory_checks.add("evidence_summary_go")
    missing = sorted(name for name in required_checks if not checks.get(name))
    return {
        "schema_version": DESIGN_PARTNER_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if not missing else "fail",
        "packet_path": str(packet_path) if packet_path else None,
        "packet_id": packet.get("packet_id") if packet else None,
        "partner_id": _field(packet, "partner", "partner_id"),
        "require_go_evidence": require_go_evidence,
        "required_checks": sorted(required_checks),
        "advisory_checks": sorted(advisory_checks),
        "missing": missing,
        "checks": checks,
        "error": load_error or ("packet_missing" if packet is None else None),
    }


def _packet_checks(
    packet: dict[str, Any] | None,
    *,
    expected_go_no_go_sha: str | None = None,
    expected_release_provenance_sha: str | None = None,
) -> dict[str, bool]:
    expected_go_no_go_sha = (expected_go_no_go_sha or "").strip()
    expected_release_provenance_sha = (expected_release_provenance_sha or "").strip()
    if packet is None:
        checks = {
            "packet_present": False,
            "schema_valid": False,
            "partner_recorded": False,
            "pilot_scope_bounded": False,
            "success_metrics_evidence_backed": False,
            "data_handling_safe": False,
            "support_model_complete": False,
            "rollback_plan_complete": False,
            "consent_documented": False,
            "evidence_summary_go": False,
            "no_raw_secret_material": False,
        }
        if expected_go_no_go_sha:
            checks["expected_go_no_go_sha_matches"] = False
        if expected_release_provenance_sha:
            checks["expected_release_provenance_sha_matches"] = False
        return checks
    evidence_summary = _section(packet, "evidence_summary")
    checks = {
        "packet_present": True,
        "schema_valid": True,
        "partner_recorded": _partner_recorded(_section(packet, "partner")),
        "pilot_scope_bounded": _pilot_scope_bounded(_section(packet, "pilot_scope")),
        "success_metrics_evidence_backed": _success_metrics_evidence_backed(_section(packet, "success_metrics")),
        "data_handling_safe": _data_handling_safe(_section(packet, "data_handling")),
        "support_model_complete": _support_model_complete(_section(packet, "support_model")),
        "rollback_plan_complete": _rollback_plan_complete(_section(packet, "rollback_plan")),
        "consent_documented": _consent_documented(_section(packet, "consent")),
        "evidence_summary_go": _evidence_summary_go(evidence_summary),
        "no_raw_secret_material": packet.get("raw_secret_material_present") is False,
    }
    if expected_go_no_go_sha:
        checks["expected_go_no_go_sha_matches"] = evidence_summary.get("go_no_go_packet_sha256") == expected_go_no_go_sha
    if expected_release_provenance_sha:
        checks["expected_release_provenance_sha_matches"] = (
            evidence_summary.get("release_provenance_sha256") == expected_release_provenance_sha
        )
    return checks


def _partner_recorded(record: dict[str, Any]) -> bool:
    return (
        bool(str(record.get("partner_id") or "").strip())
        and bool(str(record.get("technical_owner") or "").strip())
        and bool(str(record.get("escalation_channel") or "").strip())
        and isinstance(record.get("pilot_window_days"), int)
        and 0 < record.get("pilot_window_days", 0) <= 30
    )


def _pilot_scope_bounded(record: dict[str, Any]) -> bool:
    return (
        str(record.get("environment") or "").strip() in _NONLOCAL_ENVIRONMENTS
        and _nonempty_list_with_max(record.get("kubernetes_contexts"), 1)
        and _nonempty_list_with_max(record.get("namespaces"), 1)
        and _nonempty_list_with_max(record.get("service_classes"), 2)
        and record.get("approval_gate_forced") is True
        and record.get("live_execution_limited") is True
        and record.get("feature_flag_adapter_disabled") is True
        and record.get("incident_adapter_disabled") is True
        and record.get("proposal_lanes_advisory_only") is True
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _success_metrics_evidence_backed(record: dict[str, Any]) -> bool:
    required = (
        "allowed_action_with_feedback",
        "denied_action_with_blocker",
        "no_proposal_lane_credentials",
        "operator_identity_on_mutations",
        "kill_switch_rehearsed",
        "merkle_proofs_available",
        "postgres_restart_proof_passed",
    )
    return all(record.get(name) is True for name in required) and bool(str(record.get("evidence_ref") or "").strip())


def _data_handling_safe(record: dict[str, Any]) -> bool:
    return (
        isinstance(record.get("retention_days"), int)
        and 0 < record.get("retention_days", 0) <= 30
        and isinstance(record.get("training_use_opt_in"), bool)
        and record.get("audit_records_excluded_from_training_by_default") is True
        and record.get("raw_secrets_disallowed") is True
        and record.get("kubeconfig_contents_disallowed") is True
        and record.get("private_keys_disallowed") is True
        and record.get("customer_payloads_excluded") is True
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _support_model_complete(record: dict[str, Any]) -> bool:
    return (
        bool(str(record.get("mesh_support_hours") or "").strip())
        and bool(str(record.get("partner_owner_ref") or "").strip())
        and str(record.get("emergency_owner") or "").strip() == "operator"
        and record.get("postmortem_packet_required") is True
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _rollback_plan_complete(record: dict[str, Any]) -> bool:
    return (
        bool(str(record.get("plan_ref") or "").strip())
        and bool(str(record.get("kill_switch_ref") or "").strip())
        and record.get("rollback_metadata_required") is True
        and record.get("human_review_on_ambiguous_execution") is True
    )


def _consent_documented(record: dict[str, Any]) -> bool:
    consent_ref = record.get("real_user_experiment_consent_ref")
    consent_required = record.get("real_user_experiment_consent_required") is True
    return (
        record.get("partner_approved") is True
        and record.get("mesh_approved") is True
        and (not consent_required or bool(str(consent_ref or "").strip()))
        and bool(str(record.get("data_handling_terms_ref") or "").strip())
        and bool(str(record.get("signed_at") or "").strip())
    )


def _evidence_summary_go(record: dict[str, Any]) -> bool:
    return (
        record.get("go_no_go_status") == "go"
        and _valid_sha256(record.get("go_no_go_packet_sha256"))
        and _valid_sha256(record.get("release_provenance_sha256"))
        and bool(str(record.get("run_export_ref") or "").strip())
        and bool(str(record.get("readiness_ref") or "").strip())
    )


def _section(packet: dict[str, Any], name: str) -> dict[str, Any]:
    value = packet.get(name)
    return value if isinstance(value, dict) else {}


def _field(packet: dict[str, Any] | None, section: str, name: str) -> Any:
    section_value = packet.get(section) if isinstance(packet, dict) else None
    if not isinstance(section_value, dict):
        return None
    return section_value.get(name)


def _nonempty_list_with_max(value: Any, max_items: int) -> bool:
    return isinstance(value, list) and 0 < len(value) <= max_items and all(str(item).strip() for item in value)


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.match(value))


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
