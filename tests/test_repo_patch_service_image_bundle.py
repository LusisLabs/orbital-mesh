from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from shared.mesh_runtime.repo_patch_service_image_bundle import (
    ROLE_DOCKERFILES,
    ROLE_ORDER,
    RepoPatchServiceImageBundleError,
    build_repo_patch_service_image_bundle,
    repo_patch_service_image_bundle_sha256,
    verify_repo_patch_service_image_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepoPatchServiceImageBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.git_commit = "a" * 40
        self.sandbox_digest = f"sha256:{'d' * 64}"
        self.verifier_key_id = "repo-patch-verifier-release-1"
        self.public_key_path = self.root / "trusted-verifier-public.pem"
        _write_ed25519_public_key(self.public_key_path)

        for role, dockerfile_path in ROLE_DOCKERFILES.items():
            path = self.root / dockerfile_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"FROM scratch\nLABEL mesh.role={role}\n", encoding="utf-8")

        self.role_inputs: dict[str, dict[str, str]] = {}
        self.artifact_paths: dict[str, dict[str, Path]] = {}
        for index, role in enumerate(ROLE_ORDER, start=1):
            digest = f"sha256:{str(index) * 64}"
            image_tag = f"registry.example.test/lusis/{role}@{digest}"
            directory = self.root / "release-artifacts" / role
            directory.mkdir(parents=True)
            sbom = directory / "sbom.cdx.json"
            scan = directory / "vulnerability-scan.json"
            ci_attestation = directory / "ci-attestation.json"
            sbom.write_text(
                json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.6",
                        "metadata": {
                            "properties": [{"name": "mesh:image_digest", "value": digest}],
                        },
                        "components": [],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            scan.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.normalized_vulnerability_scan.v1",
                        "scanner": "grype",
                        "image_digest": digest,
                        "findings": [],
                        "blocking_finding_count": 0,
                        "accepted_exception_count": 0,
                        "unaccepted_blocking_finding_count": 0,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_ci_attestation(
                ci_attestation,
                git_commit=self.git_commit,
                image_tag=image_tag,
                image_digest=digest,
                dockerfile_path=ROLE_DOCKERFILES[role],
            )
            self.role_inputs[role] = {
                "image_tag": image_tag,
                "image_digest": digest,
                "sbom_path": sbom.relative_to(self.root).as_posix(),
                "vulnerability_scan_path": scan.relative_to(self.root).as_posix(),
                "ci_attestation_path": ci_attestation.relative_to(self.root).as_posix(),
            }
            self.artifact_paths[role] = {
                "sbom": sbom,
                "scan": scan,
                "ci_attestation": ci_attestation,
            }

        self.expected_role_images = {
            role: {
                "tag": values["image_tag"],
                "digest": values["image_digest"],
            }
            for role, values in self.role_inputs.items()
        }
        self.bundle = self._build_bundle()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_builds_and_verifies_exact_three_role_bundle(self) -> None:
        self.assertEqual(self.bundle["schema_version"], "mesh.repo_patch_service_image_bundle.v1")
        self.assertEqual(self.bundle["state_slice"], "mesh.repo_patch_service_image_bundle.v1")
        self.assertEqual(tuple(self.bundle["roles"]), ROLE_ORDER)
        verifier_policy = self.bundle["roles"]["repo_patch_verifier"]["verifier_policy"]
        self.assertEqual(verifier_policy["signature_algorithm"], "ed25519")
        self.assertEqual(verifier_policy["key_id"], self.verifier_key_id)
        self.assertEqual(len(verifier_policy["public_key_sha256"]), 64)

        result = self._verify(self.bundle)

        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["missing"], [])

    def test_generator_and_verifier_cli_round_trip(self) -> None:
        output = self.root / "repo-patch-service-image-bundle.json"
        generated = subprocess.run(
            self._generator_command(output),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
        packet = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(packet["git_commit"], self.git_commit)

        verified = subprocess.run(
            self._verifier_command(output),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        result = json.loads(verified.stdout)
        self.assertEqual(result["status"], "pass", result)

    def test_rejects_role_swap_after_bundle_rehash(self) -> None:
        tampered = deepcopy(self.bundle)
        authority = tampered["roles"]["repo_patch_authority"]
        verifier = tampered["roles"]["repo_patch_verifier"]
        tampered["roles"]["repo_patch_authority"] = verifier
        tampered["roles"]["repo_patch_verifier"] = authority
        _rehash(tampered)

        result = self._verify(tampered)

        self.assertEqual(result["status"], "fail")
        self.assertIn("schema_valid", result["missing"])
        self.assertIn("roles.repo_patch_authority.role", result["missing"])
        self.assertIn("roles.repo_patch_verifier.role", result["missing"])

    def test_rejects_image_role_swap_against_external_expected_images(self) -> None:
        tampered = deepcopy(self.bundle)
        tampered["roles"]["repo_patch_authority"]["image"], tampered["roles"]["repo_patch_verifier"]["image"] = (
            tampered["roles"]["repo_patch_verifier"]["image"],
            tampered["roles"]["repo_patch_authority"]["image"],
        )
        _rehash(tampered)

        result = self._verify(tampered)

        self.assertIn("roles.repo_patch_authority.image.expected_digest", result["missing"])
        self.assertIn("roles.repo_patch_verifier.image.expected_digest", result["missing"])
        self.assertIn("roles.repo_patch_authority.ci_attestation.binding", result["missing"])

    def test_rejects_stale_artifact_digest(self) -> None:
        self.artifact_paths["mesh_control_plane"]["sbom"].write_text("{}", encoding="utf-8")

        result = self._verify(self.bundle)

        self.assertEqual(result["status"], "fail")
        self.assertIn("roles.mesh_control_plane.sbom.sha256", result["missing"])
        self.assertIn("roles.mesh_control_plane.sbom.binding", result["missing"])

    def test_rejects_missing_vulnerability_scan(self) -> None:
        self.artifact_paths["repo_patch_authority"]["scan"].unlink()

        result = self._verify(self.bundle)

        self.assertEqual(result["status"], "fail")
        self.assertIn("roles.repo_patch_authority.vulnerability_scan.exists", result["missing"])
        self.assertIn("roles.repo_patch_authority.vulnerability_scan.binding", result["missing"])

    def test_rejects_wrong_commit_even_when_bundle_hash_is_current(self) -> None:
        tampered = deepcopy(self.bundle)
        tampered["git_commit"] = "b" * 40
        _rehash(tampered)

        result = self._verify(tampered)

        self.assertIn("git_commit_expected", result["missing"])
        for role in ROLE_ORDER:
            self.assertIn(f"roles.{role}.ci_attestation.binding", result["missing"])

    def test_rejects_wrong_ci_commit_after_attestation_and_bundle_rehash(self) -> None:
        role = "mesh_control_plane"
        ci_path = self.artifact_paths[role]["ci_attestation"]
        attestation = json.loads(ci_path.read_text(encoding="utf-8"))
        attestation["sha"] = "b" * 40
        attestation["run_sha"] = "b" * 40
        attestation["attestation_sha256"] = _canonical_sha256(
            {key: value for key, value in attestation.items() if key != "attestation_sha256"}
        )
        ci_path.write_text(json.dumps(attestation, sort_keys=True), encoding="utf-8")
        tampered = deepcopy(self.bundle)
        tampered["roles"][role]["ci_attestation"]["sha256"] = _file_sha256(ci_path)
        _rehash(tampered)

        result = self._verify(tampered)

        self.assertNotIn(f"roles.{role}.ci_attestation.sha256", result["missing"])
        self.assertIn(f"roles.{role}.ci_attestation.binding", result["missing"])

    def test_rejects_wrong_signer_policy(self) -> None:
        attacker_public_key = self.root / "attacker-public.pem"
        _write_ed25519_public_key(attacker_public_key)

        result = self._verify(self.bundle, public_key_path=attacker_public_key)

        self.assertEqual(result["status"], "fail")
        self.assertIn("roles.repo_patch_verifier.verifier_policy.public_key_expected", result["missing"])

    def test_rejects_unknown_fields_after_bundle_rehash(self) -> None:
        cases = []
        top_level = deepcopy(self.bundle)
        top_level["claim"] = "release-ready"
        cases.append(top_level)
        nested = deepcopy(self.bundle)
        nested["roles"]["mesh_control_plane"]["image"]["mutable_tag"] = "latest"
        cases.append(nested)

        for packet in cases:
            with self.subTest(keys=sorted(packet)):
                _rehash(packet)
                result = self._verify(packet)
                self.assertEqual(result["status"], "fail")
                self.assertIn("schema_valid", result["missing"])
                self.assertNotIn("bundle_sha256", result["missing"])

    def test_generator_rejects_mutable_image_tag(self) -> None:
        role_inputs = deepcopy(self.role_inputs)
        role_inputs["mesh_control_plane"]["image_tag"] = "registry.example.test/lusis/mesh:latest"

        with self.assertRaisesRegex(RepoPatchServiceImageBundleError, "immutable"):
            self._build_bundle(role_inputs=role_inputs)

    def _build_bundle(
        self,
        *,
        role_inputs: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return build_repo_patch_service_image_bundle(
            artifact_root=self.root,
            git_commit=self.git_commit,
            role_inputs=role_inputs or self.role_inputs,
            verifier_sandbox_profile_digest=self.sandbox_digest,
            verifier_key_id=self.verifier_key_id,
            verifier_public_key_path=self.public_key_path,
            generated_at="2026-07-13T12:00:00Z",
        )

    def _verify(
        self,
        packet: dict[str, Any],
        *,
        expected_git_commit: str | None = None,
        public_key_path: Path | None = None,
    ) -> dict[str, Any]:
        return verify_repo_patch_service_image_bundle(
            packet,
            artifact_root=self.root,
            expected_git_commit=expected_git_commit or self.git_commit,
            expected_role_images=self.expected_role_images,
            expected_verifier_sandbox_profile_digest=self.sandbox_digest,
            expected_verifier_key_id=self.verifier_key_id,
            expected_verifier_public_key_path=public_key_path or self.public_key_path,
        )

    def _generator_command(self, output: Path) -> list[str]:
        command = [
            sys.executable,
            "scripts/generate_repo_patch_service_image_bundle.py",
            "--artifact-root",
            str(self.root),
            "--git-commit",
            self.git_commit,
            "--output",
            str(output),
        ]
        for role, flag in (
            ("mesh_control_plane", "mesh-control-plane"),
            ("repo_patch_authority", "repo-patch-authority"),
            ("repo_patch_verifier", "repo-patch-verifier"),
        ):
            values = self.role_inputs[role]
            command.extend(
                [
                    f"--{flag}-image-tag",
                    values["image_tag"],
                    f"--{flag}-image-digest",
                    values["image_digest"],
                    f"--{flag}-sbom",
                    values["sbom_path"],
                    f"--{flag}-vulnerability-scan",
                    values["vulnerability_scan_path"],
                    f"--{flag}-ci-attestation",
                    values["ci_attestation_path"],
                ]
            )
        command.extend(
            [
                "--verifier-sandbox-profile-digest",
                self.sandbox_digest,
                "--verifier-key-id",
                self.verifier_key_id,
                "--verifier-public-key",
                str(self.public_key_path),
            ]
        )
        return command

    def _verifier_command(self, bundle: Path) -> list[str]:
        command = [
            sys.executable,
            "scripts/verify_repo_patch_service_image_bundle.py",
            "--bundle",
            str(bundle),
            "--artifact-root",
            str(self.root),
            "--expected-git-commit",
            self.git_commit,
        ]
        for role, flag in (
            ("mesh_control_plane", "mesh-control-plane"),
            ("repo_patch_authority", "repo-patch-authority"),
            ("repo_patch_verifier", "repo-patch-verifier"),
        ):
            values = self.expected_role_images[role]
            command.extend(
                [
                    f"--expected-{flag}-image-tag",
                    values["tag"],
                    f"--expected-{flag}-image-digest",
                    values["digest"],
                ]
            )
        command.extend(
            [
                "--expected-verifier-sandbox-profile-digest",
                self.sandbox_digest,
                "--expected-verifier-key-id",
                self.verifier_key_id,
                "--expected-verifier-public-key",
                str(self.public_key_path),
                "--json",
            ]
        )
        return command


def _write_ed25519_public_key(path: Path) -> None:
    public_key = Ed25519PrivateKey.generate().public_key()
    path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _write_ci_attestation(
    path: Path,
    *,
    git_commit: str,
    image_tag: str,
    image_digest: str,
    dockerfile_path: str,
) -> None:
    packet: dict[str, Any] = {
        "schema_version": "mesh.ci_attestation.v1",
        "provider": "github-actions",
        "workflow": "CI",
        "job": "docker-release-assurance",
        "run_id": "12345",
        "sha": git_commit,
        "run_sha": git_commit,
        "image": {"tag": image_tag, "digest": image_digest},
        "build": {
            "command": f"docker build --file {dockerfile_path} --tag {image_tag} .",
            "base_images": [],
        },
        "checks": [{"name": "docker-build", "status": "passed"}],
    }
    packet["attestation_sha256"] = _canonical_sha256(packet)
    path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")


def _rehash(packet: dict[str, Any]) -> None:
    packet["bundle_sha256"] = repo_patch_service_image_bundle_sha256(packet)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
