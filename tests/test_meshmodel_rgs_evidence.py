from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.rgs_evidence import build_meshmodel_rgs_evidence_binding


def _audit_packet() -> dict[str, object]:
    return {
        "version": "mesh.breakthrough_threshold_audit.v1",
        "state_slice": "breakthrough-threshold-audit",
        "status": "pass",
        "local_repo_commit": "a9ec57b7a74643b27c5b908add21704ebbc26767",
        "bounded_breakthrough_evidence_admitted": True,
        "bounded_breakthrough_evidence_status": "admitted_bounded_breakthrough_evidence_stack",
        "threshold_admitted": False,
        "threshold_admission_status": "blocked_breakthrough_threshold",
        "full_live_external_runtime_threshold_admitted": False,
        "claim_boundary": {
            "bounded_baseline_contrast_breakthrough_evidence": True,
            "cl12_live_external_runtime_replication": False,
            "production_authority": False,
            "production_readiness": False,
            "serving_authority": False,
            "serving_readiness": False,
        },
        "blocked_items": [
            {
                "item": "live_external_runtime_replication",
                "reason": "CL12 remains blocked preflight.",
                "state_slice": "breakthrough-threshold-audit",
            }
        ],
    }


class MeshModelRgsEvidenceTests(unittest.TestCase):
    def test_missing_source_fails_closed_without_production_authority(self) -> None:
        binding = build_meshmodel_rgs_evidence_binding({}, run_id="run_rgs_missing")

        self.assertEqual(binding["status"], "blocked")
        self.assertEqual(binding["state_slice"], "meshmodel-rgs-evidence-binding")
        self.assertIn("rgs_evidence_source_not_configured", binding["blockers"])
        self.assertFalse(binding["production_authority"])
        self.assertFalse(binding["serving_authority"])
        self.assertFalse(binding["promotion_authority"])

    def test_repo_packets_become_advisory_binding_with_cl12_blocker(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "docs"
            docs.mkdir()
            (docs / "breakthrough-threshold-audit-evidence.json").write_text(
                json.dumps(_audit_packet()),
                encoding="utf-8",
            )
            (docs / "cross-evidence-claim-synthesis.json").write_text(
                json.dumps(
                    {
                        "version": "mesh.cross_evidence_claim_synthesis.v1",
                        "state_slice": "cross-evidence-claim-synthesis",
                        "bounded_breakthrough_evidence_admitted": True,
                        "threshold_admitted": False,
                        "full_live_external_runtime_threshold_admitted": False,
                        "claim_boundary": {
                            "cl12_live_external_runtime_replication": False,
                            "production_authority": False,
                            "serving_authority": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (docs / "public-breakthrough-metrics.json").write_text(
                json.dumps(
                    {
                        "state_slice": "breakthrough-public-metrics",
                        "status": "admitted_public_bounded_breakthrough_metrics",
                        "checks": {"sidecar_ledger_hash_bound": True},
                        "public_claim_boundary": {
                            "strongest_supported_claim_scope": "evidence-governed recovery research workflows"
                        },
                        "use_case_metrics": [{"id": "operator_validated_recovery_advisory"}],
                    }
                ),
                encoding="utf-8",
            )

            binding = build_meshmodel_rgs_evidence_binding({"rgs_repo_root": str(root)}, run_id="run_rgs_1")

        self.assertEqual(binding["status"], "advisory_ready")
        self.assertTrue(binding["bounded_breakthrough_evidence_admitted"])
        self.assertFalse(binding["threshold_admitted"])
        self.assertFalse(binding["cl12_live_external_runtime_replication_admitted"])
        self.assertIn("rgs_cl12_live_external_runtime_not_admitted", binding["blockers"])
        self.assertEqual(binding["public_metrics"]["use_case_count"], 1)
        self.assertTrue(binding["public_metrics"]["sidecar_ledger_hash_bound"])
        self.assertEqual(binding["release_effect"], "advisory_evidence_only")
        self.assertFalse(binding["production_authority"])

    def test_expected_commit_mismatch_blocks_binding(self) -> None:
        binding = build_meshmodel_rgs_evidence_binding(
            {
                "expected_rgs_source_commit": "different",
                "rgs_evidence": _audit_packet(),
            },
            run_id="run_rgs_mismatch",
        )

        self.assertEqual(binding["status"], "blocked")
        self.assertIn("rgs_source_commit_mismatch", binding["blockers"])
        self.assertFalse(binding["production_authority"])


if __name__ == "__main__":
    unittest.main()
