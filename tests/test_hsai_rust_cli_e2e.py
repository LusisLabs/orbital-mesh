from __future__ import annotations

import os
import shlex
import unittest
from copy import deepcopy
from pathlib import Path

from services.orchestrator.hsai_bridge_adapter import RustEvidenceV2HsaiAdmissionAdapter
from shared.mesh_runtime.hsai_bridge import build_hsai_admission_request_v2, evaluate_hsai_gate
from tests.test_hsai_admission_bridge import _decision, _evaluation
from tests.test_hsai_admission_request_v2 import _preflight_receipt


class HsaiRustCliEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        raw_path = os.environ.get("MESH_HSAI_RUST_CLI_PATH", "").strip()
        cls.executable_sha256 = os.environ.get("MESH_HSAI_RUST_CLI_SHA256", "").strip()
        if not raw_path or not cls.executable_sha256:
            raise unittest.SkipTest("real pinned HSAI Rust CLI is not configured")
        cls.executable = Path(raw_path)

    def test_real_rust_cli_allows_bound_evidence_v2_without_granting_authority(self) -> None:
        decision = _decision()
        evaluation = _evaluation()
        receipt = _preflight_receipt()
        request = build_hsai_admission_request_v2(decision, evaluation, receipt)

        gate = evaluate_hsai_gate(request, self._adapter(request["mesh_policy_id"]))

        self.assertTrue(gate["allowed"])
        self.assertTrue(gate["authority_eligible"])
        metadata = gate["decision"]["formal_evidence_metadata"]
        self.assertEqual(metadata["backend"], "hsai-rust-v2-evidence-aware-cli")
        self.assertFalse(metadata["grants_authority"])
        self.assertFalse(metadata["production_readiness_claimed"])

    def test_real_rust_cli_denies_preflight_path_drift(self) -> None:
        decision = _decision()
        evaluation = _evaluation()
        receipt = deepcopy(_preflight_receipt())
        receipt["changed_paths"] = [".github/workflows/release.yml"]
        request = build_hsai_admission_request_v2(decision, evaluation, receipt)

        gate = evaluate_hsai_gate(request, self._adapter(request["mesh_policy_id"]))

        self.assertFalse(gate["allowed"])
        self.assertIn("preflight_path_outside_allowed_paths", gate["reason_codes"])
        self.assertIn("protected_path_modified", gate["reason_codes"])

    def _adapter(self, policy_id: str) -> RustEvidenceV2HsaiAdmissionAdapter:
        command = f"{shlex.quote(str(self.executable))} --current-policy-id {shlex.quote(policy_id)}"
        return RustEvidenceV2HsaiAdmissionAdapter(
            command,
            executable_sha256=self.executable_sha256,
        )


if __name__ == "__main__":
    unittest.main()
