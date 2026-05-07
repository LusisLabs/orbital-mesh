from __future__ import annotations

import json
import subprocess
import sys
import unittest
from importlib import util
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/verify_pilot_clearance.py"
SCRIPT_PATH = REPO_ROOT / SCRIPT
SPEC = util.spec_from_file_location("verify_pilot_clearance", SCRIPT_PATH)
assert SPEC is not None
verify_pilot_clearance = util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(verify_pilot_clearance)

RELEASE_COMMIT = "a" * 40
RELEASE_DIGEST = f"sha256:{'b' * 64}"


def health_packet(*, commit: str | None = RELEASE_COMMIT, image_digest: str | None = RELEASE_DIGEST) -> dict[str, Any]:
    return {
        "status": "ok",
        "timestamp": "2026-05-07T23:30:00Z",
        "commit": commit,
        "image_digest": image_digest,
    }


def readiness_packet(*, status: str = "ready", blockers: list[str] | None = None) -> dict[str, Any]:
    return {
        "profile": "pilot",
        "status": status,
        "checked_at": "2026-05-07T23:30:01Z",
        "blockers": [] if blockers is None else blockers,
    }


def go_no_go_packet(
    *,
    status: str = "go",
    missing_evidence: list[str] | None = None,
    release_status: str = "complete",
) -> dict[str, Any]:
    missing = [] if missing_evidence is None else missing_evidence
    release_missing = [] if release_status == "complete" else ["runtime_build_commit"]
    return {
        "packet_version": "pilot.go_no_go.v1",
        "status": status,
        "generated_at": "2026-05-07T23:30:02Z",
        "missing_evidence": missing,
        "checks": {
            "readiness_green": True,
            "release_provenance_complete": status == "go",
        },
        "release_provenance": {
            "schema_version": "mesh.release_provenance.v1",
            "status": release_status,
            "missing": release_missing,
            "checks": {
                "git_commit": True,
                "image_digest": True,
                "ci_attestation": True,
            },
            "packet_sha256": "c" * 64,
            "git": {"commit": RELEASE_COMMIT},
            "image": {"digest": RELEASE_DIGEST},
        },
    }


class PilotClearanceAuditTests(unittest.TestCase):
    def test_passes_when_live_readiness_go_no_go_and_runtime_binding_match(self) -> None:
        result = verify_pilot_clearance.verify_pilot_clearance(
            base_url="http://mesh.local",
            requester=_requester(
                health=health_packet(),
                readiness=readiness_packet(),
                go_no_go=go_no_go_packet(),
            ),
        )

        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["missing"], [])
        self.assertTrue(result["checks"]["runtime_build_commit_match"])
        self.assertTrue(result["checks"]["runtime_image_digest_match"])

    def test_fails_current_runtime_binding_blocker(self) -> None:
        result = verify_pilot_clearance.verify_pilot_clearance(
            base_url="http://mesh.local",
            requester=_requester(
                health=health_packet(commit="unknown", image_digest=None),
                readiness=readiness_packet(),
                go_no_go=go_no_go_packet(
                    status="blocked",
                    missing_evidence=["release_provenance_complete"],
                    release_status="incomplete",
                ),
            ),
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("go_no_go_status_go", result["missing"])
        self.assertIn("release_provenance_complete", result["missing"])
        self.assertIn("runtime_build_commit", result["missing"])
        self.assertIn("runtime_image_digest", result["missing"])
        self.assertIn("runtime_build_commit_match", result["missing"])
        self.assertIn("runtime_image_digest_match", result["missing"])
        self.assertEqual(result["artifacts"]["runtime_binding"]["build_commit"], None)
        self.assertEqual(result["artifacts"]["runtime_binding"]["image_digest"], None)

    def test_fails_readiness_blockers_even_when_release_binding_matches(self) -> None:
        result = verify_pilot_clearance.verify_pilot_clearance(
            base_url="http://mesh.local",
            requester=_requester(
                health=health_packet(),
                readiness=readiness_packet(status="blocked", blockers=["state_backend_postgres"]),
                go_no_go=go_no_go_packet(),
            ),
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("readiness_ready", result["missing"])
        self.assertIn("readiness_blockers_empty", result["missing"])
        self.assertEqual(result["artifacts"]["readiness"]["blockers"], ["state_backend_postgres"])

    def test_cli_returns_nonzero_when_endpoint_request_fails(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--base-url",
                "http://127.0.0.1:9",
                "--timeout-seconds",
                "0.1",
                "--json",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "fail")
        self.assertIn("health_status_ok", payload["missing"])


def _requester(
    *,
    health: dict[str, Any],
    readiness: dict[str, Any],
    go_no_go: dict[str, Any],
) -> Any:
    responses = {
        "/api/health": health,
        "/api/readiness": readiness,
        "/api/pilot/go-no-go": go_no_go,
    }

    def request(url: str, timeout_seconds: float) -> dict[str, Any]:
        del timeout_seconds
        for suffix, payload in responses.items():
            if url.endswith(suffix):
                return payload
        raise AssertionError(f"unexpected URL: {url}")

    return request


if __name__ == "__main__":
    unittest.main()
