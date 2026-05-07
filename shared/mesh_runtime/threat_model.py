from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


THREAT_MODEL_REGISTER_SCHEMA = "threat-model-register.schema.json"
THREAT_MODEL_REGISTER_VERSION = "mesh.threat_model_register.v1"
THREAT_MODEL_VERIFICATION_VERSION = "mesh.threat_model_register_verification.v1"


def load_threat_model_register(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    register_path = Path(path)
    if not register_path.exists():
        return None
    payload = json.loads(register_path.read_text(encoding="utf-8"))
    validate_payload(THREAT_MODEL_REGISTER_SCHEMA, payload)
    return payload


def verify_threat_model_register(
    path: str | Path | None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    checked_date = today or datetime.now(timezone.utc).date()
    errors: list[str] = []
    try:
        register = load_threat_model_register(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        register = None
        errors.append(f"register_invalid:{type(exc).__name__}")
    if register is None:
        errors.append("register_missing")
        findings: list[dict[str, Any]] = []
    else:
        findings = [
            finding
            for finding in register.get("findings", [])
            if isinstance(finding, dict)
        ]
    finding_ids = [str(finding.get("finding_id") or "") for finding in findings]
    duplicate_ids = sorted({finding_id for finding_id in finding_ids if finding_ids.count(finding_id) > 1})
    open_findings = sorted(
        str(finding.get("finding_id"))
        for finding in findings
        if finding.get("status") == "open"
    )
    expired_findings = sorted(
        str(finding.get("finding_id"))
        for finding in findings
        if finding.get("status") != "fixed"
        and _expiry_date(str(finding.get("expires_at") or "")) < checked_date
    )
    missing_owner = _missing_text(findings, "owner")
    missing_decision = _missing_text(findings, "decision")
    missing_compensating_control = _missing_text(findings, "compensating_control")
    missing_evidence_refs = sorted(
        str(finding.get("finding_id"))
        for finding in findings
        if not finding.get("evidence_refs")
    )
    if not findings:
        errors.append("findings_missing")
    if duplicate_ids:
        errors.append("duplicate_finding_ids")
    if open_findings:
        errors.append("open_findings_present")
    if expired_findings:
        errors.append("expired_findings_present")
    if missing_owner:
        errors.append("owner_missing")
    if missing_decision:
        errors.append("decision_missing")
    if missing_compensating_control:
        errors.append("compensating_control_missing")
    if missing_evidence_refs:
        errors.append("evidence_refs_missing")
    return {
        "schema_version": THREAT_MODEL_VERIFICATION_VERSION,
        "status": "pass" if not errors else "fail",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "register_path": str(Path(path).resolve()) if path else None,
        "register_version": register.get("version") if register else None,
        "finding_count": len(findings),
        "accepted_count": sum(1 for finding in findings if finding.get("status") == "accepted"),
        "fixed_count": sum(1 for finding in findings if finding.get("status") == "fixed"),
        "open_findings": open_findings,
        "expired_findings": expired_findings,
        "duplicate_ids": duplicate_ids,
        "missing_owner": missing_owner,
        "missing_decision": missing_decision,
        "missing_compensating_control": missing_compensating_control,
        "missing_evidence_refs": missing_evidence_refs,
        "errors": errors,
    }


def threat_model_register_ready(path: str | Path | None) -> bool:
    return verify_threat_model_register(path)["status"] == "pass"


def _missing_text(findings: list[dict[str, Any]], field: str) -> list[str]:
    return sorted(
        str(finding.get("finding_id"))
        for finding in findings
        if not str(finding.get(field) or "").strip()
    )


def _expiry_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return date.min
