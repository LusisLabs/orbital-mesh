from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from shared.mesh_runtime.threat_model import verify_threat_model_register


class ThreatModelRegisterTests(unittest.TestCase):
    def test_default_threat_model_register_passes(self) -> None:
        result = verify_threat_model_register("config/threat-model.register.json")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["register_version"], "mesh.threat_model_register.v1")
        self.assertGreaterEqual(result["finding_count"], 8)
        self.assertEqual(result["open_findings"], [])
        self.assertEqual(result["expired_findings"], [])

    def test_open_and_expired_findings_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "threat-model.register.json"
            payload = _register()
            payload["findings"][0]["status"] = "open"
            payload["findings"][0]["expires_at"] = "2026-01-01"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_threat_model_register(path, today=date(2026, 5, 6))

        self.assertEqual(result["status"], "fail")
        self.assertIn("open_findings_present", result["errors"])
        self.assertIn("expired_findings_present", result["errors"])
        self.assertEqual(result["open_findings"], ["tm_test"])
        self.assertEqual(result["expired_findings"], ["tm_test"])

    def test_missing_compensating_control_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "threat-model.register.json"
            payload = _register()
            payload["findings"][0]["compensating_control"] = ""
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_threat_model_register(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("compensating_control_missing", result["errors"])


def _register() -> dict:
    return {
        "version": "mesh.threat_model_register.v1",
        "generated_at": "2026-05-06T00:00:00Z",
        "findings": [
            {
                "finding_id": "tm_test",
                "boundary": "http_api",
                "risk": "test risk",
                "status": "accepted",
                "owner": "platform.security",
                "decision": "accepted_for_private_staging_only",
                "expires_at": "2026-08-31",
                "compensating_control": "test control",
                "evidence_refs": ["docs/authenticated-ingress.md"],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
