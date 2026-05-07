from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from shared.mesh_runtime import (
    build_pilot_signoff_packet,
    load_schema,
    validate_payload,
    verify_pilot_signoff_packet,
)


SIGNING_KEY = "test-pilot-signoff-key"
RELEASE_SHA = "b" * 64


class PilotSignoffTests(unittest.TestCase):
    def test_pilot_signoff_schema_is_loadable(self) -> None:
        schema = load_schema("pilot-signoff.schema.json")
        self.assertEqual(schema["title"], "PilotSignoff")

    def test_pilot_signoff_passes_for_go_packet_release_provenance_and_approver(self) -> None:
        go_no_go = _go_no_go_packet()
        packet = build_pilot_signoff_packet(
            go_no_go=go_no_go,
            operator={"operator_id": "ops@example.com", "roles": ["approver"], "source": "trusted_proxy"},
            signing_key=SIGNING_KEY,
        )
        validate_payload("pilot-signoff.schema.json", packet)

        result = verify_pilot_signoff_packet(
            packet=packet,
            signing_key=SIGNING_KEY,
            expected_release_provenance_sha=RELEASE_SHA,
            go_no_go=go_no_go,
        )

        self.assertEqual(result["schema_version"], "mesh.pilot_signoff_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_pilot_signoff_blocks_non_go_packet(self) -> None:
        go_no_go = _go_no_go_packet(status="blocked", missing_evidence=["release_provenance_complete"])
        packet = build_pilot_signoff_packet(
            go_no_go=go_no_go,
            operator={"operator_id": "ops@example.com", "roles": ["approver"], "source": "trusted_proxy"},
            signing_key=SIGNING_KEY,
        )

        result = verify_pilot_signoff_packet(packet=packet, signing_key=SIGNING_KEY, go_no_go=go_no_go)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["decision_go"])
        self.assertFalse(result["checks"]["go_no_go_status_go"])
        self.assertFalse(result["checks"]["go_no_go_no_missing_evidence"])

    def test_pilot_signoff_blocks_wrong_release_provenance_sha(self) -> None:
        go_no_go = _go_no_go_packet()
        packet = build_pilot_signoff_packet(
            go_no_go=go_no_go,
            operator={"operator_id": "ops@example.com", "roles": ["approver"], "source": "trusted_proxy"},
            signing_key=SIGNING_KEY,
        )

        result = verify_pilot_signoff_packet(
            packet=packet,
            signing_key=SIGNING_KEY,
            expected_release_provenance_sha="c" * 64,
            go_no_go=go_no_go,
        )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["expected_release_provenance_sha_matches"])

    def test_pilot_signoff_blocks_release_provenance_without_ci_sha_binding(self) -> None:
        go_no_go = _go_no_go_packet()
        go_no_go["release_provenance"]["ci_attestation"]["sha_matches_git_commit"] = False
        packet = build_pilot_signoff_packet(
            go_no_go=go_no_go,
            operator={"operator_id": "ops@example.com", "roles": ["approver"], "source": "trusted_proxy"},
            signing_key=SIGNING_KEY,
        )

        result = verify_pilot_signoff_packet(packet=packet, signing_key=SIGNING_KEY, go_no_go=go_no_go)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["release_provenance_ci_sha_matches_git_commit"])

    def test_pilot_signoff_blocks_tampered_signature_and_viewer_role(self) -> None:
        go_no_go = _go_no_go_packet()
        packet = build_pilot_signoff_packet(
            go_no_go=go_no_go,
            operator={"operator_id": "ops@example.com", "roles": ["viewer"], "source": "trusted_proxy"},
            signing_key=SIGNING_KEY,
        )
        packet["decision"] = "blocked"

        result = verify_pilot_signoff_packet(packet=packet, signing_key=SIGNING_KEY, go_no_go=go_no_go)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["operator_role_authorized"])
        self.assertFalse(result["checks"]["signature_valid"])

    def test_verify_pilot_signoff_cli_passes_with_go_no_go_hash_match(self) -> None:
        go_no_go = _go_no_go_packet()
        with tempfile.TemporaryDirectory() as tmp:
            signoff_path = Path(tmp) / "pilot-signoff.json"
            go_no_go_path = Path(tmp) / "go-no-go.json"
            go_no_go_path.write_text(json.dumps(go_no_go, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_pilot_signoff.py",
                    "--go-no-go",
                    str(go_no_go_path),
                    "--build-output",
                    str(signoff_path),
                    "--operator-id",
                    "ops@example.com",
                    "--role",
                    "admin",
                    "--signing-key",
                    SIGNING_KEY,
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_pilot_signoff.py",
                    "--signoff",
                    str(signoff_path),
                    "--go-no-go",
                    str(go_no_go_path),
                    "--signing-key",
                    SIGNING_KEY,
                    "--expected-release-provenance-sha",
                    RELEASE_SHA,
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checks"]["go_no_go_packet_hash_matches"])


def _go_no_go_packet(*, status: str = "go", missing_evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "packet_version": "pilot.go_no_go.v1",
        "generated_at": "2026-05-05T00:00:00Z",
        "status": status,
        "checks": {
            "readiness_green": status == "go",
            "release_provenance_complete": status == "go",
        },
        "missing_evidence": missing_evidence or [],
        "readiness": {"status": "ready", "profile": "pilot"},
        "observed": {
            "run_count": 11,
            "approved_run_ids": ["run_1"],
            "live_action_run_ids": ["run_1"],
            "denied_action_run_ids": ["run_2"],
            "merkle_run_ids": ["run_1"],
            "mesh_brain_model_kernel_run_ids": ["run_3"],
            "mesh_brain_live_canary_smoke_run_ids": ["run_4"],
            "mesh_brain_canary_lanes": [{"tenant_id": "tenant_a", "task_type": "crops"}],
            "mesh_brain_rollback_drill_run_ids": ["run_5"],
        },
        "release_provenance": {
            "required": True,
            "path": "/app/.mesh-runtime-state/release-provenance.json",
            "exists": True,
            "status": "complete",
            "packet_sha256": RELEASE_SHA,
            "missing": [],
            "checks": {
                "git_commit": True,
                "clean_git_tree": True,
                "image_digest": True,
                "base_image_digests": True,
                "ci_attestation": True,
            },
            "ci_attestation": {
                "provider": "github-actions",
                "run_id": "ci-run-1",
                "sha": "a" * 40,
                "expected_sha": "a" * 40,
                "sha_matches_git_commit": True,
            },
            "schema_version": "mesh.release_provenance.v1",
        },
    }
