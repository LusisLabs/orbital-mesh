from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.integrations import build_readiness
from shared.mesh_runtime.public_proof import (
    load_public_proof_package,
    public_proof_package_ready,
    verify_public_proof_package,
)


class PublicProofPackageTests(unittest.TestCase):
    def test_default_public_proof_package_verifies(self) -> None:
        package = load_public_proof_package("config/public-proof.package.json")
        assert package is not None

        verification = verify_public_proof_package("config/public-proof.package.json")

        self.assertEqual(package["schema_version"], "mesh.public_proof_package.v1")
        self.assertEqual(verification["schema_version"], "mesh.public_proof_package_verification.v1")
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(public_proof_package_ready("config/public-proof.package.json"))
        self.assertEqual(
            set(verification["covered_components"]),
            {
                "benchmark_report",
                "architecture_paper",
                "demo_dataset",
                "run_export",
                "limitations_statement",
            },
        )

    def test_missing_limitations_ref_fails_verification(self) -> None:
        package = load_public_proof_package("config/public-proof.package.json")
        assert package is not None
        package["components"][0]["limitations_ref"] = "missing/public-proof-limitations.md"
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "public-proof.package.json"
            package_path.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            verification = verify_public_proof_package(package_path)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("limitations_refs_exist", verification["failed_checks"])

    def test_expansion_readiness_blocks_missing_public_proof_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                RuntimeConfig(
                    state_directory=tmp,
                    vault_path=str(Path(tmp) / "vault"),
                    readiness_profile="expansion",
                    public_proof_package_path=str(Path(tmp) / "missing-public-proof.package.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("public_proof_package_verified", readiness["blockers"])


if __name__ == "__main__":
    unittest.main()
