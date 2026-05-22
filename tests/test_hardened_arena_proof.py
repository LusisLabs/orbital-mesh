from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from shared.mesh_runtime.hardened_arena_packet import generate_hardened_arena_packet, write_hardened_arena_packet
from shared.mesh_runtime.hardened_arena_proof import (
    REQUIRED_PROOF_CHECKS,
    output_path_is_generated,
    run_hardened_arena_proof,
    verify_hardened_arena_proof,
    write_hardened_arena_proof,
)
from shared.mesh_runtime.schema_validation import validate_payload


class HardenedArenaProofTests(unittest.TestCase):
    def test_proof_runner_marks_smoke_passed_only_with_observed_evidence(self) -> None:
        with _ProofServer() as server:
            proof = run_hardened_arena_proof(
                _write_evidence(_complete_evidence(server.base_url)),
                generated_at="2026-05-22T00:00:00Z",
            )

        self.assertEqual(proof["readiness_posture"]["status"], "arena_smoke_passed")
        self.assertFalse(proof["readiness_posture"]["target_validated"])
        self.assertEqual({check["check"] for check in proof["checks"]}, REQUIRED_PROOF_CHECKS)
        self.assertTrue(all(check["observed"] for check in proof["checks"]))
        self.assertFalse(proof["raw_secret_values_present"])
        validate_payload("hardened-arena-proof.schema.json", proof)

    def test_target_validated_requires_target_specific_packet_ref_and_complete_checks(self) -> None:
        packet_path = _write_valid_packet()
        with _ProofServer() as server:
            evidence = _complete_evidence(server.base_url)
            evidence["packet_ref"] = str(packet_path)
            evidence["request_target_validated"] = True
            proof = run_hardened_arena_proof(_write_evidence(evidence), generated_at="2026-05-22T00:00:00Z")
        packet_path.unlink(missing_ok=True)

        self.assertEqual(proof["readiness_posture"]["status"], "target_validated")
        self.assertTrue(proof["readiness_posture"]["target_validated"])
        self.assertTrue(proof["readiness_posture"]["target_specific"])

    def test_target_validated_rejects_profile_mismatched_packet_ref(self) -> None:
        packet_path = _write_valid_packet("solo_project_default")
        with _ProofServer() as server:
            evidence = _complete_evidence(server.base_url)
            evidence["profile_id"] = "enterprise_onprem_rehearsal"
            evidence["packet_ref"] = str(packet_path)
            evidence["request_target_validated"] = True
            proof = run_hardened_arena_proof(_write_evidence(evidence), generated_at="2026-05-22T00:00:00Z")
        packet_path.unlink(missing_ok=True)

        self.assertEqual(proof["profile_id"], "enterprise_onprem_rehearsal")
        self.assertEqual(proof["readiness_posture"]["status"], "blocked")
        self.assertFalse(proof["readiness_posture"]["target_validated"])
        self.assertIn("target_validated_packet_ref_profile_mismatch", proof["blockers"])

    def test_target_validated_rejects_missing_or_invalid_packet_ref(self) -> None:
        with _ProofServer() as server:
            evidence = _complete_evidence(server.base_url)
            evidence["packet_ref"] = "not/a/real/complete/packet.json"
            evidence["request_target_validated"] = True
            proof = run_hardened_arena_proof(_write_evidence(evidence), generated_at="2026-05-22T00:00:00Z")

        self.assertEqual(proof["readiness_posture"]["status"], "blocked")
        self.assertFalse(proof["readiness_posture"]["target_validated"])
        self.assertIn("target_validated_requires_complete_proof_packet", proof["blockers"])

    def test_target_validated_rejects_packet_with_unresolved_blockers(self) -> None:
        packet_path = _write_unresolved_blocker_packet("solo_project_default")
        with _ProofServer() as server:
            evidence = _complete_evidence(server.base_url)
            evidence["packet_ref"] = str(packet_path)
            evidence["request_target_validated"] = True
            proof = run_hardened_arena_proof(_write_evidence(evidence), generated_at="2026-05-22T00:00:00Z")
        packet_path.unlink(missing_ok=True)

        self.assertEqual(proof["readiness_posture"]["status"], "blocked")
        self.assertFalse(proof["readiness_posture"]["target_validated"])
        self.assertIn("target_validated_packet_ref_has_unresolved_blockers", proof["blockers"])

    def test_incomplete_evidence_blocks_smoke_status(self) -> None:
        with _ProofServer() as server:
            evidence = _complete_evidence(server.base_url)
            evidence["checks"].pop("cleanup")
            proof = run_hardened_arena_proof(_write_evidence(evidence), generated_at="2026-05-22T00:00:00Z")

        self.assertEqual(proof["readiness_posture"]["status"], "blocked")
        self.assertIn("proof_check_not_observed:cleanup", proof["blockers"])

    def test_verifier_rejects_overclaimed_target_validated_without_packet_ref(self) -> None:
        with _ProofServer() as server:
            proof = run_hardened_arena_proof(
                _write_evidence(_complete_evidence(server.base_url)),
                generated_at="2026-05-22T00:00:00Z",
            )
        broken = copy.deepcopy(proof)
        broken["packet_ref"] = None
        broken["readiness_posture"]["status"] = "target_validated"
        broken["readiness_posture"]["target_validated"] = True
        path = Path("dist/hardened-arena/test/proof-overclaim.json")
        try:
            write_hardened_arena_proof(broken, path)
            result = verify_hardened_arena_proof(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("target_validated_requires_packet_ref", result["blockers"])

    def test_verifier_rejects_raw_secret_values(self) -> None:
        with _ProofServer() as server:
            proof = run_hardened_arena_proof(
                _write_evidence(_complete_evidence(server.base_url)),
                generated_at="2026-05-22T00:00:00Z",
            )
        proof["raw_secret_values_present"] = True
        path = Path("dist/hardened-arena/test/proof-secret.json")
        try:
            write_hardened_arena_proof(proof, path)
            result = verify_hardened_arena_proof(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("proof_contains_raw_secret_values", result["blockers"])

    def test_cli_runs_and_verifies_proof_under_dist(self) -> None:
        output = Path("dist/hardened-arena/solo_project_default/proof.json")
        output.unlink(missing_ok=True)
        with _ProofServer() as server:
            evidence_path = _write_evidence(_complete_evidence(server.base_url))
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_hardened_arena_proof.py",
                    "--evidence",
                    str(evidence_path),
                    "--output",
                    str(output),
                    "--timeout-seconds",
                    "2",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        verify_completed = subprocess.run(
            [sys.executable, "scripts/verify_hardened_arena_proof.py", "--proof", str(output), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        output.unlink(missing_ok=True)

        self.assertEqual(verify_completed.returncode, 0, verify_completed.stdout + verify_completed.stderr)
        self.assertIn('"status": "pass"', verify_completed.stdout)

    def test_cli_rejects_output_outside_generated_dist(self) -> None:
        self.assertTrue(output_path_is_generated("dist/hardened-arena/example/proof.json"))
        self.assertFalse(output_path_is_generated("config/proof.json"))
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_hardened_arena_proof.py",
                "--evidence",
                "missing.json",
                "--output",
                "config/proof.json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("refusing to write generated proof outside ignored dist/ output", completed.stderr)


def _complete_evidence(base_url: str) -> dict:
    checks = {
        check: {
            "observed": True,
            "evidence_ref": f"evidence://{check}",
            "details": f"observed {check}",
        }
        for check in REQUIRED_PROOF_CHECKS
    }
    checks["health_endpoint"] = {"url": f"{base_url}/health", "expected_status": 200}
    checks["readiness_endpoint"] = {"url": f"{base_url}/ready", "expected_status": 200}
    return {
        "profile_id": "solo_project_default",
        "target": {
            "target_id": "local-test-arena",
            "target_specific": True,
            "base_url": base_url,
            "environment": "unit-test",
        },
        "packet_ref": "dist/hardened-arena/solo_project_default/packet.json",
        "request_target_validated": False,
        "raw_secret_values_present": False,
        "checks": checks,
    }


def _write_valid_packet(profile_id: str = "solo_project_default") -> Path:
    directory = Path("dist/hardened-arena/test")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"valid-{profile_id}-packet.json"
    packet = generate_hardened_arena_packet(profile_id, generated_at="2026-05-22T00:00:00Z")
    packet["blockers"] = ["target_validation_missing"]
    write_hardened_arena_packet(packet, path)
    return path


def _write_unresolved_blocker_packet(profile_id: str = "solo_project_default") -> Path:
    directory = Path("dist/hardened-arena/test")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"unresolved-{profile_id}-packet.json"
    write_hardened_arena_packet(
        generate_hardened_arena_packet(profile_id, generated_at="2026-05-22T00:00:00Z"),
        path,
    )
    return path


def _write_evidence(payload: dict) -> Path:
    directory = Path("dist/hardened-arena/test/evidence")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "proof-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _ProofHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/ready"}:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class _ProofServer:
    def __enter__(self) -> "_ProofServer":
        self.server = HTTPServer(("127.0.0.1", 0), _ProofHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        shutil.rmtree(Path("dist/hardened-arena/test/evidence"), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
