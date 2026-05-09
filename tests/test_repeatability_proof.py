from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.repeatability import load_repeatability_proof, verify_repeatability_proof


class RepeatabilityProofTests(unittest.TestCase):
    def test_repeatability_proof_passes_complete_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "repeatability-proof.json", _proof())

            result = verify_repeatability_proof(proof_path, expected_head=_HEAD)

            self.assertEqual(result["schema_version"], "mesh.repeatability_verification.v1")
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["run_ids"], ["run_repeat_001", "run_repeat_002"])
            self.assertTrue(all(result["checks"].values()))

    def test_expected_head_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "repeatability-proof.json", _proof())

            result = verify_repeatability_proof(proof_path, expected_head="f" * 40)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["head_matches_expected"])

    def test_stale_packet_reuse_fails(self) -> None:
        proof = _proof()
        proof["release_packet_head"] = "e" * 40
        proof["stale_packet_reused"] = True
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "repeatability-proof.json", proof)

            result = verify_repeatability_proof(proof_path, expected_head=_HEAD)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["release_packet_matches_head"])
            self.assertFalse(result["checks"]["no_stale_packet_reuse"])

    def test_clean_env_requirement_fails_dirty_packet(self) -> None:
        proof = _proof()
        proof["working_tree_clean"] = False
        proof["clean_env_recreated"] = False
        proof["fresh_image_built"] = False
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "repeatability-proof.json", proof)

            strict = verify_repeatability_proof(proof_path, expected_head=_HEAD)
            relaxed = verify_repeatability_proof(proof_path, expected_head=_HEAD, require_clean_env=False)

            self.assertEqual(strict["status"], "fail")
            self.assertFalse(strict["checks"]["working_tree_clean"])
            self.assertEqual(relaxed["status"], "pass")

    def test_multiple_unique_runs_are_required(self) -> None:
        proof = _proof()
        proof["runs"] = [proof["runs"][0], {**proof["runs"][1], "run_id": "run_repeat_001"}]
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "repeatability-proof.json", proof)

            result = verify_repeatability_proof(proof_path, expected_head=_HEAD)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["run_ids_unique"])

    def test_schema_error_is_reported(self) -> None:
        proof = _proof()
        proof.pop("runs")
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "repeatability-proof.json", proof)

            self.assertIsNone(load_repeatability_proof(None))
            result = verify_repeatability_proof(proof_path, expected_head=_HEAD)

            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["checks"]["schema_valid"])
            self.assertIn("runs", result["error"])

    def test_cli_verifies_repeatability_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = _write_json(Path(tmp) / "repeatability-proof.json", _proof())

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_repeatability_proof.py",
                    "--proof",
                    str(proof_path),
                    "--expected-head",
                    _HEAD,
                    "--json",
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "pass")


_HEAD = "a" * 40


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _proof() -> dict:
    return {
        "schema_version": "mesh.repeatability_proof.v1",
        "proof_id": "repeatability-proof-fixture",
        "generated_at": "2026-05-08T18:00:00Z",
        "repo_head": _HEAD,
        "working_tree_clean": True,
        "clean_env_recreated": True,
        "manual_env_surgery": False,
        "fresh_image_built": True,
        "image_digest": f"sha256:{'b' * 64}",
        "release_packet_ref": "artifact://release/release-provenance.json",
        "release_packet_head": _HEAD,
        "release_packet_generated_at": "2026-05-08T17:59:00Z",
        "stale_packet_reused": False,
        "commands": [
            _command("docker buildx build --load -t orbital-mesh:repeatability ."),
            _command("scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --json"),
        ],
        "runs": [
            _run("run_repeat_001"),
            _run("run_repeat_002"),
        ],
    }


def _command(command: str) -> dict:
    slug = command.split()[0].replace("/", "-")
    return {
        "command": command,
        "started_at": "2026-05-08T18:00:00Z",
        "completed_at": "2026-05-08T18:01:00Z",
        "status": "pass",
        "artifact_refs": [f"artifact://repeatability/{slug}.json"],
    }


def _run(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "started_at": "2026-05-08T18:02:00Z",
        "completed_at": "2026-05-08T18:03:00Z",
        "status": "pass",
        "artifact_refs": [
            f"artifact://runs/{run_id}/run-export-package.json",
            f"artifact://runs/{run_id}/timeline-proof.json",
        ],
    }


if __name__ == "__main__":
    unittest.main()
