from __future__ import annotations

import unittest
from copy import deepcopy

from shared.mesh_runtime.hsai_bridge import (
    build_hsai_admission_request_v2,
    evaluate_hsai_gate,
    sha256_digest,
    validate_bridge_gate,
)
from tests.test_hsai_admission_bridge import RecordingHsaiAdapter, _decision, _evaluation


class HsaiAdmissionRequestV2Tests(unittest.TestCase):
    def test_v2_request_recomputes_candidate_evidence_and_stage_digests(self) -> None:
        decision = _decision()
        evaluation = _evaluation()
        receipt = _preflight_receipt()

        request = build_hsai_admission_request_v2(decision, evaluation, receipt)

        self.assertEqual(request["schema_version"], "mesh.hsai_admission_request.v2")
        self.assertEqual(request["candidate_payload_digest"], sha256_digest(request["candidate_payload"]))
        self.assertEqual(
            request["evidence_packet_digest"],
            sha256_digest(request["pre_execution_evidence"]),
        )
        self.assertEqual(
            request["pre_execution_evidence"]["stage_results_digest"],
            sha256_digest(evaluation.stage_results),
        )
        self.assertEqual(
            request["candidate_payload"]["execution_plan"]["parameters"]["test_commands"],
            [["/usr/bin/python3", "-m", "unittest"]],
        )
        self.assertEqual(
            request["candidate_payload"]["execution_plan"]["parameters"]["protected_paths"],
            [".git", ".github", "AGENTS.md"],
        )

    def test_v2_gate_rejects_evaluation_body_drift(self) -> None:
        decision = _decision()
        evaluation = _evaluation()
        request = build_hsai_admission_request_v2(decision, evaluation, _preflight_receipt())
        gate = evaluate_hsai_gate(request, RecordingHsaiAdapter())
        changed = deepcopy(gate)
        changed["request"]["pre_execution_evidence"]["stage_results"] = {"drift": True}

        with self.assertRaisesRegex(ValueError, "request digest|evidence packet digest|stage results"):
            validate_bridge_gate(
                changed,
                expected_decision=decision,
                expected_evaluation=evaluation,
            )

    def test_v2_builder_rejects_action_identity_override(self) -> None:
        decision = _decision(parameters={"mesh_action_id": "different-action"})

        with self.assertRaisesRegex(ValueError, "must equal the decision id"):
            build_hsai_admission_request_v2(decision, _evaluation(), _preflight_receipt())

    def test_v2_builder_rejects_preflight_command_substitution(self) -> None:
        receipt = _preflight_receipt()
        receipt["test_results"][0]["argv"] = ["/usr/bin/python3", "-c", "print('different')"]

        with self.assertRaisesRegex(ValueError, "not bound"):
            build_hsai_admission_request_v2(_decision(), _evaluation(), receipt)

    def test_v2_builder_rejects_non_absolute_preflight_executable(self) -> None:
        receipt = _preflight_receipt()
        receipt["test_results"][0]["argv"][0] = "python3"

        with self.assertRaisesRegex(ValueError, "not bound"):
            build_hsai_admission_request_v2(_decision(), _evaluation(), receipt)


def _preflight_receipt() -> dict:
    return {
        "state_slice": "mesh.repo_patch_disposable_worktree.v1",
        "base_commit": "a" * 40,
        "base_tree": "b" * 40,
        "target_path": "app/search.py",
        "target_preimage_digest": "sha256:" + ("1" * 64),
        "target_postimage_digest": "sha256:" + ("2" * 64),
        "authorized_diff_digest": "sha256:" + ("3" * 64),
        "changed_paths": ["app/search.py"],
        "test_results": [
            {
                "argv": ["/usr/bin/python3", "-m", "unittest"],
                "returncode": 0,
                "stdout_digest": "sha256:" + ("4" * 64),
                "stderr_digest": "sha256:" + ("5" * 64),
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
