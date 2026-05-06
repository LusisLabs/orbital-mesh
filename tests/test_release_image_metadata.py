from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.collect_release_image_metadata import (
    collect_release_image_metadata,
    discover_base_images,
)


class ReleaseImageMetadataTests(unittest.TestCase):
    def test_collect_release_image_metadata_records_image_and_base_digests(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if args[:3] == ["docker", "image", "inspect"]:
                image = args[3]
                if image == "orbital-mesh:ci":
                    payload = [{"Id": f"sha256:{'a' * 64}", "RepoDigests": []}]
                else:
                    payload = [{"Id": f"sha256:{'b' * 64}", "RepoDigests": [f"{image}@sha256:{'c' * 64}"]}]
                return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
            if args[:2] == ["docker", "pull"]:
                return subprocess.CompletedProcess(args, 0, "pulled\n", "")
            return subprocess.CompletedProcess(args, 1, "", "unexpected command")

        packet = collect_release_image_metadata(
            image_tag="orbital-mesh:ci",
            pull_base_images=True,
            runner=fake_runner,
        )

        self.assertEqual(packet["schema_version"], "mesh.release_image_metadata.v1")
        self.assertEqual(packet["image"]["digest"], f"sha256:{'a' * 64}")
        self.assertEqual(packet["image"]["digest_source"], "local_image_id")
        self.assertTrue(packet["base_images"])
        self.assertTrue(all(item["digest"] == f"sha256:{'c' * 64}" for item in packet["base_images"]))
        self.assertTrue(any(call[:2] == ["docker", "pull"] for call in calls))

    def test_discover_base_images_skips_internal_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Dockerfile").write_text(
                "\n".join(
                    [
                        "FROM python:3.12-slim-bookworm AS pybase",
                        "FROM pybase AS runtime",
                        "FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS web",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = discover_base_images(repo_root=root)

        self.assertEqual([item["image"] for item in records], ["python:3.12-slim-bookworm", "node:22-bookworm-slim"])

    def test_ci_workflow_attests_release_image_metadata_and_draft_packet(self) -> None:
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/collect_release_image_metadata.py", workflow)
        self.assertIn("dist/base-image-digest.args", workflow)
        self.assertIn("--image-digest \"$MESH_IMAGE_DIGEST\"", workflow)
        self.assertIn("\"${BASE_IMAGE_ARGS[@]}\"", workflow)
        self.assertIn("dist/release-provenance-draft.json", workflow)
        self.assertIn("release-provenance-draft", workflow)


if __name__ == "__main__":
    unittest.main()
