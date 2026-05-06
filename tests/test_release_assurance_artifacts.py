from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NORMALIZER = "scripts/normalize_release_assurance_artifacts.py"
PROVENANCE = "scripts/generate_release_provenance.py"
IMAGE_ASSURANCE = "scripts/generate_release_image_assurance.py"


class ReleaseAssuranceArtifactTests(unittest.TestCase):
    def test_rehearsal_input_generator_feeds_normalizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_dir = tmp_path / "raw"
            output_dir = tmp_path / "dist"
            generated = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_release_assurance_rehearsal_inputs.py",
                    "--output-dir",
                    str(raw_dir),
                    "--component-version",
                    "test-sha",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
            generated_payload = json.loads(generated.stdout)
            self.assertEqual(generated_payload["schema_version"], "mesh.release_assurance_rehearsal_inputs.v1")

            normalized = subprocess.run(
                [
                    sys.executable,
                    NORMALIZER,
                    "--sbom-input",
                    str(raw_dir / "raw-sbom.cdx.json"),
                    "--scan-input",
                    str(raw_dir / "raw-vulnerability-scan.json"),
                    "--scanner",
                    "release-assurance-rehearsal",
                    "--output-dir",
                    str(output_dir),
                    "--require-scan",
                    "--fail-on-blocking",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(normalized.returncode, 0, normalized.stderr + normalized.stdout)
            normalized_payload = json.loads(normalized.stdout)
            self.assertEqual(normalized_payload["blocking_finding_count"], 0)
            self.assertTrue((output_dir / "sbom.cdx.json").exists())
            self.assertTrue((output_dir / "vulnerability-scan.json").exists())

    def test_release_provenance_rejects_rehearsal_artifacts_as_pilot_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_dir = tmp_path / "raw"
            output_dir = tmp_path / "dist"
            generated = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_release_assurance_rehearsal_inputs.py",
                    "--output-dir",
                    str(raw_dir),
                    "--component-version",
                    "test-sha",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
            normalized = subprocess.run(
                [
                    sys.executable,
                    NORMALIZER,
                    "--sbom-input",
                    str(raw_dir / "raw-sbom.cdx.json"),
                    "--scan-input",
                    str(raw_dir / "raw-vulnerability-scan.json"),
                    "--scanner",
                    "release-assurance-rehearsal",
                    "--output-dir",
                    str(output_dir),
                    "--require-scan",
                    "--fail-on-blocking",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(normalized.returncode, 0, normalized.stderr + normalized.stdout)

            provenance = subprocess.run(
                [
                    sys.executable,
                    PROVENANCE,
                    "--json",
                    "--allow-dirty",
                    "--sbom",
                    str(output_dir / "sbom.cdx.json"),
                    "--vulnerability-scan",
                    str(output_dir / "vulnerability-scan.json"),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(provenance.returncode, 0, provenance.stderr + provenance.stdout)
            packet = json.loads(provenance.stdout)
            self.assertFalse(packet["checks"]["sbom_path"])
            self.assertFalse(packet["checks"]["vulnerability_scan_path"])
            self.assertTrue(packet["sbom"]["rehearsal"])
            self.assertTrue(packet["vulnerability_scan"]["rehearsal"])
            self.assertEqual(packet["sbom"]["missing"], ["real_release_image_sbom"])
            self.assertEqual(packet["vulnerability_scan"]["missing"], ["real_release_image_vulnerability_scan"])

    def test_ci_workflow_uploads_real_release_assurance_artifacts(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn('SYFT_VERSION: "1.44.0"', workflow)
        self.assertIn("SYFT_DEB_SHA256: 82d374ac6179acda9d0b6b3e694ecfda54dfbd9da8e29e02dc81f92d67dc103b", workflow)
        self.assertIn('GRYPE_VERSION: "0.112.0"', workflow)
        self.assertIn("GRYPE_DEB_SHA256: 434bae8af635b6308d7a33ea842c6216dc382d4ec49fe3873f927b7805cc69e2", workflow)
        self.assertIn("sha256sum -c -", workflow)
        self.assertIn("scripts/generate_release_image_assurance.py", workflow)
        self.assertIn("release-assurance-artifacts", workflow)
        self.assertIn("dist/release-assurance/", workflow)
        self.assertIn("dist/release-assurance-raw/", workflow)
        self.assertNotIn("release-assurance-contract-rehearsal", workflow)

    def test_release_image_assurance_script_uses_real_scanner_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            syft_bin = tmp_path / "syft"
            grype_bin = tmp_path / "grype"
            raw_dir = tmp_path / "raw"
            output_dir = tmp_path / "dist"
            image_digest = f"sha256:{'b' * 64}"
            syft_bin.write_text(
                "#!/usr/bin/env python3\n"
                "print('{\"bomFormat\":\"CycloneDX\",\"components\":[]}')\n",
                encoding="utf-8",
            )
            grype_bin.write_text(
                "#!/usr/bin/env python3\n"
                "print('{\"matches\":[{\"vulnerability\":{\"id\":\"CVE-LOW\",\"severity\":\"Low\"},\"artifact\":{\"name\":\"pkg\",\"version\":\"1.0\"}}]}')\n",
                encoding="utf-8",
            )
            os.chmod(syft_bin, 0o755)
            os.chmod(grype_bin, 0o755)

            result = subprocess.run(
                [
                    sys.executable,
                    IMAGE_ASSURANCE,
                    "--image-tag",
                    "orbital-mesh:ci",
                    "--image-digest",
                    image_digest,
                    "--raw-output-dir",
                    str(raw_dir),
                    "--output-dir",
                    str(output_dir),
                    "--syft-bin",
                    str(syft_bin),
                    "--grype-bin",
                    str(grype_bin),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema_version"], "mesh.release_image_assurance.v1")
            self.assertEqual(payload["blocking_finding_count"], 0)
            self.assertTrue((raw_dir / "raw-sbom.cdx.json").exists())
            self.assertTrue((raw_dir / "raw-vulnerability-scan.grype.json").exists())
            normalized_scan = json.loads((output_dir / "vulnerability-scan.json").read_text(encoding="utf-8"))
            self.assertEqual(normalized_scan["scanner"], "grype")
            self.assertEqual(normalized_scan["image_digest"], image_digest)

            provenance = subprocess.run(
                [
                    sys.executable,
                    PROVENANCE,
                    "--json",
                    "--allow-dirty",
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(output_dir / "sbom.cdx.json"),
                    "--vulnerability-scan",
                    str(output_dir / "vulnerability-scan.json"),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(provenance.returncode, 0, provenance.stderr + provenance.stdout)
            packet = json.loads(provenance.stdout)
            self.assertTrue(packet["checks"]["sbom_path"])
            self.assertTrue(packet["checks"]["vulnerability_scan_path"])

    def test_normalizer_writes_release_provenance_compatible_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            scan = tmp_path / "raw-scan.json"
            output_dir = tmp_path / "dist"
            image_digest = f"sha256:{'a' * 64}"
            sbom.write_text('{"bomFormat":"CycloneDX","components":[]}\n', encoding="utf-8")
            scan.write_text('{"matches":[{"vulnerability":{"id":"CVE-LOW","severity":"Low"},"artifact":{"name":"pkg","version":"1.0"}}]}\n', encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    NORMALIZER,
                    "--sbom-input",
                    str(sbom),
                    "--scan-input",
                    str(scan),
                    "--scanner",
                    "grype",
                    "--output-dir",
                    str(output_dir),
                    "--image-digest",
                    image_digest,
                    "--fail-on-blocking",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "complete")
            self.assertEqual(payload["finding_count"], 1)
            self.assertEqual(payload["blocking_finding_count"], 0)
            normalized_scan = json.loads((output_dir / "vulnerability-scan.json").read_text(encoding="utf-8"))
            self.assertEqual(normalized_scan["scanner"], "grype")
            self.assertEqual(normalized_scan["image_digest"], image_digest)
            self.assertEqual(normalized_scan["findings"][0]["severity"], "low")
            normalized_sbom = json.loads((output_dir / "sbom.cdx.json").read_text(encoding="utf-8"))
            self.assertIn(
                {"name": "mesh:image_digest", "value": image_digest},
                normalized_sbom["metadata"]["properties"],
            )

            provenance = subprocess.run(
                [
                    sys.executable,
                    PROVENANCE,
                    "--json",
                    "--allow-dirty",
                    "--image-digest",
                    image_digest,
                    "--sbom",
                    str(output_dir / "sbom.cdx.json"),
                    "--vulnerability-scan",
                    str(output_dir / "vulnerability-scan.json"),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(provenance.returncode, 0, provenance.stderr + provenance.stdout)
            packet = json.loads(provenance.stdout)
            self.assertTrue(packet["sbom"]["valid"])
            self.assertTrue(packet["vulnerability_scan"]["valid"])
            self.assertTrue(packet["sbom"]["image_digest_matches"])
            self.assertTrue(packet["vulnerability_scan"]["image_digest_matches"])

    def test_normalizer_fails_on_high_npm_audit_finding_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            scan = tmp_path / "npm-audit.json"
            sbom.write_text('{"bomFormat":"CycloneDX"}\n', encoding="utf-8")
            scan.write_text(
                json.dumps(
                    {
                        "vulnerabilities": {
                            "left-pad": {
                                "name": "left-pad",
                                "severity": "high",
                                "via": [{"source": 12345, "title": "test advisory"}],
                            }
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    NORMALIZER,
                    "--sbom-input",
                    str(sbom),
                    "--scan-input",
                    str(scan),
                    "--scanner",
                    "npm-audit",
                    "--output-dir",
                    str(tmp_path / "dist"),
                    "--fail-on-blocking",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("blocking vulnerability findings present: 1", result.stderr + result.stdout)

    def test_normalizer_rejects_non_cyclonedx_sbom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            sbom.write_text('{"bomFormat":"SPDX"}\n', encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    NORMALIZER,
                    "--sbom-input",
                    str(sbom),
                    "--output-dir",
                    str(tmp_path / "dist"),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must use bomFormat CycloneDX", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
