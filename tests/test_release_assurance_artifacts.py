from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import release_vulnerability_evidence as vulnerability_evidence


REPO_ROOT = Path(__file__).resolve().parents[1]
NORMALIZER = "scripts/normalize_release_assurance_artifacts.py"
PROVENANCE = "scripts/generate_release_provenance.py"
IMAGE_ASSURANCE = "scripts/generate_release_image_assurance.py"


class ReleaseAssuranceArtifactTests(unittest.TestCase):
    def test_release_cli_help_does_not_depend_on_repo_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            for script in (IMAGE_ASSURANCE, NORMALIZER, PROVENANCE):
                with self.subTest(script=script):
                    result = subprocess.run(
                        [sys.executable, str(REPO_ROOT / script), "--help"],
                        cwd=tmp,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

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
        self.assertIn("if: always()", workflow)
        self.assertNotIn("release-assurance-contract-rehearsal", workflow)

    def test_release_image_assurance_script_uses_real_scanner_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            syft_bin = tmp_path / "syft"
            grype_bin = tmp_path / "grype"
            raw_dir = tmp_path / "raw"
            output_dir = tmp_path / "dist"
            image_digest = f"sha256:{'b' * 64}"
            _write_fake_syft(syft_bin)
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
            self.assertTrue((raw_dir / "raw-sbom.syft.json").exists())
            self.assertTrue((raw_dir / "scanner-sbom.syft.json").exists())
            self.assertTrue((raw_dir / "binary-identity-corrections.json").exists())
            self.assertTrue((raw_dir / "raw-sbom.cdx.json").exists())
            self.assertTrue((raw_dir / "raw-vulnerability-scan.grype.json").exists())
            self.assertTrue((raw_dir / "release-vulnerability-evidence.json").exists())
            normalized_scan = json.loads((output_dir / "vulnerability-scan.json").read_text(encoding="utf-8"))
            self.assertEqual(normalized_scan["scanner"], "grype")
            self.assertEqual(normalized_scan["image_digest"], image_digest)
            self.assertEqual(normalized_scan["verified_vex_count"], 0)

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

    def test_release_image_assurance_reports_blocking_finding_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            syft_bin = tmp_path / "syft"
            grype_bin = tmp_path / "grype"
            image_digest = f"sha256:{'c' * 64}"
            _write_fake_syft(syft_bin)
            grype_bin.write_text(
                "#!/usr/bin/env python3\n"
                "print('{\"matches\":[{\"vulnerability\":{\"id\":\"CVE-HIGH\",\"severity\":\"High\"},\"artifact\":{\"name\":\"openssl\",\"version\":\"3.0\"}}]}')\n",
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
                    str(tmp_path / "raw"),
                    "--output-dir",
                    str(tmp_path / "dist"),
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

            self.assertNotEqual(result.returncode, 0)
            output = result.stderr + result.stdout
            self.assertIn("blocking vulnerability findings present: 1", output)
            self.assertIn("blocking vulnerability findings:", output)
            self.assertIn("high\tCVE-HIGH\topenssl\t3.0", output)

    def test_normalizer_applies_mesh_release_vulnerability_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            scan = tmp_path / "raw-scan.json"
            policy = tmp_path / "release-vulnerability-exceptions.json"
            output_dir = tmp_path / "dist"
            image_digest = f"sha256:{'d' * 64}"
            sbom.write_text('{"bomFormat":"CycloneDX","components":[]}\n', encoding="utf-8")
            scan.write_text(
                '{"matches":[{"vulnerability":{"id":"CVE-HIGH","severity":"High"},'
                '"artifact":{"name":"openssl","version":"3.0"}}]}\n',
                encoding="utf-8",
            )
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.release_vulnerability_exceptions.v1",
                        "owner": "platform-security",
                        "expires_at": "2999-01-01",
                        "decision": "accepted_for_test",
                        "reason": "test exception",
                        "compensating_controls": ["test control"],
                        "exceptions": [
                            {
                                "id": "CVE-HIGH",
                                "severity": "high",
                                "package": "openssl",
                                "version": "3.0",
                            }
                        ],
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
                    "grype",
                    "--output-dir",
                    str(output_dir),
                    "--image-digest",
                    image_digest,
                    "--fail-on-blocking",
                    "--exception-policy",
                    str(policy),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["blocking_finding_count"], 1)
            self.assertEqual(payload["accepted_exception_count"], 1)
            self.assertEqual(payload["unaccepted_blocking_finding_count"], 0)
            normalized_scan = json.loads((output_dir / "vulnerability-scan.json").read_text(encoding="utf-8"))
            accepted = normalized_scan["findings"][0]["accepted_exception"]
            self.assertEqual(accepted["owner"], "platform-security")
            self.assertEqual(accepted["expires_at"], "2999-01-01")

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
            self.assertTrue(packet["checks"]["vulnerability_scan_path"])
            self.assertEqual(packet["vulnerability_scan"]["accepted_exception_count"], 1)
            self.assertEqual(packet["vulnerability_scan"]["blocking_finding_count"], 0)

    def test_normalizer_rejects_expired_release_vulnerability_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            scan = tmp_path / "raw-scan.json"
            policy = tmp_path / "release-vulnerability-exceptions.json"
            sbom.write_text('{"bomFormat":"CycloneDX","components":[]}\n', encoding="utf-8")
            scan.write_text(
                '{"matches":[{"vulnerability":{"id":"CVE-HIGH","severity":"High"},'
                '"artifact":{"name":"openssl","version":"3.0"}}]}\n',
                encoding="utf-8",
            )
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.release_vulnerability_exceptions.v1",
                        "owner": "platform-security",
                        "expires_at": "2000-01-01",
                        "decision": "accepted_for_test",
                        "reason": "test exception",
                        "compensating_controls": ["test control"],
                        "exceptions": [
                            {
                                "id": "CVE-HIGH",
                                "severity": "high",
                                "package": "openssl",
                                "version": "3.0",
                            }
                        ],
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
                    "grype",
                    "--output-dir",
                    str(tmp_path / "dist"),
                    "--fail-on-blocking",
                    "--exception-policy",
                    str(policy),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expired on 2000-01-01", result.stderr + result.stdout)

    def test_normalizer_accepts_only_digest_bound_exact_verified_vex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            scan = tmp_path / "raw-scan.json"
            evidence = tmp_path / "release-vulnerability-evidence.json"
            output_dir = tmp_path / "dist"
            image_digest = f"sha256:{'e' * 64}"
            matches = [_python_grype_match(), _perl_grype_match()]
            sbom.write_text('{"bomFormat":"CycloneDX","components":[]}\n', encoding="utf-8")
            scan.write_text(json.dumps({"matches": matches}, sort_keys=True) + "\n", encoding="utf-8")
            scan_sha256 = vulnerability_evidence.file_sha256(scan)
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": vulnerability_evidence.SCHEMA_VERSION,
                        "scanner": "grype",
                        "image_digest": image_digest,
                        "raw_scan_sha256": scan_sha256,
                        "records": [
                            _python_vex_record(matches[0], image_digest),
                            _perl_vex_record(matches[1], image_digest),
                        ],
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
                    "grype",
                    "--output-dir",
                    str(output_dir),
                    "--image-digest",
                    image_digest,
                    "--vulnerability-evidence",
                    str(evidence),
                    "--fail-on-blocking",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["blocking_finding_count"], 2)
            self.assertEqual(payload["verified_vex_count"], 2)
            self.assertEqual(payload["accepted_exception_count"], 0)
            self.assertEqual(payload["unaccepted_blocking_finding_count"], 0)
            normalized_scan = json.loads((output_dir / "vulnerability-scan.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {item["verified_vex"]["analysis_state"] for item in normalized_scan["findings"]},
                {"fixed", "not_affected"},
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
            provenance_payload = json.loads(provenance.stdout)
            self.assertTrue(provenance_payload["vulnerability_scan"]["valid"])
            self.assertEqual(provenance_payload["vulnerability_scan"]["verified_vex_count"], 2)

    def test_normalizer_rejects_tampered_verified_vex_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            scan = tmp_path / "raw-scan.json"
            evidence = tmp_path / "release-vulnerability-evidence.json"
            image_digest = f"sha256:{'f' * 64}"
            match = _python_grype_match()
            sbom.write_text('{"bomFormat":"CycloneDX","components":[]}\n', encoding="utf-8")
            scan.write_text(json.dumps({"matches": [match]}, sort_keys=True) + "\n", encoding="utf-8")
            record = _python_vex_record(match, image_digest)
            record["evidence"]["installed_sha256"] = "0" * 64
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": vulnerability_evidence.SCHEMA_VERSION,
                        "scanner": "grype",
                        "image_digest": image_digest,
                        "raw_scan_sha256": vulnerability_evidence.file_sha256(scan),
                        "records": [record],
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
                    "--output-dir",
                    str(tmp_path / "dist"),
                    "--image-digest",
                    image_digest,
                    "--vulnerability-evidence",
                    str(evidence),
                    "--fail-on-blocking",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid installed_sha256", result.stderr + result.stdout)

    def test_normalizer_rejects_vex_when_scanner_match_contract_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sbom = tmp_path / "raw-sbom.json"
            scan = tmp_path / "raw-scan.json"
            evidence = tmp_path / "release-vulnerability-evidence.json"
            image_digest = f"sha256:{'1' * 64}"
            match = _python_grype_match()
            match["matchDetails"][0]["fix"]["suggestedVersion"] = "3.14.0"
            sbom.write_text('{"bomFormat":"CycloneDX","components":[]}\n', encoding="utf-8")
            scan.write_text(json.dumps({"matches": [match]}, sort_keys=True) + "\n", encoding="utf-8")
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": vulnerability_evidence.SCHEMA_VERSION,
                        "scanner": "grype",
                        "image_digest": image_digest,
                        "raw_scan_sha256": vulnerability_evidence.file_sha256(scan),
                        "records": [_python_vex_record(match, image_digest)],
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
                    "--output-dir",
                    str(tmp_path / "dist"),
                    "--image-digest",
                    image_digest,
                    "--vulnerability-evidence",
                    str(evidence),
                    "--fail-on-blocking",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("profile mismatch", result.stderr + result.stdout)

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


def _write_fake_syft(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] == 'version':\n"
        "    print(json.dumps({'version': '1.44.0'}))\n"
        "elif args and args[0] == 'convert':\n"
        "    output = args[args.index('-o') + 1]\n"
        "    destination = output.split('=', 1)[1]\n"
        "    Path(destination).write_text(json.dumps({'bomFormat': 'CycloneDX', 'components': []}) + '\\n', encoding='utf-8')\n"
        "else:\n"
        "    print(json.dumps({'artifacts': [], 'artifactRelationships': []}))\n",
        encoding="utf-8",
    )


def _python_grype_match() -> dict[str, object]:
    version = vulnerability_evidence.PYTHON_VERSION
    vulnerability_id = vulnerability_evidence.PYTHON_VULNERABILITY_ID
    return {
        "vulnerability": {
            "id": vulnerability_id,
            "namespace": "nvd:cpe",
            "severity": "High",
            "urls": [vulnerability_evidence.PYTHON_BACKPORT_URL],
        },
        "artifact": {
            "name": "python",
            "version": version,
            "type": "binary",
            "purl": f"pkg:generic/python@{version}",
        },
        "matchDetails": [
            {
                "type": "cpe-match",
                "matcher": "stock-matcher",
                "searchedBy": {
                    "namespace": "nvd:cpe",
                    "cpes": [f"cpe:2.3:a:python:python:{version}:*:*:*:*:*:*:*"],
                    "package": {"name": "python", "version": version},
                },
                "found": {
                    "vulnerabilityID": vulnerability_id,
                    "versionConstraint": "< 3.15.0 (unknown)",
                },
                "fix": {"suggestedVersion": "3.15.0"},
            }
        ],
    }


def _perl_grype_match() -> dict[str, object]:
    return {
        "vulnerability": {
            "id": vulnerability_evidence.PERL_VULNERABILITY_ID,
            "namespace": "debian:distro:debian:13",
            "severity": "High",
        },
        "artifact": {
            "name": vulnerability_evidence.PERL_PACKAGE,
            "version": vulnerability_evidence.PERL_VERSION,
            "type": "deb",
            "purl": (
                "pkg:deb/debian/perl-base@5.40.1-6?arch=arm64&distro=debian-13&upstream=perl"
            ),
            "upstreams": [{"name": "perl"}],
        },
        "matchDetails": [
            {
                "type": "exact-indirect-match",
                "matcher": "dpkg-matcher",
                "searchedBy": {
                    "distro": {"type": "debian", "version": "13"},
                    "package": {"name": "perl", "version": vulnerability_evidence.PERL_VERSION},
                    "namespace": "debian:distro:debian:13",
                },
                "found": {
                    "vulnerabilityID": vulnerability_evidence.PERL_VULNERABILITY_ID,
                    "versionConstraint": "none (unknown)",
                },
            }
        ],
    }


def _python_vex_record(match: dict[str, object], image_digest: str) -> dict[str, object]:
    return {
        "profile": vulnerability_evidence.PYTHON_PROFILE,
        "vulnerability_id": vulnerability_evidence.PYTHON_VULNERABILITY_ID,
        "package": "python",
        "version": vulnerability_evidence.PYTHON_VERSION,
        "analysis_state": "fixed",
        "justification": "code_fixed",
        "image_digest": image_digest,
        "raw_match_sha256": vulnerability_evidence.grype_match_sha256(match),
        "evidence": {
            "runtime_version": vulnerability_evidence.PYTHON_VERSION,
            "installed_path": vulnerability_evidence.PYTHON_PARSER_PATH,
            "installed_sha256": vulnerability_evidence.PYTHON_PARSER_SHA256,
            "source_commit": vulnerability_evidence.PYTHON_BACKPORT_COMMIT,
            "source_url": vulnerability_evidence.PYTHON_BACKPORT_URL,
            "regression_status": "pass",
            "regression_cases": vulnerability_evidence.PYTHON_REGRESSION_CASES,
            "regression_iterations": vulnerability_evidence.PYTHON_REGRESSION_ITERATIONS,
            "regression_chunk_size": vulnerability_evidence.PYTHON_REGRESSION_CHUNK_SIZE,
            "execution_profile": vulnerability_evidence.ISOLATED_EXECUTION_PROFILE,
        },
    }


def _perl_vex_record(match: dict[str, object], image_digest: str) -> dict[str, object]:
    return {
        "profile": vulnerability_evidence.PERL_PROFILE,
        "vulnerability_id": vulnerability_evidence.PERL_VULNERABILITY_ID,
        "package": vulnerability_evidence.PERL_PACKAGE,
        "version": vulnerability_evidence.PERL_VERSION,
        "analysis_state": "not_affected",
        "justification": "vulnerable_code_not_present",
        "image_digest": image_digest,
        "raw_match_sha256": vulnerability_evidence.grype_match_sha256(match),
        "evidence": {
            "distro": "debian-13",
            "package": vulnerability_evidence.PERL_PACKAGE,
            "package_version": vulnerability_evidence.PERL_VERSION,
            "package_status": f"install ok installed\t{vulnerability_evidence.PERL_VERSION}",
            "absent_packages": ["perl-modules-5.40", "libhttp-tiny-perl"],
            "http_tiny_paths": [],
            "http_tiny_import_status": "absent",
            "perl_base_file_manifest_contains_http_tiny": False,
            "execution_profile": vulnerability_evidence.ISOLATED_EXECUTION_PROFILE,
        },
    }


if __name__ == "__main__":
    unittest.main()
