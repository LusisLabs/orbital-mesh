from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/generate_release_provenance.py"


class ReleaseProvenanceTests(unittest.TestCase):
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
        self.assertIn("migrations", packet)
        self.assertIn("packet_sha256", packet)
        self.assertTrue(packet["policies"]["hashes"])
        self.assertTrue(packet["migrations"]["version"])

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
            output = Path(tmp) / "release-provenance.json"
            sbom.write_text('{"bomFormat":"CycloneDX"}\n', encoding="utf-8")
            vuln.write_text('{"scanner":"test","findings":[]}\n', encoding="utf-8")
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
                    f"sha256:{'a' * 64}",
                    "--sbom",
                    str(sbom),
                    "--vulnerability-scan",
                    str(vuln),
                    "--build-command",
                    "docker buildx build --provenance=true",
                    "--builder-identity",
                    "ci:test",
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
            self.assertTrue(output.exists())
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["packet_sha256"], packet["packet_sha256"])


if __name__ == "__main__":
    unittest.main()
