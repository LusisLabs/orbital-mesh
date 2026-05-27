from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from tests.test_on_call_drill import _proof as _on_call_drill


class ProductionLiveProofBundleTests(unittest.TestCase):
    def test_capture_script_collects_live_api_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "capture"
            server = _CaptureServer(("127.0.0.1", 0), _CaptureHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "scripts/capture_production_live_proof_bundle.py",
                        "--base-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--output-dir",
                        str(output),
                        "--release-provenance",
                        str(root / "release-provenance.json"),
                        "--release-runtime-binding",
                        str(root / "release-runtime-binding.json"),
                        "--on-call-drill",
                        str(root / "on-call-drill.json"),
                        "--timeout-seconds",
                        "10",
                        "--skip-generate",
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            stdout = json.loads(completed.stdout)
            self.assertEqual(stdout["status"], "captured")
            manifest = json.loads((output / "capture-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "mesh.production_live_proof_capture.v1")
            self.assertEqual(manifest["target_run_id"], "run_target")
            self.assertEqual(manifest["repeat_run_id"], "run_repeat")
            self.assertEqual(json.loads(Path(manifest["denied_action"]).read_text(encoding="utf-8"))["http_status"], 403)
            for section in ("target", "repeat"):
                for name in ("run", "events", "export", "timeline", "merkle"):
                    self.assertTrue(Path(manifest[section][name]).exists(), (section, name))

    def test_generator_writes_current_head_bundle_and_clearance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            output = root / "bundle"
            head = "a" * 40
            _write_inputs(artifacts, head=head)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_production_live_proof_bundle.py",
                    "--repo-root",
                    str(repo),
                    "--repo-head",
                    head,
                    "--output-dir",
                    str(output),
                    "--environment",
                    "pilot",
                    "--operator-id",
                    "launcher@example.com",
                    "--operator-identity-ref",
                    "proxy-header://X-Mesh-Operator/launcher@example.com",
                    "--approver-identity-ref",
                    "proxy-header://X-Mesh-Operator/approver@example.com",
                    "--target-ref",
                    "kubernetes://pilot/edge/api-gateway",
                    "--repeat-target-ref",
                    "kubernetes://pilot/edge/repeatability",
                    "--healthy-target-ref",
                    "kubernetes://pilot/edge/healthy-control",
                    "--provider-failure-target-ref",
                    "kubernetes://pilot/edge/provider",
                    "--ingress-url",
                    "https://mesh.pilot.local",
                    "--authenticated-ingress-ref",
                    "artifact://authenticated-ingress-deployment-proof.json",
                    "--credential-rotation-ref",
                    "rotation://mesh/pilot/2026-05-23",
                    "--rollback-ref",
                    "rollback://kubernetes/pilot/edge/api-gateway",
                    "--runtime-secret-ref",
                    "secret://mesh/kubernetes-service-account",
                    "--health",
                    str(artifacts / "health.json"),
                    "--readiness",
                    str(artifacts / "readiness.json"),
                    "--kill-switch",
                    str(artifacts / "kill-switch.json"),
                    "--denied-action",
                    str(artifacts / "denied-action.json"),
                    "--release-provenance",
                    str(artifacts / "release-provenance.json"),
                    "--release-runtime-binding",
                    str(artifacts / "release-runtime-binding.json"),
                    "--on-call-drill",
                    str(artifacts / "on-call-drill.json"),
                    "--target-run-json",
                    str(artifacts / "target-run.json"),
                    "--target-events",
                    str(artifacts / "target-events.json"),
                    "--target-export",
                    str(artifacts / "target-export.json"),
                    "--target-timeline",
                    str(artifacts / "target-timeline.json"),
                    "--target-merkle",
                    str(artifacts / "target-merkle.json"),
                    "--repeat-run-json",
                    str(artifacts / "repeat-run.json"),
                    "--repeat-events",
                    str(artifacts / "repeat-events.json"),
                    "--repeat-export",
                    str(artifacts / "repeat-export.json"),
                    "--repeat-timeline",
                    str(artifacts / "repeat-timeline.json"),
                    "--repeat-merkle",
                    str(artifacts / "repeat-merkle.json"),
                    "--build-command",
                    "docker build --pull -t orbital-mesh-stack:proof .",
                    "--target-run-command",
                    "POST /api/runs target proof",
                    "--repeat-run-command",
                    "POST /api/runs repeat proof",
                    "--clean-env-recreated",
                    "--fresh-image-built",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )

            stdout = json.loads(completed.stdout)
            self.assertEqual(stdout["status"], "pass")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "pass")
            self.assertEqual(manifest["repo_head"], head)
            self.assertEqual(manifest["target_run_id"], "run_target_live")
            self.assertEqual(manifest["repeat_run_id"], "run_repeat_live")

            for path in (
                output / "proofs" / "production-target-proof.json",
                output / "proofs" / "watch-mode-proof.json",
                output / "proofs" / "incident-coverage-proof.json",
                output / "proofs" / "repeatability-proof.json",
                output / "verifications" / "production-autonomy-clearance.json",
            ):
                self.assertTrue(path.exists(), path)

            clearance = json.loads((output / "verifications" / "production-autonomy-clearance.json").read_text(encoding="utf-8"))
            self.assertEqual(clearance["status"], "pass")
            self.assertEqual(clearance["missing"], [])

    def test_generator_requires_runtime_binding_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            output = root / "bundle"
            head = "a" * 40
            _write_inputs(artifacts, head=head)
            image_digest = "sha256:" + "c" * 64
            weak_binding = _release_runtime_binding(head=head, image_digest=image_digest)
            weak_binding.pop("health")
            _write(artifacts / "release-runtime-binding.json", weak_binding)

            completed = subprocess.run(
                [
                    *_generator_command(repo_root=repo, output=output, artifacts=artifacts, head=head),
                    "--clean-env-recreated",
                    "--fresh-image-built",
                    "--allow-partial",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )

            stdout = json.loads(completed.stdout)
            self.assertEqual(stdout["status"], "partial")
            self.assertIn("release_runtime_binding:runtime_binding_evidence_present", stdout["missing"])
            verification = json.loads(
                (output / "verifications" / "release-runtime-binding-verification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(verification["status"], "fail")
            self.assertIn("runtime_binding_evidence_present", verification["missing"])

    def test_generator_records_dirty_or_incomplete_repeatability_as_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            output = root / "bundle"
            head = "b" * 40
            _write_inputs(artifacts, head=head)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_production_live_proof_bundle.py",
                    "--repo-root",
                    str(root / "not-a-git-repo"),
                    "--repo-head",
                    head,
                    "--output-dir",
                    str(output),
                    "--environment",
                    "pilot",
                    "--operator-id",
                    "launcher@example.com",
                    "--operator-identity-ref",
                    "proxy-header://X-Mesh-Operator/launcher@example.com",
                    "--approver-identity-ref",
                    "proxy-header://X-Mesh-Operator/approver@example.com",
                    "--target-ref",
                    "kubernetes://pilot/edge/api-gateway",
                    "--repeat-target-ref",
                    "kubernetes://pilot/edge/repeatability",
                    "--healthy-target-ref",
                    "kubernetes://pilot/edge/healthy-control",
                    "--provider-failure-target-ref",
                    "kubernetes://pilot/edge/provider",
                    "--ingress-url",
                    "https://mesh.pilot.local",
                    "--authenticated-ingress-ref",
                    "artifact://authenticated-ingress-deployment-proof.json",
                    "--credential-rotation-ref",
                    "rotation://mesh/pilot/2026-05-23",
                    "--rollback-ref",
                    "rollback://kubernetes/pilot/edge/api-gateway",
                    "--runtime-secret-ref",
                    "secret://mesh/kubernetes-service-account",
                    "--health",
                    str(artifacts / "health.json"),
                    "--readiness",
                    str(artifacts / "readiness.json"),
                    "--kill-switch",
                    str(artifacts / "kill-switch.json"),
                    "--denied-action",
                    str(artifacts / "denied-action.json"),
                    "--release-provenance",
                    str(artifacts / "release-provenance.json"),
                    "--release-runtime-binding",
                    str(artifacts / "release-runtime-binding.json"),
                    "--on-call-drill",
                    str(artifacts / "on-call-drill.json"),
                    "--target-run-json",
                    str(artifacts / "target-run.json"),
                    "--target-events",
                    str(artifacts / "target-events.json"),
                    "--target-export",
                    str(artifacts / "target-export.json"),
                    "--target-timeline",
                    str(artifacts / "target-timeline.json"),
                    "--target-merkle",
                    str(artifacts / "target-merkle.json"),
                    "--repeat-run-json",
                    str(artifacts / "repeat-run.json"),
                    "--repeat-events",
                    str(artifacts / "repeat-events.json"),
                    "--repeat-export",
                    str(artifacts / "repeat-export.json"),
                    "--repeat-timeline",
                    str(artifacts / "repeat-timeline.json"),
                    "--repeat-merkle",
                    str(artifacts / "repeat-merkle.json"),
                    "--build-command",
                    "docker build --pull -t orbital-mesh-stack:proof .",
                    "--target-run-command",
                    "POST /api/runs target proof",
                    "--repeat-run-command",
                    "POST /api/runs repeat proof",
                    "--allow-partial",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )

            stdout = json.loads(completed.stdout)
            self.assertEqual(stdout["status"], "partial")
            self.assertIn("repeatability_passed", stdout["missing"])


def _write_inputs(root: Path, *, head: str) -> None:
    image_digest = "sha256:" + "c" * 64
    _write(root / "health.json", {"status": "ok", "commit": head, "image_digest": image_digest})
    _write(root / "readiness.json", {"status": "ready"})
    _write(root / "kill-switch.json", {"status": "ok", "watchers_paused": True})
    _write(root / "denied-action.json", {"status": "denied"})
    _write(root / "release-runtime-binding.json", _release_runtime_binding(head=head, image_digest=image_digest))
    _write(
        root / "release-provenance.json",
        {
            "schema_version": "mesh.release_provenance.v1",
            "generated_at": "2026-05-23T00:00:00Z",
            "status": "complete",
            "git": {"commit": head},
            "image": {"digest": image_digest},
        },
    )
    on_call = _on_call_drill()
    on_call["environment"] = "pilot"
    _write(root / "on-call-drill.json", on_call)
    for prefix, run_id in (("target", "run_target_live"), ("repeat", "run_repeat_live")):
        _write(root / f"{prefix}-run.json", {"run_id": run_id})
        _write(root / f"{prefix}-events.json", {"run_id": run_id, "events": []})
        _write(root / f"{prefix}-export.json", {"run_id": run_id, "decision_record": {}, "evaluation_record": {}, "execution_record": {}, "feedback_record": {}})
        _write(root / f"{prefix}-timeline.json", {"run_id": run_id, "timeline": []})
        _write(root / f"{prefix}-merkle.json", {"run_id": run_id, "merkle_root": "d" * 64})


def _generator_command(*, repo_root: Path, output: Path, artifacts: Path, head: str) -> list[str]:
    return [
        sys.executable,
        "scripts/generate_production_live_proof_bundle.py",
        "--repo-root",
        str(repo_root),
        "--repo-head",
        head,
        "--output-dir",
        str(output),
        "--environment",
        "pilot",
        "--operator-id",
        "launcher@example.com",
        "--operator-identity-ref",
        "proxy-header://X-Mesh-Operator/launcher@example.com",
        "--approver-identity-ref",
        "proxy-header://X-Mesh-Operator/approver@example.com",
        "--target-ref",
        "kubernetes://pilot/edge/api-gateway",
        "--repeat-target-ref",
        "kubernetes://pilot/edge/repeatability",
        "--healthy-target-ref",
        "kubernetes://pilot/edge/healthy-control",
        "--provider-failure-target-ref",
        "kubernetes://pilot/edge/provider",
        "--ingress-url",
        "https://mesh.pilot.local",
        "--authenticated-ingress-ref",
        "artifact://authenticated-ingress-deployment-proof.json",
        "--credential-rotation-ref",
        "rotation://mesh/pilot/2026-05-23",
        "--rollback-ref",
        "rollback://kubernetes/pilot/edge/api-gateway",
        "--runtime-secret-ref",
        "secret://mesh/kubernetes-service-account",
        "--health",
        str(artifacts / "health.json"),
        "--readiness",
        str(artifacts / "readiness.json"),
        "--kill-switch",
        str(artifacts / "kill-switch.json"),
        "--denied-action",
        str(artifacts / "denied-action.json"),
        "--release-provenance",
        str(artifacts / "release-provenance.json"),
        "--release-runtime-binding",
        str(artifacts / "release-runtime-binding.json"),
        "--on-call-drill",
        str(artifacts / "on-call-drill.json"),
        "--target-run-json",
        str(artifacts / "target-run.json"),
        "--target-events",
        str(artifacts / "target-events.json"),
        "--target-export",
        str(artifacts / "target-export.json"),
        "--target-timeline",
        str(artifacts / "target-timeline.json"),
        "--target-merkle",
        str(artifacts / "target-merkle.json"),
        "--repeat-run-json",
        str(artifacts / "repeat-run.json"),
        "--repeat-events",
        str(artifacts / "repeat-events.json"),
        "--repeat-export",
        str(artifacts / "repeat-export.json"),
        "--repeat-timeline",
        str(artifacts / "repeat-timeline.json"),
        "--repeat-merkle",
        str(artifacts / "repeat-merkle.json"),
        "--build-command",
        "docker build --pull -t orbital-mesh-stack:proof .",
        "--target-run-command",
        "POST /api/runs target proof",
        "--repeat-run-command",
        "POST /api/runs repeat proof",
    ]


class _CaptureServer(ThreadingHTTPServer):
    runs: dict[str, dict[str, object]]

    def __init__(self, server_address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(server_address, handler)
        self.runs = {}
        self.created = 0


class _CaptureHandler(BaseHTTPRequestHandler):
    server: _CaptureServer

    def log_message(self, _format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send({"status": "ok", "commit": "a" * 40, "image_digest": "sha256:" + "1" * 64})
            return
        if path == "/api/readiness":
            self._send({"status": "ready", "profile": "pilot", "blockers": []})
            return
        if path == "/api/kill-switch":
            self._send({"status": "armed", "watchers_paused": True})
            return
        if path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = path.split("/")[3]
            self._send({"events": [{"event_id": f"evt-{run_id}", "sequence": 1, "event_type": "completed"}]})
            return
        if path.startswith("/api/runs/") and path.endswith("/timeline-proof"):
            run_id = path.split("/")[3]
            self._send({"schema_version": "mesh.timeline_proof.v1", "run_id": run_id, "timeline": [{"event_id": f"evt-{run_id}"}]})
            return
        if path.startswith("/api/runs/") and path.endswith("/merkle"):
            run_id = path.split("/")[3]
            self._send({"run_id": run_id, "root_hash": "abc123", "leaf_count": 1})
            return
        if path.startswith("/api/runs/"):
            run_id = path.split("/")[3]
            self._send(self.server.runs[run_id])
            return
        self._send({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/runs":
            self.server.created += 1
            run_id = "run_target" if self.server.created == 1 else "run_repeat"
            self.server.runs[run_id] = _fake_run(run_id, stage="evaluation_ready")
            self._send({"run_id": run_id}, status=201)
            return
        if path.startswith("/api/runs/") and path.endswith("/steer"):
            if self.headers.get("X-Mesh-Roles") == "launcher":
                self._send({"error": "role approver required"}, status=403)
                return
            run_id = path.split("/")[3]
            self.server.runs[run_id] = _fake_run(run_id, stage="completed")
            self._send(self.server.runs[run_id])
            return
        if path.startswith("/api/runs/") and path.endswith("/export"):
            run_id = path.split("/")[3]
            self._send(
                {
                    "package_version": "mesh.run_export.v1",
                    "run_id": run_id,
                    "decision_record": {"decision_type": "disable_flag"},
                    "evaluation_record": {"passed": True, "final_recommendation": "execute"},
                    "execution_record": {"status": "succeeded"},
                    "feedback_record": {"outcome": "recovered"},
                    "postmortem_markdown": "# Postmortem",
                    "timeline_json": [{"event_id": f"evt-{run_id}"}],
                }
            )
            return
        self._send({"error": "not found"}, status=404)

    def _send(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _fake_run(run_id: str, *, stage: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "stage": stage,
        "status": stage,
        "pending_pause_stage": "evaluation_ready" if stage == "awaiting_operator" else None,
        "scenario_key": "search_latency_regression",
        "artifacts": {
            "decision": {"decision_type": "disable_flag"},
            "evaluation": {"passed": True, "final_recommendation": "execute"},
            "execution": {"status": "succeeded"} if stage == "completed" else None,
            "feedback": {"outcome": "recovered"} if stage == "completed" else None,
        },
    }


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _release_runtime_binding(*, head: str, image_digest: str) -> dict[str, object]:
    return {
        "schema_version": "mesh.release_runtime_binding.v1",
        "generated_at": "2026-05-23T00:00:00Z",
        "status": "pass",
        "release_provenance_path": "release-provenance.json",
        "runtime_env": {
            "MESH_RELEASE_PROVENANCE_PATH": "/app/.mesh-runtime-state/release-provenance.json",
            "MESH_BUILD_COMMIT": head,
            "MESH_BUILD_IMAGE_DIGEST": image_digest,
        },
        "release": {
            "packet_sha256": "e" * 64,
            "git_commit": head,
            "image_digest": image_digest,
            "checks": {
                "schema_version": True,
                "release_provenance_complete": True,
                "release_provenance_missing_empty": True,
                "release_provenance_checks": True,
                "ci_attestation_sha_matches_git_commit": True,
                "release_git_commit": True,
                "release_image_digest": True,
            },
            "missing": [],
        },
        "health": {
            "url": "http://127.0.0.1:8787/api/health",
            "commit": head,
            "image_digest": image_digest,
            "commit_match": True,
            "image_digest_match": True,
        },
        "checks": {
            "schema_version": True,
            "release_provenance_complete": True,
            "release_provenance_missing_empty": True,
            "release_provenance_checks": True,
            "ci_attestation_sha_matches_git_commit": True,
            "release_git_commit": True,
            "release_image_digest": True,
            "runtime_build_commit_match": True,
            "runtime_image_digest_match": True,
        },
        "missing": [],
    }


if __name__ == "__main__":
    unittest.main()
