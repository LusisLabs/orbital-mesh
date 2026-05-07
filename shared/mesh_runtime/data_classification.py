from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


DATA_CLASSIFICATION_POLICY_SCHEMA = "data-classification-policy.schema.json"
DATA_CLASSIFICATION_POLICY_VERSION = "mesh.data_classification_policy.v1"
DATA_CLASSIFICATION_VERIFICATION_VERSION = "mesh.data_classification_policy_verification.v1"
REQUIRED_DATA_CLASSES = frozenset(
    {
        "operational_signal",
        "operator_identity",
        "secret_material",
        "model_output",
        "audit_proof",
        "training_candidate",
        "application_log",
        "distributed_trace",
    }
)
DELETION_REQUIRED_CLASSES = frozenset(
    {
        "operational_signal",
        "model_output",
        "training_candidate",
        "application_log",
        "distributed_trace",
    }
)


def load_data_classification_policy(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    policy_path = Path(path)
    if not policy_path.exists():
        return None
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    validate_payload(DATA_CLASSIFICATION_POLICY_SCHEMA, payload)
    return payload


def verify_data_classification_policy(path: str | Path | None) -> dict[str, Any]:
    errors: list[str] = []
    try:
        policy = load_data_classification_policy(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        policy = None
        errors.append(f"policy_invalid:{type(exc).__name__}")
    if policy is None:
        errors.append("policy_missing")
        classes: list[dict[str, Any]] = []
    else:
        classes = [
            entry
            for entry in policy.get("classes", [])
            if isinstance(entry, dict)
        ]
    class_ids = [str(entry.get("class_id") or "") for entry in classes]
    duplicate_ids = sorted({class_id for class_id in class_ids if class_ids.count(class_id) > 1})
    missing_classes = sorted(REQUIRED_DATA_CLASSES - set(class_ids))
    missing_owner = _missing_text(classes, "owner")
    missing_examples = _missing_list(classes, "examples")
    missing_storage_locations = _missing_list(classes, "storage_locations")
    missing_deletion_controls = _missing_list(classes, "deletion_controls")
    missing_evidence_refs = _missing_list(classes, "evidence_refs")
    invalid_retention = sorted(
        str(entry.get("class_id"))
        for entry in classes
        if not isinstance(entry.get("retention_days"), int) or int(entry.get("retention_days", -1)) < 0
    )
    missing_deletion_for_mutable_data = sorted(
        str(entry.get("class_id"))
        for entry in classes
        if entry.get("class_id") in DELETION_REQUIRED_CLASSES
        and entry.get("deletion_mode") == "retain"
    )
    secret_export_allowed = sorted(
        str(entry.get("class_id"))
        for entry in classes
        if entry.get("class_id") == "secret_material" and entry.get("export_allowed") is not False
    )
    secret_redaction_missing = sorted(
        str(entry.get("class_id"))
        for entry in classes
        if entry.get("class_id") == "secret_material" and entry.get("requires_redaction") is not True
    )
    if not classes:
        errors.append("classes_missing")
    if duplicate_ids:
        errors.append("duplicate_class_ids")
    if missing_classes:
        errors.append("required_classes_missing")
    if missing_owner:
        errors.append("owner_missing")
    if missing_examples:
        errors.append("examples_missing")
    if missing_storage_locations:
        errors.append("storage_locations_missing")
    if missing_deletion_controls:
        errors.append("deletion_controls_missing")
    if missing_evidence_refs:
        errors.append("evidence_refs_missing")
    if invalid_retention:
        errors.append("retention_invalid")
    if missing_deletion_for_mutable_data:
        errors.append("mutable_data_deletion_control_missing")
    if secret_export_allowed:
        errors.append("secret_material_export_allowed")
    if secret_redaction_missing:
        errors.append("secret_material_redaction_missing")
    return {
        "schema_version": DATA_CLASSIFICATION_VERIFICATION_VERSION,
        "status": "pass" if not errors else "fail",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy_path": str(Path(path).resolve()) if path else None,
        "policy_version": policy.get("version") if policy else None,
        "class_count": len(classes),
        "required_classes": sorted(REQUIRED_DATA_CLASSES),
        "covered_classes": sorted(set(class_ids)),
        "missing_classes": missing_classes,
        "duplicate_ids": duplicate_ids,
        "missing_owner": missing_owner,
        "missing_examples": missing_examples,
        "missing_storage_locations": missing_storage_locations,
        "missing_deletion_controls": missing_deletion_controls,
        "missing_evidence_refs": missing_evidence_refs,
        "invalid_retention": invalid_retention,
        "missing_deletion_for_mutable_data": missing_deletion_for_mutable_data,
        "secret_export_allowed": secret_export_allowed,
        "secret_redaction_missing": secret_redaction_missing,
        "errors": errors,
    }


def data_classification_policy_ready(path: str | Path | None) -> bool:
    return verify_data_classification_policy(path)["status"] == "pass"


def _missing_text(classes: list[dict[str, Any]], field: str) -> list[str]:
    return sorted(
        str(entry.get("class_id"))
        for entry in classes
        if not str(entry.get(field) or "").strip()
    )


def _missing_list(classes: list[dict[str, Any]], field: str) -> list[str]:
    return sorted(
        str(entry.get("class_id"))
        for entry in classes
        if not entry.get(field)
    )
