from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.integrations import build_readiness
from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.procurement_security import (
    load_procurement_security_package,
    procurement_security_package_ready,
    verify_procurement_security_package,
)


class ProcurementSecurityPackageTests(unittest.TestCase):
    def test_default_procurement_security_package_verifies(self) -> None:
        package = load_procurement_security_package("config/procurement-security.package.json")
        assert package is not None

        verification = verify_procurement_security_package("config/procurement-security.package.json")

        self.assertEqual(package["schema_version"], "mesh.procurement_security_package.v1")
        self.assertEqual(verification["schema_version"], "mesh.procurement_security_package_verification.v1")
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(procurement_security_package_ready("config/procurement-security.package.json"))
        self.assertEqual(
            set(verification["covered_sections"]),
            {
                "sso_identity",
                "audit_export",
                "retention_controls",
                "data_boundaries",
                "deployment_modes",
                "security_answers",
                "support_escalation",
                "known_limits",
            },
        )

    def test_missing_artifact_ref_fails_verification(self) -> None:
        package = load_procurement_security_package("config/procurement-security.package.json")
        assert package is not None
        package["sections"][0]["artifact_refs"] = ["missing/procurement/path.md"]
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "procurement-security.package.json"
            package_path.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            verification = verify_procurement_security_package(package_path)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("artifact_refs_exist", verification["failed_checks"])

    def test_expansion_readiness_blocks_missing_procurement_security_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                RuntimeConfig(
                    state_directory=tmp,
                    vault_path=str(Path(tmp) / "vault"),
                    readiness_profile="expansion",
                    procurement_security_package_path=str(Path(tmp) / "missing-procurement-security.package.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("procurement_security_package_verified", readiness["blockers"])


if __name__ == "__main__":
    unittest.main()
