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


if __name__ == "__main__":
    unittest.main()
