from __future__ import annotations

import unittest
from typing import Any

from scripts.verify_pilot_clearance import (
    DEFAULT_EXPECTED_GO_NO_GO_MISSING,
    DEFAULT_EXPECTED_READINESS_BLOCKERS,
    verify_pilot_clearance,
)


class VerifyPilotClearanceTest(unittest.TestCase):
    def test_expect_blocked_passes_for_expected_pilot_evidence_gaps(self) -> None:
        result = verify_pilot_clearance(
            base_url="http://mesh.test",
            expect_blocked=True,
            requester=_requester(
                health={"status": "ok", "commit": "unknown", "image_digest": None},
                readiness={
                    "profile": "pilot",
                    "status": "blocked",
                    "blockers": list(DEFAULT_EXPECTED_READINESS_BLOCKERS),
                    "blocker_details": _blocker_details(DEFAULT_EXPECTED_READINESS_BLOCKERS),
                },
                go_no_go={
                    "packet_version": "pilot.go_no_go.v1",
                    "status": "blocked",
                    "missing_evidence": list(DEFAULT_EXPECTED_GO_NO_GO_MISSING),
                    "checks": {
                        **{name: False for name in DEFAULT_EXPECTED_GO_NO_GO_MISSING},
                        "denied_action_proof_observed": True,
                    },
                    "observed": _observed_proofs(),
                    "mesh_brain_artifact_upload_proof": {"status": "missing", "required": True},
                    "on_call_drill": {"status": "missing", "required": True},
                },
            ),
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["mode"], "expect_blocked")
        self.assertEqual(result["missing"], [])
        self.assertIn(
            "authenticated_ingress_deployment_verified",
            result["expected_blocked"]["readiness_blocker_details"],
        )
        self.assertIn("release_provenance_complete", result["expected_blocked"]["go_no_go_missing_details"])
        checklist = {row["id"]: row for row in result["prompt_to_artifact_checklist"]}
        self.assertEqual(len(checklist), len(result["prompt_to_artifact_checklist"]))
        self.assertEqual(checklist["runtime_booted"]["status"], "pass")
        self.assertEqual(
            checklist["readiness.authenticated_ingress_deployment_verified"]["status"],
            "blocked_expected",
        )
        self.assertEqual(
            checklist["go_no_go.observed.denied_action_proof_observed"]["status"],
            "pass",
        )

    def test_expect_blocked_fails_when_endpoint_fails_to_boot(self) -> None:
        result = verify_pilot_clearance(
            base_url="http://mesh.test",
            expect_blocked=True,
            requester=_requester(
                health={"status": "ok"},
                readiness={"error": "connection refused"},
                go_no_go={
                    "packet_version": "pilot.go_no_go.v1",
                    "status": "blocked",
                    "missing_evidence": list(DEFAULT_EXPECTED_GO_NO_GO_MISSING),
                    "checks": {},
                },
            ),
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("readiness_endpoint_ok", result["missing"])
        self.assertIn("expected_readiness_blockers_present", result["missing"])

    def test_expect_blocked_fails_on_unexpected_readiness_or_go_no_go_gaps(self) -> None:
        result = verify_pilot_clearance(
            base_url="http://mesh.test",
            expect_blocked=True,
            requester=_requester(
                health={"status": "ok"},
                readiness={
                    "profile": "pilot",
                    "status": "blocked",
                    "blockers": [*DEFAULT_EXPECTED_READINESS_BLOCKERS, "runtime_boot_regression"],
                    "blocker_details": _blocker_details(
                        [*DEFAULT_EXPECTED_READINESS_BLOCKERS, "runtime_boot_regression"]
                    ),
                },
                go_no_go={
                    "packet_version": "pilot.go_no_go.v1",
                    "status": "blocked",
                    "missing_evidence": [*DEFAULT_EXPECTED_GO_NO_GO_MISSING, "unexpected_canary_gap"],
                    "checks": {
                        **{name: False for name in DEFAULT_EXPECTED_GO_NO_GO_MISSING},
                        "denied_action_proof_observed": True,
                    },
                    "observed": _observed_proofs(),
                    "mesh_brain_artifact_upload_proof": {"status": "missing", "required": True},
                    "on_call_drill": {"status": "missing", "required": True},
                },
            ),
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("unexpected_readiness_blockers_absent", result["missing"])
        self.assertIn("unexpected_go_no_go_missing_absent", result["missing"])
        self.assertEqual(result["expected_blocked"]["unexpected_readiness_blockers"], ["runtime_boot_regression"])
        self.assertEqual(result["expected_blocked"]["unexpected_go_no_go_missing"], ["unexpected_canary_gap"])

    def test_clearance_mode_still_requires_go_packet(self) -> None:
        result = verify_pilot_clearance(
            base_url="http://mesh.test",
            requester=_requester(
                health={"status": "ok"},
                readiness={
                    "profile": "pilot",
                    "status": "blocked",
                    "blockers": list(DEFAULT_EXPECTED_READINESS_BLOCKERS),
                },
                go_no_go={
                    "packet_version": "pilot.go_no_go.v1",
                    "status": "blocked",
                    "missing_evidence": list(DEFAULT_EXPECTED_GO_NO_GO_MISSING),
                    "checks": {},
                },
            ),
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["mode"], "clearance")
        self.assertIn("readiness_ready", result["missing"])
        self.assertIn("go_no_go_status_go", result["missing"])


def _requester(
    *,
    health: dict[str, Any],
    readiness: dict[str, Any],
    go_no_go: dict[str, Any],
):
    payloads = {
        "http://mesh.test/api/health": health,
        "http://mesh.test/api/readiness": readiness,
        "http://mesh.test/api/pilot/go-no-go": go_no_go,
    }

    def request(url: str, timeout_seconds: float) -> dict[str, Any]:
        del timeout_seconds
        return payloads[url]

    return request


def _observed_proofs() -> dict[str, Any]:
    return {
        "approved_run_ids": [],
        "denied_action_run_ids": ["run_denied"],
        "live_action_run_ids": [],
        "mesh_brain_model_kernel_run_ids": [],
        "mesh_brain_live_canary_smoke_run_ids": [],
        "mesh_brain_canary_lanes": [],
        "mesh_brain_rollback_drill_run_ids": [],
    }


def _blocker_details(blockers: Any) -> dict[str, dict[str, Any]]:
    return {
        str(blocker): {
            "blocker": str(blocker),
            "state_slice": f"RuntimeConfig.{blocker}",
            "env": [f"MESH_{str(blocker).upper()}"],
            "expected": "test evidence",
            "observed": False,
            "passed": False,
            "remediation": "provide test evidence",
        }
        for blocker in blockers
    }


if __name__ == "__main__":
    unittest.main()
