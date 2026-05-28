from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from importlib import util
from io import BytesIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_HANDOFF_PATH = REPO_ROOT / "scripts" / "verify_release_image_handoff.py"
VERIFY_HANDOFF_SPEC = util.spec_from_file_location("verify_release_image_handoff", VERIFY_HANDOFF_PATH)
assert VERIFY_HANDOFF_SPEC is not None
verify_release_image_handoff = util.module_from_spec(VERIFY_HANDOFF_SPEC)
assert VERIFY_HANDOFF_SPEC.loader is not None
VERIFY_HANDOFF_SPEC.loader.exec_module(verify_release_image_handoff)


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
            (root / "migration-rehearsal.json").write_text("{}", encoding="utf-8")
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
                    "--migration-rehearsal",
                    "dist/migration-rehearsal.json",
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
            self.assertTrue(payload["checks"]["migration_rehearsal_present"])
            self.assertTrue(payload["checks"]["migration_rehearsal_json"])
            self.assertTrue(payload["checks"]["ci_attestation_image_digest_match"])
            self.assertTrue(payload["checks"]["release_provenance_commit_match"])

    def test_verifier_requires_manifest_bound_migration_rehearsal_artifact(self) -> None:
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

            self.assertNotEqual(verified.returncode, 0)
            payload = json.loads(verified.stdout)
            self.assertIn("migration_rehearsal_present", payload["missing"])

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

    def test_verifier_writes_runtime_env_after_loaded_image_and_complete_packet_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "release-image-handoff" / "orbital-mesh-image.tar.gz"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"image archive")
            manifest = archive.parent / "release-image-handoff.json"
            env_output = root / "release-runtime.env"
            image_digest = f"sha256:{'a' * 64}"
            git_commit = "b" * 40
            complete_packet = root / "release-provenance-complete.json"
            (root / "ci-attestation.json").write_text(
                json.dumps({"sha": git_commit, "image": {"digest": image_digest}}),
                encoding="utf-8",
            )
            (root / "release-provenance-draft.json").write_text(
                json.dumps({"git": {"commit": git_commit}, "image": {"digest": image_digest}}),
                encoding="utf-8",
            )
            (root / "migration-rehearsal.json").write_text("{}", encoding="utf-8")
            (root / "release-assurance").mkdir()
            (root / "release-assurance" / "sbom.cdx.json").write_text("{}", encoding="utf-8")
            (root / "release-assurance" / "vulnerability-scan.json").write_text("{}", encoding="utf-8")

            complete_packet.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.release_provenance.v1",
                        "status": "complete",
                        "missing": [],
                        "checks": {"release_provenance_complete": True},
                        "ci": {"attestation": {"sha_matches_git_commit": True}},
                        "git": {"commit": git_commit},
                        "image": {"digest": image_digest},
                        "packet_sha256": "c" * 64,
                    }
                ),
                encoding="utf-8",
            )

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
                    "--migration-rehearsal",
                    "dist/migration-rehearsal.json",
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

            def fake_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
                self.assertEqual(args, ["docker", "image", "inspect", "orbital-mesh:handoff"])
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps([{"Id": image_digest, "RepoDigests": []}]),
                    stderr="",
                )

            result = verify_release_image_handoff.verify_handoff(
                manifest_path=manifest,
                artifact_root=root,
                image_ref="orbital-mesh:handoff",
                complete_release_provenance=complete_packet,
                runtime_release_provenance_path="/app/.mesh-runtime-state/release-provenance.json",
                env_output=env_output,
                require_artifacts=True,
                runner=fake_runner,
            )

            self.assertEqual(result["status"], "pass", result)
            self.assertEqual(result["missing"], [])
            self.assertTrue(result["checks"]["image_ref_digest_match"])
            self.assertTrue(result["checks"]["complete_release_provenance_complete"])
            self.assertEqual(
                env_output.read_text(encoding="utf-8"),
                "\n".join(
                    [
                        "MESH_IMAGE=orbital-mesh:handoff",
                        "MESH_STACK_IMAGE=orbital-mesh:handoff",
                        "MESH_RELEASE_PROVENANCE_PATH=/app/.mesh-runtime-state/release-provenance.json",
                        f"MESH_BUILD_COMMIT={git_commit}",
                        f"MESH_BUILD_IMAGE_DIGEST={image_digest}",
                        "",
                    ]
                ),
            )

    def test_verifier_accepts_archive_config_digest_when_loaded_image_reports_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "release-image-handoff" / "orbital-mesh-image.tar.gz"
            archive.parent.mkdir(parents=True)
            manifest = archive.parent / "release-image-handoff.json"
            env_output = root / "release-runtime.env"
            image_digest = f"sha256:{'a' * 64}"
            docker_manifest_digest = f"sha256:{'d' * 64}"
            git_commit = "b" * 40
            complete_packet = root / "release-provenance-complete.json"
            _write_docker_archive(archive, image_tag="orbital-mesh:handoff", config_digest=image_digest)
            (root / "ci-attestation.json").write_text(
                json.dumps({"sha": git_commit, "image": {"digest": image_digest}}),
                encoding="utf-8",
            )
            (root / "release-provenance-draft.json").write_text(
                json.dumps({"git": {"commit": git_commit}, "image": {"digest": image_digest}}),
                encoding="utf-8",
            )
            (root / "migration-rehearsal.json").write_text("{}", encoding="utf-8")
            (root / "release-assurance").mkdir()
            (root / "release-assurance" / "sbom.cdx.json").write_text("{}", encoding="utf-8")
            (root / "release-assurance" / "vulnerability-scan.json").write_text("{}", encoding="utf-8")
            complete_packet.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.release_provenance.v1",
                        "status": "complete",
                        "missing": [],
                        "checks": {"release_provenance_complete": True},
                        "ci": {"attestation": {"sha_matches_git_commit": True}},
                        "git": {"commit": git_commit},
                        "image": {"digest": image_digest},
                    }
                ),
                encoding="utf-8",
            )

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
                    "--migration-rehearsal",
                    "dist/migration-rehearsal.json",
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

            def fake_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
                self.assertEqual(args, ["docker", "image", "inspect", "orbital-mesh:handoff"])
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps(
                        [
                            {
                                "Id": docker_manifest_digest,
                                "RepoDigests": [f"orbital-mesh@{docker_manifest_digest}"],
                            }
                        ]
                    ),
                    stderr="",
                )

            result = verify_release_image_handoff.verify_handoff(
                manifest_path=manifest,
                artifact_root=root,
                image_ref="orbital-mesh:handoff",
                complete_release_provenance=complete_packet,
                runtime_release_provenance_path="/app/.mesh-runtime-state/release-provenance.json",
                env_output=env_output,
                require_artifacts=True,
                runner=fake_runner,
            )

            self.assertEqual(result["status"], "pass", result)
            self.assertTrue(result["checks"]["image_ref_digest_match"])
            self.assertIn(image_digest, result["image_ref"]["digest_candidates"])
            self.assertEqual(result["image_ref"]["archive"]["config_digest"], image_digest)

    def test_verifier_refuses_runtime_env_without_loaded_image_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "orbital-mesh-image.tar.gz"
            archive.write_bytes(b"image archive")
            manifest = root / "handoff.json"
            env_output = root / "release-runtime.env"
            image_digest = f"sha256:{'a' * 64}"
            git_commit = "b" * 40
            complete_packet = root / "release-provenance-complete.json"

            complete_packet.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.release_provenance.v1",
                        "status": "complete",
                        "missing": [],
                        "checks": {"release_provenance_complete": True},
                        "ci": {"attestation": {"sha_matches_git_commit": True}},
                        "git": {"commit": git_commit},
                        "image": {"digest": image_digest},
                    }
                ),
                encoding="utf-8",
            )

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
                    "--output",
                    str(manifest),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)

            result = verify_release_image_handoff.verify_handoff(
                manifest_path=manifest,
                complete_release_provenance=complete_packet,
                env_output=env_output,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("env_output_image_ref", result["missing"])
            self.assertIn("env_output_artifacts_required", result["missing"])
            self.assertIn("env_output_binding_evidence", result["missing"])
            self.assertFalse(env_output.exists())

    def test_verifier_reports_invalid_docker_inspect_json_as_failed_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "orbital-mesh-image.tar.gz"
            archive.write_bytes(b"image archive")
            manifest = root / "handoff.json"
            image_digest = f"sha256:{'a' * 64}"
            git_commit = "b" * 40

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
                    "--output",
                    str(manifest),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)

            def fake_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout="{", stderr="")

            result = verify_release_image_handoff.verify_handoff(
                manifest_path=manifest,
                image_ref="orbital-mesh:handoff",
                runner=fake_runner,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("image_ref_digest_match", result["missing"])
            self.assertIn("invalid JSON", result["image_ref"]["error"])


def _write_docker_archive(path: Path, *, image_tag: str, config_digest: str) -> None:
    config_name = f"blobs/sha256/{config_digest.split(':', 1)[1]}"
    manifest_payload = json.dumps(
        [
            {
                "Config": config_name,
                "RepoTags": [image_tag],
                "Layers": [],
            }
        ]
    ).encode("utf-8")
    config_payload = b"{}"
    with tarfile.open(path, "w:gz") as archive:
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_payload)
        archive.addfile(manifest_info, BytesIO(manifest_payload))
        config_info = tarfile.TarInfo(config_name)
        config_info.size = len(config_payload)
        archive.addfile(config_info, BytesIO(config_payload))


if __name__ == "__main__":
    unittest.main()
