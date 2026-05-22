from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from urllib.request import urlopen

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.hardened_arena_packet import generate_hardened_arena_packet, write_hardened_arena_packet
from shared.mesh_runtime.hardened_arena_proof import REQUIRED_PROOF_CHECKS, run_hardened_arena_proof, write_hardened_arena_proof


class HardenedArenaReleaseReadinessTests(unittest.TestCase):
    def test_readiness_exposes_hardened_arena_profile_verifier_without_upgrading_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfig(
                state_directory=tmp,
                vault_path=str(Path(tmp) / "vault"),
                integrations_config_path=str(Path(tmp) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                with urlopen(f"{base_url}/api/readiness", timeout=10) as response:
                    self.assertEqual(response.status, HTTPStatus.OK)
                    readiness = json.loads(response.read().decode("utf-8"))
            finally:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with server.coordinator._lock:
                        active_workers = list(server.coordinator._threads.values())
                    if not any(worker.is_alive() for worker in active_workers):
                        break
                    time.sleep(0.05)
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(readiness["hardened_arena"]["status"], "pass")
        self.assertEqual(readiness["hardened_arena"]["profile_count"], 3)
        self.assertIn("target-specific proof runner packet", readiness["hardened_arena"]["readiness_note"])
        self.assertNotIn("hardened_arena_target_validated", readiness.get("required_checks", {}))

    def test_release_provenance_references_arena_artifacts_without_completion_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            packet_path = tmp_path / "packet.json"
            proof_path = tmp_path / "proof.json"
            evidence_path = tmp_path / "proof-evidence.json"
            packet = generate_hardened_arena_packet("solo_project_default", generated_at="2026-05-22T00:00:00Z")
            packet["blockers"] = ["target_validation_missing"]
            write_hardened_arena_packet(packet, packet_path)
            evidence_path.write_text(json.dumps(_complete_target_evidence(str(packet_path))), encoding="utf-8")
            proof = run_hardened_arena_proof(evidence_path, generated_at="2026-05-22T00:00:00Z")
            write_hardened_arena_proof(proof, proof_path)

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_release_provenance.py",
                    "--json",
                    "--hardened-arena-profile",
                    "solo_project_default",
                    "--hardened-arena-packet",
                    str(packet_path),
                    "--hardened-arena-proof",
                    str(proof_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        release = json.loads(result.stdout)
        arena = release["hardened_arena"]
        self.assertEqual(arena["profile_id"], "solo_project_default")
        self.assertEqual(arena["profile_verification"]["status"], "pass")
        self.assertTrue(arena["packet"]["present"])
        self.assertEqual(arena["packet"]["status"], "pass")
        self.assertTrue(arena["proof"]["present"])
        self.assertEqual(arena["proof"]["readiness_status"], "target_validated")
        self.assertTrue(arena["target_validation_upgrade_allowed"])
        self.assertIn("production readiness is not upgraded", arena["readiness_note"])
        self.assertIn("clean_git_tree", release["checks"])


def _complete_target_evidence(packet_ref: str) -> dict:
    return {
        "profile_id": "solo_project_default",
        "target": {
            "target_id": "release-readiness-test",
            "target_specific": True,
            "base_url": None,
            "environment": "unit-test",
        },
        "packet_ref": packet_ref,
        "request_target_validated": True,
        "raw_secret_values_present": False,
        "checks": {
            check: {
                "observed": True,
                "evidence_ref": f"evidence://{check}",
                "details": f"observed {check}",
            }
            for check in REQUIRED_PROOF_CHECKS
        },
    }


if __name__ == "__main__":
    unittest.main()
