from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class ReleaseImageHandoffTests(unittest.TestCase):
    def test_generates_manifest_for_operator_confirmed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "orbital-mesh-image.tar.gz"
            archive.write_bytes(b"image archive")
            output = Path(tmp) / "handoff.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_release_image_handoff.py",
                    "--image-tag",
                    "orbital-mesh:handoff",
                    "--image-digest",
                    f"sha256:{'a' * 64}",
                    "--git-commit",
                    "b" * 40,
                    "--image-archive",
                    str(archive),
                    "--confirmation",
                    "EXPORT_RELEASE_IMAGE",
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            packet = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(packet["schema_version"], "mesh.release_image_handoff.v1")
            self.assertEqual(packet["status"], "ready")
            self.assertEqual(packet["missing"], [])
            self.assertEqual(packet["image"]["archive_bytes"], len(b"image archive"))
            self.assertTrue(packet["checks"]["confirmation"])
            self.assertIn("handoff_sha256", packet)

    def test_verifies_downloaded_handoff_manifest_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "release-image-handoff" / "orbital-mesh-image.tar.gz"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"image archive")
            manifest = archive.parent / "release-image-handoff.json"
            image_digest = f"sha256:{'a' * 64}"
            git_commit = "b" * 40

            (root / "ci-attestation.json").write_text(
                json.dumps({"sha": git_commit, "image": {"digest": image_digest}}),
                encoding="utf-8",
            )
            (root / "release-provenance-draft.json").write_text(
                json.dumps({"git": {"commit": git_commit}, "image": {"digest": image_digest}}),
                encoding="utf-8",
            )
            (root / "release-assurance").mkdir()
            (root / "release-assurance" / "sbom.cdx.json").write_text("{}", encoding="utf-8")
            (root / "release-assurance" / "vulnerability-scan.json").write_text("{}", encoding="utf-8")

            generated = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_release_image_handoff.py",
                    "--image-tag",
                    "orbital-mesh:handoff",
                    "--image-digest",
                    image_digest,
                    "--git-commit",
                    git_commit,
                    "--image-archive",
                    str(archive),
                    "--confirmation",
                    "EXPORT_RELEASE_IMAGE",
                    "--ci-attestation",
                    "dist/ci-attestation.json",
                    "--release-provenance",
                    "dist/release-provenance-draft.json",
                    "--sbom",
                    "dist/release-assurance/sbom.cdx.json",
                    "--vulnerability-scan",
                    "dist/release-assurance/vulnerability-scan.json",
                    "--output",
                    str(manifest),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)

            verified = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_release_image_handoff.py",
                    "--manifest",
                    str(manifest),
                    "--artifact-root",
                    str(root),
                    "--require-artifacts",
                    "--json",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
            payload = json.loads(verified.stdout)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["missing"], [])
            self.assertTrue(payload["checks"]["image_archive_sha256_match"])
            self.assertTrue(payload["checks"]["ci_attestation_image_digest_match"])
            self.assertTrue(payload["checks"]["release_provenance_commit_match"])

    def test_rejects_unconfirmed_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "orbital-mesh-image.tar.gz"
            archive.write_bytes(b"image archive")
            output = Path(tmp) / "handoff.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_release_image_handoff.py",
                    "--image-tag",
                    "orbital-mesh:handoff",
                    "--image-digest",
                    f"sha256:{'a' * 64}",
                    "--git-commit",
                    "b" * 40,
                    "--image-archive",
                    str(archive),
                    "--confirmation",
                    "NO",
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("confirmation", result.stderr)
            self.assertFalse(output.exists())

    def test_verifier_rejects_tampered_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "orbital-mesh-image.tar.gz"
            archive.write_bytes(b"image archive")
            manifest = Path(tmp) / "handoff.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_release_image_handoff.py",
                    "--image-tag",
                    "orbital-mesh:handoff",
                    "--image-digest",
                    f"sha256:{'a' * 64}",
                    "--git-commit",
                    "b" * 40,
                    "--image-archive",
                    str(archive),
                    "--confirmation",
                    "EXPORT_RELEASE_IMAGE",
                    "--output",
                    str(manifest),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            archive.write_bytes(b"tampered archive")

            verified = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_release_image_handoff.py",
                    "--manifest",
                    str(manifest),
                    "--json",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(verified.returncode, 0)
            payload = json.loads(verified.stdout)
            self.assertIn("image_archive_sha256_match", payload["missing"])


if __name__ == "__main__":
    unittest.main()
