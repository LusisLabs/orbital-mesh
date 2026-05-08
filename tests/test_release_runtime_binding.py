from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import util
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/verify_release_runtime_binding.py"
RUNTIME_BINDING_PATH = REPO_ROOT / SCRIPT
RUNTIME_BINDING_SPEC = util.spec_from_file_location("verify_release_runtime_binding", RUNTIME_BINDING_PATH)
assert RUNTIME_BINDING_SPEC is not None
verify_release_runtime_binding = util.module_from_spec(RUNTIME_BINDING_SPEC)
assert RUNTIME_BINDING_SPEC.loader is not None
RUNTIME_BINDING_SPEC.loader.exec_module(verify_release_runtime_binding)
RELEASE_COMMIT = "a" * 40
RELEASE_DIGEST = f"sha256:{'b' * 64}"


def release_packet(
    *,
    git_commit: str | None = RELEASE_COMMIT,
    image_digest: str | None = RELEASE_DIGEST,
    status: str = "complete",
    missing: list[str] | None = None,
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": "mesh.release_provenance.v1",
        "status": status,
        "missing": [] if missing is None else missing,
        "checks": {
            "git_commit": True,
            "image_digest": True,
            "ci_attestation": True,
        },
        "ci": {
            "attestation": {
                "provider": "github-actions",
                "run_id": "ci-run-1",
                "sha": git_commit,
                "expected_sha": git_commit,
                "sha_matches_git_commit": True,
            }
        },
        "packet_sha256": "c" * 64,
    }
    if git_commit is not None:
        packet["git"] = {"commit": git_commit}
    if image_digest is not None:
        packet["image"] = {"digest": image_digest}
    return packet


class ReleaseRuntimeBindingTests(unittest.TestCase):
    def test_rejects_runtime_env_without_binding_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "release-provenance.json"
            env_path = Path(tmp) / "release-runtime.env"
            packet_path.write_text(json.dumps(release_packet()) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--release-provenance",
                    str(packet_path),
                    "--runtime-release-provenance-path",
                    "/app/.mesh-runtime-state/release-provenance.json",
                    "--env-output",
                    str(env_path),
                    "--json",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "fail")
            self.assertIn("env_output_binding_evidence", payload["missing"])
            self.assertFalse(env_path.exists())

    def test_generates_runtime_env_after_health_binding_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "release-provenance.json"
            env_path = Path(tmp) / "release-runtime.env"
            packet_path.write_text(json.dumps(release_packet()) + "\n", encoding="utf-8")
            server = _start_health_server(
                {
                    "status": "ok",
                    "commit": RELEASE_COMMIT,
                    "image_digest": RELEASE_DIGEST,
                }
            )
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        SCRIPT,
                        "--release-provenance",
                        str(packet_path),
                        "--runtime-release-provenance-path",
                        "/app/.mesh-runtime-state/release-provenance.json",
                        "--health-url",
                        f"http://127.0.0.1:{server.server_address[1]}/api/health",
                        "--env-output",
                        str(env_path),
                        "--json",
                    ],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                server.shutdown()
                server.server_close()

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(
                env_path.read_text(encoding="utf-8").splitlines(),
                [
                    "MESH_RELEASE_PROVENANCE_PATH=/app/.mesh-runtime-state/release-provenance.json",
                    f"MESH_BUILD_COMMIT={RELEASE_COMMIT}",
                    f"MESH_BUILD_IMAGE_DIGEST={RELEASE_DIGEST}",
                ],
            )

    def test_generates_runtime_env_with_verified_image_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "release-provenance.json"
            packet_path.write_text(json.dumps(release_packet()) + "\n", encoding="utf-8")

            def fake_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
                payload = [
                    {
                        "Id": RELEASE_DIGEST,
                        "RepoDigests": [f"registry.example/orbital-mesh@{RELEASE_DIGEST}"],
                    }
                ]
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

            payload = verify_release_runtime_binding.verify_release_runtime_binding(
                release_provenance=packet_path,
                runtime_release_provenance_path="/app/.mesh-runtime-state/release-provenance.json",
                image_ref="orbital-mesh:release",
                runner=fake_runner,
            )

            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["runtime_env"]["MESH_IMAGE"], "orbital-mesh:release")
            self.assertEqual(payload["runtime_env"]["MESH_STACK_IMAGE"], "orbital-mesh:release")
            self.assertEqual(payload["runtime_env"]["MESH_BUILD_COMMIT"], RELEASE_COMMIT)
            self.assertEqual(payload["runtime_env"]["MESH_BUILD_IMAGE_DIGEST"], RELEASE_DIGEST)

    def test_rejects_incomplete_packet_without_writing_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "release-provenance.json"
            env_path = Path(tmp) / "release-runtime.env"
            packet_path.write_text(
                json.dumps(release_packet(status="incomplete", missing=["ci_attestation"])) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--release-provenance",
                    str(packet_path),
                    "--env-output",
                    str(env_path),
                    "--json",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "fail")
            self.assertIn("release_provenance_complete", payload["missing"])
            self.assertFalse(env_path.exists())

    def test_health_url_must_match_packet_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "release-provenance.json"
            packet_path.write_text(json.dumps(release_packet()) + "\n", encoding="utf-8")
            server = _start_health_server(
                {
                    "status": "ok",
                    "commit": RELEASE_COMMIT,
                    "image_digest": f"sha256:{'d' * 64}",
                }
            )
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        SCRIPT,
                        "--release-provenance",
                        str(packet_path),
                        "--health-url",
                        f"http://127.0.0.1:{server.server_address[1]}/api/health",
                        "--json",
                    ],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                server.shutdown()
                server.server_close()

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertIn("runtime_image_digest_match", payload["missing"])
            self.assertNotIn("runtime_build_commit_match", payload["missing"])

    def test_image_ref_reports_invalid_docker_inspect_json_as_failed_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "release-provenance.json"
            packet_path.write_text(json.dumps(release_packet()) + "\n", encoding="utf-8")

            def fake_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout="{", stderr="")

            payload = verify_release_runtime_binding.verify_release_runtime_binding(
                release_provenance=packet_path,
                runtime_release_provenance_path="/app/.mesh-runtime-state/release-provenance.json",
                image_ref="orbital-mesh:release",
                runner=fake_runner,
            )

            self.assertEqual(payload["status"], "fail")
            self.assertIn("image_ref_digest_match", payload["missing"])
            self.assertIn("invalid JSON", payload["image_ref"]["error"])


def _start_health_server(payload: dict[str, Any]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    unittest.main()
