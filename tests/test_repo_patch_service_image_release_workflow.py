from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/repo-patch-service-image-release.yml"
ROLE_DOCKERFILE_PATHS = (
    REPO_ROOT / "Dockerfile",
    REPO_ROOT / "docker/repo-patch-authority.Dockerfile",
    REPO_ROOT / "docker/repo-patch-verifier.Dockerfile",
)


class RepoPatchServiceImageReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_is_manual_release_only(self) -> None:
        workflow = self.workflow
        self.assertIn("workflow_dispatch:", workflow)
        trigger_block = workflow.split("permissions:", 1)[0]
        self.assertNotIn("\n  push:", trigger_block)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("if: github.event_name == 'workflow_dispatch'", workflow)

    def test_release_platform_preconditions_precede_build_and_authentication(self) -> None:
        workflow = self.workflow
        preflight = workflow.index("Verify release platform preconditions before build")
        build = workflow.index("Build and scan all three local role images before publication")
        authenticate = workflow.index("Authenticate to GHCR only after all scans pass")
        self.assertLess(preflight, build)
        self.assertLess(preflight, authenticate)
        for variable in (
            "REPO_PATCH_GITHUB_ATTESTATIONS_ENABLED",
            "REPO_PATCH_ACTIONS_ARTIFACT_STORAGE_READY",
        ):
            self.assertIn(f"vars.{variable}", workflow)
            self.assertIn(f'test "${variable}" = "true"', workflow)

    def test_checks_out_exact_sha_and_requires_clean_tree(self) -> None:
        workflow = self.workflow
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', workflow)
        self.assertGreaterEqual(workflow.count('test -z "$(git status --porcelain)"'), 2)
        self.assertIn("pnpm install --frozen-lockfile", workflow)
        self.assertIn("pnpm run lint", workflow)

    def test_maps_exactly_three_roles_to_exact_dockerfiles(self) -> None:
        workflow = self.workflow
        mapping = {
            "mesh_control_plane": "Dockerfile",
            "repo_patch_authority": "docker/repo-patch-authority.Dockerfile",
            "repo_patch_verifier": "docker/repo-patch-verifier.Dockerfile",
        }
        for role, dockerfile in mapping.items():
            self.assertIn(f"{role})", workflow)
            self.assertIn(f'dockerfile="{dockerfile}"', workflow)
        self.assertIn("for role in mesh_control_plane repo_patch_authority repo_patch_verifier", workflow)
        self.assertNotIn(":latest", workflow)
        self.assertIn(":sha-${GITHUB_SHA}", workflow)

    def test_all_local_scans_precede_registry_authentication_and_push(self) -> None:
        workflow = self.workflow
        scan = workflow.index("Build and scan all three local role images before publication")
        authenticate = workflow.index("Authenticate to GHCR only after all scans pass")
        publish = workflow.index("Publish immutable tags, resolve digests, and rescan published subjects")
        self.assertLess(scan, authenticate)
        self.assertLess(authenticate, publish)
        scan_block = workflow[scan:authenticate]
        self.assertIn("scripts/generate_release_image_assurance.py", scan_block)
        self.assertIn("config/release-vulnerability-exceptions.json", scan_block)
        self.assertNotIn("docker push", scan_block)

    def test_all_role_images_bind_exact_source_identity_before_scan(self) -> None:
        for path in ROLE_DOCKERFILE_PATHS:
            with self.subTest(dockerfile=path.relative_to(REPO_ROOT).as_posix()):
                dockerfile = path.read_text(encoding="utf-8")
                self.assertIn("ARG MESH_BUILD_VERSION=dev", dockerfile)
                self.assertIn("ARG MESH_BUILD_COMMIT=unknown", dockerfile)
                self.assertIn("org.opencontainers.image.source", dockerfile)
                self.assertIn("org.opencontainers.image.revision", dockerfile)
                self.assertIn("org.opencontainers.image.version", dockerfile)

        workflow = self.workflow
        scan = workflow.index("scripts/generate_release_image_assurance.py")
        for marker in (
            "image-source-binding.json",
            "mesh.image_source_binding.v1",
            "org.opencontainers.image.source",
            "org.opencontainers.image.revision",
            "org.opencontainers.image.version",
            'test "$image_source" = "https://github.com/${GITHUB_REPOSITORY}"',
            'test "$image_revision" = "$GITHUB_SHA"',
            'test "$image_version" = "sha-${GITHUB_SHA}"',
        ):
            self.assertIn(marker, workflow)
            self.assertLess(workflow.index(marker), scan)
        self.assertIn("--check image-source-binding", workflow)

    def test_permissions_and_actions_are_pinned(self) -> None:
        workflow = self.workflow
        for permission in (
            "contents: read",
            "packages: write",
            "id-token: write",
            "attestations: write",
            "artifact-metadata: write",
        ):
            self.assertIn(permission, workflow)
        uses = re.findall(r"^[ ]+uses: ([^\s]+)$", workflow, flags=re.MULTILINE)
        self.assertGreaterEqual(len(uses), 5)
        for action in uses:
            self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")
        self.assertEqual(workflow.count("actions/attest@a1948c3f048ba23858d222213b7c278aabede763"), 3)

    def test_generates_and_verifies_exact_commit_three_role_bundle(self) -> None:
        workflow = self.workflow
        self.assertIn("scripts/generate_repo_patch_service_image_bundle.py", workflow)
        self.assertIn("scripts/verify_repo_patch_service_image_bundle.py", workflow)
        self.assertIn("--git-commit \"$GITHUB_SHA\"", workflow)
        self.assertIn("--expected-git-commit \"$GITHUB_SHA\"", workflow)
        for role_flag in (
            "mesh-control-plane",
            "repo-patch-authority",
            "repo-patch-verifier",
        ):
            self.assertIn(f"--{role_flag}-image-tag", workflow)
            self.assertIn(f"--{role_flag}-image-digest", workflow)
            self.assertIn(f"--{role_flag}-sbom", workflow)
            self.assertIn(f"--{role_flag}-raw-vulnerability-scan", workflow)
            self.assertIn(f"--{role_flag}-vulnerability-scan", workflow)
            self.assertIn(f"--{role_flag}-vulnerability-evidence", workflow)
            self.assertIn(f"--{role_flag}-ci-attestation", workflow)
            self.assertIn(f"--expected-{role_flag}-image-tag", workflow)
            self.assertIn(f"--expected-{role_flag}-image-digest", workflow)
        self.assertIn("Re-resolve registry digests", workflow)
        self.assertGreaterEqual(workflow.count("docker buildx imagetools inspect"), 2)

    def test_uses_only_public_policy_inputs_and_has_no_deployment_authority(self) -> None:
        workflow = self.workflow
        lowered = workflow.lower()
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("verifier_private", lowered)
        self.assertNotIn("private-key", lowered)
        self.assertNotIn("hsai", lowered)
        self.assertNotIn("kubectl", lowered)
        self.assertNotIn("docker compose", lowered)
        self.assertNotIn("deploy", lowered)
        self.assertIn("vars.REPO_PATCH_VERIFIER_PUBLIC_KEY_PEM", workflow)
        self.assertIn("vars.REPO_PATCH_GITHUB_ATTESTATIONS_ENABLED", workflow)
        self.assertIn("vars.REPO_PATCH_ACTIONS_ARTIFACT_STORAGE_READY", workflow)
        self.assertIn("${{ github.token }}", workflow)


if __name__ == "__main__":
    unittest.main()
