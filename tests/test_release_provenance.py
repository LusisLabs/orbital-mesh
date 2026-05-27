from __future__ import annotations

import json
import os
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/generate_release_provenance.py"


def sbom_json(image_digest: str, *, bom_format: str = "CycloneDX") -> str:
    return (
        json.dumps(
            {
                "bomFormat": bom_format,
                "metadata": {
                    "properties": [
                        {"name": "mesh:image_digest", "value": image_digest},
                    ]
                },
            }
        )
        + "\n"
    )


def vulnerability_scan_json(image_digest: str, *, findings: list[dict[str, object]] | None = None) -> str:
    return (
        json.dumps(
            {
                "scanner": "test",
                "image_digest": image_digest,
                "findings": findings or [],
            }
        )
        + "\n"
    )


def write_ci_attestation(
    path: Path,
    *,
    provider: str = "github-actions",
    workflow: str = "CI",
    job: str = "docker-build",
    run_id: str = "run-1",
    sha: str | None = None,
    image_digest: str | None = None,
    build_command: str | None = None,
    base_images: list[dict[str, str]] | None = None,
    checks: list[str] | None = None,
    check_records: list[dict[str, str]] | None = None,
) -> None:
    attested_image_digest = image_digest or f"sha256:{'a' * 64}"
    packet: dict[str, object] = {
        "schema_version": "mesh.ci_attestation.v1",
        "generated_at": "2026-05-05T00:00:00Z",
        "provider": provider,
        "workflow": workflow,
        "job": job,
        "run_id": run_id,
        "repository": "example/orbital-mesh",
        "ref": "refs/heads/main",
        "sha": sha or current_git_commit(),
        "server_url": "https://github.com",
        "image": {"tag": "orbital-mesh:ci", "digest": attested_image_digest},
        "build": {
            "command": build_command,
            "base_images": base_images or [],
        },
        "checks": check_records
        if check_records is not None
        else [{"name": name, "status": "passed"} for name in (checks or ["python-test", "web", "docker-build"])],
    }
    packet["attestation_sha256"] = payload_hash(packet)
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def payload_hash(payload: dict[str, object]) -> str:
    unsigned_payload = dict(payload)
    unsigned_payload.pop("attestation_sha256", None)
    raw = json.dumps(unsigned_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def migration_rehearsal_json(discovered: dict[str, object]) -> str:
    migrations = discovered["migrations"]
    assert isinstance(migrations, dict)
    version = str(migrations["version"])
    combined_sha256 = str(migrations["combined_sha256"])
    hashes = migrations["hashes"]
    assert isinstance(hashes, list)
    return (
        json.dumps(
            {
                "schema_version": "mesh.migration_rehearsal.v1",
                "rehearsal_id": "migration_rehearsal_test",
                "generated_at": "2026-05-05T23:30:00Z",
                "operator_id": "platform@example.com",
                "environment": "staging",
                "database_engine": "postgres",
                "migration_directory": "migrations/postgres",
                "migration_version": version,
                "migration_combined_sha256": combined_sha256,
                "applied_migration_count": len(hashes),
                "rolled_back": True,
                "rollback_ref": "restore://postgres/migration-rehearsal/test",
                "pre_migration_snapshot_ref": "snapshot://postgres/pre-migration/test",
                "post_migration_validation_ref": "validation://postgres/post-migration/test",
                "destructive_changes_reviewed": True,
                "measured_apply_seconds": 12.5,
                "measured_rollback_seconds": 18.25,
            }
        )
        + "\n"
    )


class ReleaseProvenanceTests(unittest.TestCase):
    def test_ci_attestation_generator_records_github_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ci-attestation.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_ci_attestation.py",
                    "--output",
                    str(output),
                    "--check",
                    "python-test",
                    "--check",
                    "docker-build",
                    "--image-tag",
                    "orbital-mesh:ci",
                    "--image-digest",
                    f"sha256:{'b' * 64}",
                    "--source-sha",
                    "def456",
                    "--build-command",
                    "docker build -t orbital-mesh:ci .",
                    "--base-image-digest",
                    f"python:3.12-slim-bookworm=sha256:{'d' * 64}",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_WORKFLOW": "CI",
                    "GITHUB_JOB": "docker-build",
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_SHA": "abc123",
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            packet = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(packet["schema_version"], "mesh.ci_attestation.v1")
            self.assertEqual(packet["provider"], "github-actions")
            self.assertEqual(packet["workflow"], "CI")
            self.assertEqual(packet["job"], "docker-build")
            self.assertEqual(packet["sha"], "def456")
            self.assertEqual(packet["run_sha"], "abc123")
            self.assertEqual(packet["image"]["digest"], f"sha256:{'b' * 64}")
            self.assertEqual(
                packet["build"]["base_images"],
                [{"image": "python:3.12-slim-bookworm", "digest": f"sha256:{'d' * 64}"}],
            )
            self.assertEqual([item["name"] for item in packet["checks"]], ["python-test", "docker-build"])
            self.assertRegex(packet["attestation_sha256"], r"^[0-9a-f]{64}$")

    def test_ci_attestation_generator_records_explicit_check_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ci-attestation.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_ci_attestation.py",
                    "--output",
                    str(output),
                    "--check",
                    "python-test",
                    "--check-status",
                    "web=passed",
                    "--check-status",
                    "docker-build=failed",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_WORKFLOW": "CI",
                    "GITHUB_JOB": "docker-build",
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_SHA": "abc123",
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            packet = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                packet["checks"],
                [
                    {"name": "python-test", "status": "passed"},
                    {"name": "web", "status": "passed"},
                    {"name": "docker-build", "status": "failed"},
                ],
            )
            self.assertRegex(packet["attestation_sha256"], r"^[0-9a-f]{64}$")

    def test_ci_attestation_generator_requires_github_actions_context_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ci-attestation.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_ci_attestation.py",
                    "--output",
                    str(output),
                    "--require-github-actions",
                    "--check",
                    "docker-build",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                env={key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            self.assertIn("GITHUB_ACTIONS=true", result.stderr)

    def test_provenance_packet_reports_required_fields_and_missing_gates(self) -> None:
        result = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["schema_version"], "mesh.release_provenance.v1")
        self.assertIn(packet["status"], {"complete", "incomplete"})
        self.assertIn("git", packet)
        self.assertIn("image", packet)
        self.assertIn("base_images", packet)
        self.assertIn("dependency_locks", packet)
        self.assertIn("policies", packet)
        self.assertIn("connectors", packet)
        self.assertIn("deployment", packet)
        self.assertIn("migrations", packet)
        self.assertIn("ci", packet)
        self.assertIn("packet_sha256", packet)
        self.assertTrue(packet["policies"]["hashes"])
        self.assertEqual(packet["policies"]["lifecycle"]["status"], "incomplete")
        self.assertIn("policy_hash_signature", packet["policies"]["lifecycle"]["missing"])
        self.assertEqual(packet["connectors"]["certification"]["status"], "complete")
        self.assertEqual(packet["deployment"]["compatibility"]["status"], "complete")
        self.assertTrue(packet["migrations"]["version"])
        self.assertIn("rehearsal", packet["migrations"])
        self.assertEqual(packet["migrations"]["rehearsal"]["status"], "fail")

    def test_require_complete_fails_without_ci_artifacts(self) -> None:
        result = subprocess.run(
            [sys.executable, SCRIPT, "--json", "--require-complete"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["status"], "incomplete")
        self.assertIn("image_digest", packet["missing"])
        self.assertIn("sbom_path", packet["missing"])
        self.assertIn("vulnerability_scan_path", packet["missing"])
        self.assertIn("ci_attestation", packet["missing"])
        self.assertIn("policy_lifecycle_signed", packet["missing"])
        self.assertIn("migration_rehearsal", packet["missing"])

    def test_missing_policy_signing_key_path_keeps_packet_incomplete_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_key = Path(tmp) / "missing-policy-signing-key"
            result = subprocess.run(
                [sys.executable, SCRIPT, "--json"],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "MESH_POLICY_SIGNING_KEY_PATH": str(missing_key)},
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            packet = json.loads(result.stdout)
            self.assertEqual(packet["policies"]["lifecycle"]["status"], "incomplete")
            self.assertIn("policy_hash_signature", packet["policies"]["lifecycle"]["missing"])

    def test_build_image_digest_env_alias_supplies_release_image_digest(self) -> None:
        image_digest = f"sha256:{'d' * 64}"
        result = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "MESH_IMAGE_DIGEST": "",
                "MESH_STACK_IMAGE_DIGEST": "",
                "MESH_BUILD_IMAGE_DIGEST": image_digest,
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["image"]["digest"], image_digest)
        self.assertNotIn("image_digest", packet["missing"])

    def test_require_complete_rejects_placeholder_ci_attestation(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_args: list[str] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            image = item["image"]
            digest = f"sha256:{index:064x}"[-71:]
            base_args.extend(["--base-image-digest", f"{image}={digest}"])

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            image_digest = f"sha256:{'a' * 64}"
            sbom.write_text(sbom_json(image_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(image_digest), encoding="utf-8")
            ci_attestation.write_text('{"provider":"test-ci","run_id":"run-1"}\n', encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key",
                    "test-policy-signing-key",
                    *base_args,
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            packet = json.loads(result.stdout)
            self.assertIn("ci_attestation", packet["missing"])
            self.assertFalse(packet["ci"]["attestation"]["valid"])
            self.assertEqual(
                packet["ci"]["attestation"]["missing"],
                [
                    "schema_version:mesh.ci_attestation.v1",
                    "attestation_sha256",
                    "provider:github-actions",
                    "workflow",
                    "job",
                    "sha",
                    "image_digest_match",
                    "check:docker-build",
                    "check:python-test",
                    "check:web",
                ],
            )

    def test_require_complete_rejects_local_ci_attestation_even_with_hash_and_checks(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_args: list[str] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            image = item["image"]
            digest = f"sha256:{index:064x}"[-71:]
            base_args.extend(["--base-image-digest", f"{image}={digest}"])

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            image_digest = f"sha256:{'a' * 64}"
            sbom.write_text(sbom_json(image_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(image_digest), encoding="utf-8")
            write_ci_attestation(ci_attestation, provider="local")
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key",
                    "test-policy-signing-key",
                    *base_args,
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            packet = json.loads(result.stdout)
            self.assertIn("ci_attestation", packet["missing"])
            self.assertFalse(packet["ci"]["attestation"]["valid"])
            self.assertTrue(packet["ci"]["attestation"]["hash_valid"])
            self.assertEqual(packet["ci"]["attestation"]["missing"], ["provider:github-actions"])

    def test_require_complete_rejects_stale_ci_attestation_sha(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_args: list[str] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            image = item["image"]
            digest = f"sha256:{index:064x}"[-71:]
            base_args.extend(["--base-image-digest", f"{image}={digest}"])

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            migration_rehearsal = Path(tmp) / "migration-rehearsal.json"
            image_digest = f"sha256:{'a' * 64}"
            sbom.write_text(sbom_json(image_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(image_digest), encoding="utf-8")
            migration_rehearsal.write_text(migration_rehearsal_json(discovered), encoding="utf-8")
            write_ci_attestation(ci_attestation, sha="0" * 40)
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--migration-rehearsal",
                    str(migration_rehearsal),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key",
                    "test-policy-signing-key",
                    *base_args,
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            packet = json.loads(result.stdout)
            self.assertIn("ci_attestation", packet["missing"])
            self.assertFalse(packet["ci"]["attestation"]["valid"])
            self.assertTrue(packet["ci"]["attestation"]["hash_valid"])
            self.assertFalse(packet["ci"]["attestation"]["sha_matches_git_commit"])
            self.assertEqual(packet["ci"]["attestation"]["expected_sha"], current_git_commit())
            self.assertEqual(packet["ci"]["attestation"]["missing"], ["sha_matches_git_commit"])

    def test_release_provenance_rejects_failed_required_ci_check(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_args: list[str] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            image = item["image"]
            digest = f"sha256:{index:064x}"[-71:]
            base_args.extend(["--base-image-digest", f"{image}={digest}"])

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            migration_rehearsal = Path(tmp) / "migration-rehearsal.json"
            image_digest = f"sha256:{'a' * 64}"
            sbom.write_text(sbom_json(image_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(image_digest), encoding="utf-8")
            migration_rehearsal.write_text(migration_rehearsal_json(discovered), encoding="utf-8")
            write_ci_attestation(
                ci_attestation,
                check_records=[
                    {"name": "python-test", "status": "passed"},
                    {"name": "web", "status": "passed"},
                    {"name": "docker-build", "status": "failed"},
                ],
            )
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--migration-rehearsal",
                    str(migration_rehearsal),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key",
                    "test-policy-signing-key",
                    *base_args,
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            packet = json.loads(result.stdout)
            self.assertIn("ci_attestation", packet["missing"])
            self.assertFalse(packet["ci"]["attestation"]["valid"])
            self.assertEqual(packet["ci"]["attestation"]["passed_checks"], ["python-test", "web"])
            self.assertEqual(packet["ci"]["attestation"]["missing_checks"], ["docker-build"])
            self.assertEqual(packet["ci"]["attestation"]["missing"], ["check:docker-build"])

    def test_release_provenance_rejects_ci_attestation_for_different_image_digest(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_args: list[str] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            image = item["image"]
            digest = f"sha256:{index:064x}"[-71:]
            base_args.extend(["--base-image-digest", f"{image}={digest}"])

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            migration_rehearsal = Path(tmp) / "migration-rehearsal.json"
            release_digest = f"sha256:{'a' * 64}"
            attested_digest = f"sha256:{'b' * 64}"
            sbom.write_text(sbom_json(release_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(release_digest), encoding="utf-8")
            migration_rehearsal.write_text(migration_rehearsal_json(discovered), encoding="utf-8")
            write_ci_attestation(ci_attestation, image_digest=attested_digest)

            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--image-digest",
                    release_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--migration-rehearsal",
                    str(migration_rehearsal),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key",
                    "test-policy-signing-key",
                    *base_args,
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            packet = json.loads(result.stdout)
            self.assertIn("ci_attestation", packet["missing"])
            self.assertFalse(packet["ci"]["attestation"]["valid"])
            self.assertEqual(packet["ci"]["attestation"]["image_digest"], attested_digest)
            self.assertEqual(packet["ci"]["attestation"]["expected_image_digest"], release_digest)
            self.assertFalse(packet["ci"]["attestation"]["image_digest_matches"])
            self.assertEqual(packet["ci"]["attestation"]["missing"], ["image_digest_match"])

    def test_require_complete_passes_with_release_artifacts_and_base_digests(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_args: list[str] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            image = item["image"]
            digest = f"sha256:{index:064x}"[-71:]
            base_args.extend(["--base-image-digest", f"{image}={digest}"])

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            migration_rehearsal = Path(tmp) / "migration-rehearsal.json"
            output = Path(tmp) / "release-provenance.json"
            policy_signing_key = Path(tmp) / "policy-signing-key"
            image_digest = f"sha256:{'a' * 64}"
            sbom.write_text(sbom_json(image_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(image_digest), encoding="utf-8")
            write_ci_attestation(ci_attestation)
            migration_rehearsal.write_text(migration_rehearsal_json(discovered), encoding="utf-8")
            policy_signing_key.write_text("test-policy-signing-key\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--output",
                    str(output),
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--migration-rehearsal",
                    str(migration_rehearsal),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key-path",
                    str(policy_signing_key),
                    *base_args,
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            packet = json.loads(result.stdout)
            self.assertEqual(packet["status"], "complete")
            self.assertEqual(packet["missing"], [])
            self.assertEqual(packet["policies"]["lifecycle"]["status"], "complete")
            self.assertEqual(packet["policies"]["lifecycle"]["signature"]["key_id"], "policy-lifecycle-hmac")
            self.assertEqual(packet["connectors"]["certification"]["status"], "complete")
            self.assertEqual(packet["deployment"]["compatibility"]["status"], "complete")
            self.assertTrue(packet["ci"]["attestation"]["exists"])
            self.assertTrue(output.exists())
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["packet_sha256"], packet["packet_sha256"])

    def test_release_artifact_contract_rejects_invalid_sbom_and_blocking_vulns(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_args: list[str] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            image = item["image"]
            digest = f"sha256:{index:064x}"[-71:]
            base_args.extend(["--base-image-digest", f"{image}={digest}"])

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            image_digest = f"sha256:{'a' * 64}"
            sbom.write_text(sbom_json(image_digest, bom_format="SPDX"), encoding="utf-8")
            vuln.write_text(
                vulnerability_scan_json(image_digest, findings=[{"id": "CVE-2026-0001", "severity": "high"}]),
                encoding="utf-8",
            )
            write_ci_attestation(ci_attestation)
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key",
                    "test-policy-signing-key",
                    *base_args,
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            packet = json.loads(result.stdout)
            self.assertIn("sbom_path", packet["missing"])
            self.assertIn("vulnerability_scan_path", packet["missing"])
            self.assertFalse(packet["sbom"]["valid"])
            self.assertEqual(packet["sbom"]["missing"], ["bomFormat:CycloneDX"])
            self.assertFalse(packet["vulnerability_scan"]["valid"])
            self.assertEqual(packet["vulnerability_scan"]["blocking_finding_count"], 1)
            self.assertEqual(packet["vulnerability_scan"]["missing"], ["no_high_or_critical_findings"])

    def test_ci_attestation_supplies_image_digest_build_command_and_base_digests(self) -> None:
        discovery = subprocess.run(
            [sys.executable, SCRIPT, "--json"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        discovered = json.loads(discovery.stdout)
        base_records: list[dict[str, str]] = []
        for index, item in enumerate(discovered["base_images"], start=1):
            base_records.append({"image": item["image"], "digest": f"sha256:{index:064x}"})

        with tempfile.TemporaryDirectory() as tmp:
            sbom = Path(tmp) / "sbom.json"
            vuln = Path(tmp) / "vulnerability-scan.json"
            ci_attestation = Path(tmp) / "ci-attestation.json"
            migration_rehearsal = Path(tmp) / "migration-rehearsal.json"
            image_digest = f"sha256:{'c' * 64}"
            sbom.write_text(sbom_json(image_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(image_digest), encoding="utf-8")
            migration_rehearsal.write_text(migration_rehearsal_json(discovered), encoding="utf-8")
            write_ci_attestation(
                ci_attestation,
                image_digest=image_digest,
                build_command="docker build -t orbital-mesh:ci .",
                base_images=base_records,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--require-complete",
                    "--allow-dirty",
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--ci-attestation",
                    str(ci_attestation),
                    "--migration-rehearsal",
                    str(migration_rehearsal),
                    "--builder-identity",
                    "ci:test",
                    "--policy-signing-key",
                    "test-policy-signing-key",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            packet = json.loads(result.stdout)
            self.assertEqual(packet["image"]["digest"], image_digest)
            self.assertEqual(packet["build"]["command"], "docker build -t orbital-mesh:ci .")
            self.assertTrue(packet["checks"]["base_image_digests"])
            self.assertTrue(packet["checks"]["migration_rehearsal"])
            self.assertEqual(packet["missing"], [])

    def test_release_artifacts_must_match_release_image_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "sbom.json"
            vuln = tmp_path / "vulnerability-scan.json"
            release_digest = f"sha256:{'a' * 64}"
            wrong_digest = f"sha256:{'b' * 64}"
            sbom.write_text(sbom_json(wrong_digest), encoding="utf-8")
            vuln.write_text(vulnerability_scan_json(wrong_digest), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "--json",
                    "--allow-dirty",
                    "--image-digest",
                    release_digest,
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            packet = json.loads(result.stdout)
            self.assertFalse(packet["sbom"]["valid"])
            self.assertFalse(packet["vulnerability_scan"]["valid"])
            self.assertEqual(packet["sbom"]["missing"], ["release_image_digest_match"])
            self.assertEqual(packet["vulnerability_scan"]["missing"], ["release_image_digest_match"])


if __name__ == "__main__":
    unittest.main()
