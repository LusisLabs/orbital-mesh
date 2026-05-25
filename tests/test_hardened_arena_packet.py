from __future__ import annotations

import copy
import subprocess
import sys
import unittest
from pathlib import Path

from shared.mesh_runtime.hardened_arena import REQUIRED_PROOF_GATES
from shared.mesh_runtime.hardened_arena_packet import (
    generate_hardened_arena_packet,
    output_path_is_generated,
    verify_hardened_arena_packet,
    write_hardened_arena_packet,
)
from shared.mesh_runtime.schema_validation import validate_payload


class HardenedArenaPacketTests(unittest.TestCase):
    def test_generated_packet_contains_required_review_sections_without_target_claim(self) -> None:
        packet = generate_hardened_arena_packet(
            "solo_project_default",
            generated_at="2026-05-22T00:00:00Z",
        )

        self.assertEqual(packet["selected_profile"]["profile_id"], "solo_project_default")
        self.assertEqual(packet["readiness_posture"]["status"], "profile_verified")
        self.assertFalse(packet["readiness_posture"]["target_validated"])
        self.assertFalse(packet["readiness_posture"]["production_ready"])
        self.assertGreater(len(packet["component_graph"]), 0)
        self.assertGreater(len(packet["authority_boundaries"]), 0)
        self.assertGreater(len(packet["credential_classes"]), 0)
        self.assertGreater(len(packet["dhi_catalog_refs"]), 0)
        self.assertTrue(REQUIRED_PROOF_GATES.issubset({item["gate"] for item in packet["proof_checklist"]}))
        self.assertIn("health_endpoint", packet["mesh_probe_plan"]["checks"])
        self.assertGreater(len(packet["failure_mode_curriculum"]), 0)
        self.assertTrue(packet["cleanup_plan"]["required"])
        self.assertIn("retention", packet["data_retention_plan"])
        self.assertIn("target_validation_missing", packet["blockers"])
        validate_payload("hardened-arena-packet.schema.json", packet)

    def test_packet_verifier_accepts_generated_packet(self) -> None:
        packet = generate_hardened_arena_packet("startup_saas_staging", generated_at="2026-05-22T00:00:00Z")
        path = Path("dist/hardened-arena/test/startup_packet.json")
        try:
            write_hardened_arena_packet(packet, path)
            result = verify_hardened_arena_packet(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["profile_id"], "startup_saas_staging")

    def test_packet_verifier_rejects_target_validated_overclaim(self) -> None:
        packet = generate_hardened_arena_packet("enterprise_onprem_rehearsal", generated_at="2026-05-22T00:00:00Z")
        packet["readiness_posture"]["target_validated"] = True
        path = Path("dist/hardened-arena/test/overclaim_packet.json")
        try:
            write_hardened_arena_packet(packet, path)
            result = verify_hardened_arena_packet(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("packet_overclaims_target_validated", result["blockers"])

    def test_packet_verifier_rejects_missing_proof_gate(self) -> None:
        packet = generate_hardened_arena_packet("solo_project_default", generated_at="2026-05-22T00:00:00Z")
        broken_packet = copy.deepcopy(packet)
        broken_packet["proof_checklist"] = [
            item for item in broken_packet["proof_checklist"] if item["gate"] != "release_packet"
        ]
        path = Path("dist/hardened-arena/test/missing_gate_packet.json")
        try:
            write_hardened_arena_packet(broken_packet, path)
            result = verify_hardened_arena_packet(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("proof_gate_missing:release_packet", result["blockers"])

    def test_cli_generates_and_verifies_packet_under_dist(self) -> None:
        output = Path("dist/hardened-arena/solo_project_default/packet.json")
        output.unlink(missing_ok=True)
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/generate_hardened_arena_packet.py",
                "--profile",
                "solo_project_default",
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        verify_completed = subprocess.run(
            [
                sys.executable,
                "scripts/verify_hardened_arena_packet.py",
                "--packet",
                str(output),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        output.unlink(missing_ok=True)

        self.assertEqual(verify_completed.returncode, 0, verify_completed.stdout + verify_completed.stderr)
        self.assertIn('"status": "pass"', verify_completed.stdout)

    def test_cli_rejects_output_outside_generated_dist(self) -> None:
        self.assertTrue(output_path_is_generated("dist/hardened-arena/example/packet.json"))
        self.assertFalse(output_path_is_generated("config/packet.json"))
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/generate_hardened_arena_packet.py",
                "--profile",
                "solo_project_default",
                "--output",
                "config/packet.json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("refusing to write generated packet outside ignored dist/ output", completed.stderr)


if __name__ == "__main__":
    unittest.main()
