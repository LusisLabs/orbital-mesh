from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.data_classification import verify_data_classification_policy


class DataClassificationPolicyTests(unittest.TestCase):
    def test_default_data_classification_policy_passes(self) -> None:
        result = verify_data_classification_policy("config/data-classification.policy.json")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["policy_version"], "mesh.data_classification_policy.v1")
        self.assertGreaterEqual(result["class_count"], 8)
        self.assertEqual(result["missing_classes"], [])
        self.assertEqual(result["missing_deletion_for_mutable_data"], [])

    def test_missing_required_class_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data-classification.policy.json"
            payload = _policy()
            payload["classes"] = [
                entry
                for entry in payload["classes"]
                if entry["class_id"] != "application_log"
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_data_classification_policy(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("required_classes_missing", result["errors"])
        self.assertEqual(result["missing_classes"], ["application_log"])

    def test_secret_material_export_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data-classification.policy.json"
            payload = _policy()
            payload["classes"][2]["export_allowed"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_data_classification_policy(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("secret_material_export_allowed", result["errors"])

    def test_mutable_data_without_deletion_control_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data-classification.policy.json"
            payload = _policy()
            payload["classes"][0]["deletion_mode"] = "retain"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_data_classification_policy(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("mutable_data_deletion_control_missing", result["errors"])
        self.assertEqual(result["missing_deletion_for_mutable_data"], ["operational_signal"])


def _policy() -> dict:
    return {
        "version": "mesh.data_classification_policy.v1",
        "generated_at": "2026-05-06T00:00:00Z",
        "classes": [
            _entry("operational_signal", deletion_mode="purge"),
            _entry("operator_identity", deletion_mode="retain", requires_redaction=False),
            _entry("secret_material", deletion_mode="redact", export_allowed=False),
            _entry("model_output", deletion_mode="purge"),
            _entry("audit_proof", deletion_mode="retain", requires_redaction=False),
            _entry("training_candidate", deletion_mode="purge", export_allowed=False),
            _entry("application_log", deletion_mode="purge", export_allowed=False),
            _entry("distributed_trace", deletion_mode="purge", export_allowed=False),
        ],
    }


def _entry(
    class_id: str,
    *,
    deletion_mode: str,
    export_allowed: bool = True,
    requires_redaction: bool = True,
) -> dict:
    return {
        "class_id": class_id,
        "examples": [f"{class_id} example"],
        "owner": "platform.security",
        "retention_days": 30,
        "deletion_mode": deletion_mode,
        "export_allowed": export_allowed,
        "requires_redaction": requires_redaction,
        "storage_locations": ["run_artifacts"],
        "deletion_controls": ["retention review"],
        "evidence_refs": ["docs/production-hardening-records.md"],
    }


if __name__ == "__main__":
    unittest.main()
