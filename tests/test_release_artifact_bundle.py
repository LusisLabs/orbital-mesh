from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/verify_release_artifact_bundle.py"
RELEASE_COMMIT = "a" * 40
RELEASE_DIGEST = f"sha256:{'b' * 64}"


class ReleaseArtifactBundleTests(unittest.TestCase):
    def test_verifies_complete_downloaded_ci_artifact_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_bundle(root)

            result = _run_bundle_verifier(root, "--expected-head", RELEASE_COMMIT)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["missing"], [])
            self.assertEqual(payload["release"]["git_commit"], RELEASE_COMMIT)
            self.assertEqual(payload["release"]["image_digest"], RELEASE_DIGEST)

    def test_rejects_bundle_for_wrong_expected_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_bundle(root)

            result = _run_bundle_verifier(root, "--expected-head", "c" * 40)

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "fail")
            self.assertIn("expected_head_match", payload["missing"])

    def test_rejects_runtime_env_without_binding_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / "release-runtime.env"
            _write_bundle(root)

            result = _run_bundle_verifier(root, "--env-output", str(env_path))

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertIn("env_output_binding_evidence", payload["missing"])
            self.assertFalse(env_path.exists())

    def test_writes_runtime_env_when_external_deployer_owns_image_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / "release-runtime.env"
            _write_bundle(root)

            result = _run_bundle_verifier(root, "--env-output", str(env_path), "--allow-unverified-env-output")

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(
                env_path.read_text(encoding="utf-8").splitlines(),
                [
                    "MESH_RELEASE_PROVENANCE_PATH=/app/.mesh-runtime-state/release-provenance.json",
                    f"MESH_BUILD_COMMIT={RELEASE_COMMIT}",
                    f"MESH_BUILD_IMAGE_DIGEST={RELEASE_DIGEST}",
                ],
            )

    def test_verifies_downloaded_release_image_handoff_artifact_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_root = root / f"release-image-handoff-{RELEASE_COMMIT}"
            _write_handoff_bundle(handoff_root)

            result = _run_bundle_verifier(root, "--expected-head", RELEASE_COMMIT)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["artifact_layout"], "release-image-handoff")
            self.assertEqual(payload["artifact_bundle_root"], str(handoff_root.resolve()))
            self.assertEqual(payload["release"]["image_digest"], RELEASE_DIGEST)


def _run_bundle_verifier(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SCRIPT, "--artifact-root", str(root), "--json", *extra],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_bundle(root: Path) -> None:
    ci = {
        "schema_version": "mesh.ci_attestation.v1",
        "provider": "github-actions",
        "workflow": "CI",
        "job": "docker-build",
        "run_id": "run-1",
        "sha": RELEASE_COMMIT,
        "image": {"tag": "orbital-mesh:ci", "digest": RELEASE_DIGEST},
        "checks": [
            {"name": "python-test", "status": "passed"},
            {"name": "web", "status": "passed"},
            {"name": "docker-build", "status": "passed"},
        ],
    }
    ci["attestation_sha256"] = _payload_hash(ci)
    ci_path = root / "ci-attestation" / "ci-attestation.json"
    _write_json(ci_path, ci)

    sbom = {
        "bomFormat": "CycloneDX",
        "metadata": {"component": {"name": "orbital-mesh"}},
        "components": [],
    }
    sbom_path = root / "release-assurance-artifacts" / "release-assurance" / "sbom.cdx.json"
    _write_json(sbom_path, sbom)

    vulnerability_scan = {
        "schema_version": "mesh.normalized_vulnerability_scan.v1",
        "scanner": "grype",
        "image_digest": RELEASE_DIGEST,
        "findings": [],
    }
    scan_path = root / "release-assurance-artifacts" / "release-assurance" / "vulnerability-scan.json"
    _write_json(scan_path, vulnerability_scan)

    migration_rehearsal = {
        "schema_version": "mesh.migration_rehearsal.v1",
        "status": "pass",
        "migration_version": "005_relationship_infra_node_key",
    }
    migration_path = root / "release-provenance-draft" / "migration-rehearsal.json"
    _write_json(migration_path, migration_rehearsal)

    metadata = {
        "schema_version": "mesh.release_image_metadata.v1",
        "image": {"tag": "orbital-mesh:ci", "digest": RELEASE_DIGEST},
    }
    _write_json(root / "release-provenance-draft" / "release-image-metadata.json", metadata)

    release = {
        "schema_version": "mesh.release_provenance.v1",
        "status": "complete",
        "missing": [],
        "checks": {
            "git_commit": True,
            "image_digest": True,
            "ci_attestation": True,
            "sbom_path": True,
            "vulnerability_scan_path": True,
            "migration_rehearsal": True,
        },
        "git": {"commit": RELEASE_COMMIT},
        "image": {"tag": "orbital-mesh:ci", "digest": RELEASE_DIGEST},
        "ci": {
            "attestation": {
                "schema_version": "mesh.ci_attestation.v1",
                "provider": "github-actions",
                "workflow": "CI",
                "job": "docker-build",
                "run_id": "run-1",
                "sha": RELEASE_COMMIT,
                "expected_sha": RELEASE_COMMIT,
                "sha_matches_git_commit": True,
                "image_digest": RELEASE_DIGEST,
                "expected_image_digest": RELEASE_DIGEST,
                "image_digest_matches": True,
                "valid": True,
                "sha256": _sha256(ci_path),
            }
        },
        "sbom": {
            "exists": True,
            "valid": True,
            "path": "dist/release-assurance/sbom.cdx.json",
            "sha256": _sha256(sbom_path),
            "image_digest": RELEASE_DIGEST,
            "image_digest_matches": True,
        },
        "vulnerability_scan": {
            "exists": True,
            "valid": True,
            "path": "dist/release-assurance/vulnerability-scan.json",
            "sha256": _sha256(scan_path),
            "image_digest": RELEASE_DIGEST,
            "image_digest_matches": True,
            "blocking_finding_count": 0,
        },
        "migrations": {
            "rehearsal": {
                "exists": True,
                "valid": True,
                "status": "pass",
                "path": "dist/migration-rehearsal.json",
                "sha256": _sha256(migration_path),
            }
        },
    }
    release["packet_sha256"] = _payload_hash(release)
    _write_json(root / "release-provenance-draft" / "release-provenance-draft.json", release)


def _write_handoff_bundle(root: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ci_root = Path(tmp)
        _write_bundle(ci_root)
        mappings = {
            "ci-attestation/ci-attestation.json": "ci-attestation.json",
            "release-provenance-draft/release-provenance-draft.json": "release-provenance-draft.json",
            "release-provenance-draft/release-image-metadata.json": "release-image-metadata.json",
            "release-provenance-draft/migration-rehearsal.json": "migration-rehearsal.json",
            "release-assurance-artifacts/release-assurance/sbom.cdx.json": "release-assurance/sbom.cdx.json",
            "release-assurance-artifacts/release-assurance/vulnerability-scan.json": "release-assurance/vulnerability-scan.json",
        }
        for source, target in mappings.items():
            target_path = root / target
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes((ci_root / source).read_bytes())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
