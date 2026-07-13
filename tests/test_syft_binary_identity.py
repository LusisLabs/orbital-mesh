from __future__ import annotations

import base64
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.normalize_syft_binary_identity import (
    BinaryIdentityCorrectionError,
    correct_syft_binary_identity,
    normalize_syft_binary_identity_file,
)


DENO_SHA256 = "1a2b9903943f9741c4f5f0afc1e2002e0c5c7320b8487a7f192f7695cd36c9a1"
DENO_SIZE = 96_181_352
DENO_PATHS = (
    "/opt/hermes-agent/venv/bin/deno",
    "/usr/local/bin/deno",
)


class SyftBinaryIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _source_sbom()
        self.evidence = _binary_evidence()

    def test_removes_only_exact_synthetic_artifact_and_its_relationships(self) -> None:
        corrected, proof = correct_syft_binary_identity(
            self.source,
            syft_version="1.44.0",
            binary_evidence=self.evidence,
        )

        self.assertEqual(proof["status"], "corrected")
        self.assertEqual(proof["removed_artifact_count"], 1)
        self.assertEqual(proof["removed_relationship_count"], 3)
        self.assertEqual(proof["installed_package_version"], "2.9.2")
        self.assertEqual(
            [item["id"] for item in corrected["artifacts"]],
            ["unrelated", "python-deno-hermes", "python-deno-system"],
        )
        self.assertEqual(corrected["artifacts"][0], self.source["artifacts"][0])
        self.assertEqual(corrected["artifacts"][1:], self.source["artifacts"][2:])
        self.assertFalse(
            any(
                item.get("parent") == "synthetic-deno" or item.get("child") == "synthetic-deno"
                for item in corrected["artifactRelationships"]
            )
        )

    def test_rejects_changed_synthetic_version_classifier_or_purl(self) -> None:
        cases = {
            "version": ("version", "0.76.1"),
            "purl": ("purl", "pkg:generic/deno@0.76.1"),
            "foundBy": ("foundBy", "other-cataloger"),
        }
        for label, (field, value) in cases.items():
            with self.subTest(label=label):
                source = copy.deepcopy(self.source)
                source["artifacts"][1][field] = value
                with self.assertRaises(BinaryIdentityCorrectionError):
                    correct_syft_binary_identity(
                        source,
                        syft_version="1.44.0",
                        binary_evidence=self.evidence,
                    )

        source = copy.deepcopy(self.source)
        source["artifacts"][1]["metadata"]["matches"][0]["classifier"] = "other-binary"
        with self.assertRaisesRegex(BinaryIdentityCorrectionError, "classifier"):
            correct_syft_binary_identity(
                source,
                syft_version="1.44.0",
                binary_evidence=self.evidence,
            )

    def test_rejects_missing_additional_or_changed_binary_paths(self) -> None:
        cases = []
        missing = copy.deepcopy(self.source)
        missing["artifacts"][1]["locations"].pop()
        cases.append(missing)
        additional = copy.deepcopy(self.source)
        additional["artifacts"][1]["locations"].append({"path": "/tmp/deno"})
        cases.append(additional)
        changed = copy.deepcopy(self.source)
        changed["artifacts"][1]["locations"][0]["path"] = "/usr/bin/deno"
        cases.append(changed)

        for source in cases:
            with self.subTest(locations=source["artifacts"][1]["locations"]):
                with self.assertRaisesRegex(BinaryIdentityCorrectionError, "paths"):
                    correct_syft_binary_identity(
                        source,
                        syft_version="1.44.0",
                        binary_evidence=self.evidence,
                    )

    def test_rejects_divergent_python_package_versions(self) -> None:
        source = copy.deepcopy(self.source)
        source["artifacts"][3]["version"] = "2.9.1"
        source["artifacts"][3]["purl"] = "pkg:pypi/deno@2.9.1"

        with self.assertRaisesRegex(BinaryIdentityCorrectionError, "versions must agree"):
            correct_syft_binary_identity(
                source,
                syft_version="1.44.0",
                binary_evidence=self.evidence,
            )

    def test_rejects_binary_version_hash_and_size_mismatches(self) -> None:
        cases = {
            "version": ("executed_version", "2.9.1"),
            "hash": ("sha256", "f" * 64),
            "size": ("size", DENO_SIZE - 1),
        }
        for label, (field, value) in cases.items():
            with self.subTest(label=label):
                evidence = copy.deepcopy(self.evidence)
                evidence[DENO_PATHS[0]][field] = value
                with self.assertRaises(BinaryIdentityCorrectionError):
                    correct_syft_binary_identity(
                        self.source,
                        syft_version="1.44.0",
                        binary_evidence=evidence,
                    )

    def test_rejects_multiple_synthetic_artifacts(self) -> None:
        source = copy.deepcopy(self.source)
        duplicate = copy.deepcopy(source["artifacts"][1])
        duplicate["id"] = "synthetic-deno-duplicate"
        source["artifacts"].append(duplicate)

        with self.assertRaisesRegex(BinaryIdentityCorrectionError, "exactly one"):
            correct_syft_binary_identity(
                source,
                syft_version="1.44.0",
                binary_evidence=self.evidence,
            )

    def test_rejects_known_mismatch_from_unreviewed_syft_version(self) -> None:
        with self.assertRaisesRegex(BinaryIdentityCorrectionError, "only reviewed"):
            correct_syft_binary_identity(
                self.source,
                syft_version="1.45.0",
                binary_evidence=self.evidence,
            )

    def test_noops_when_classifier_matches_installed_package(self) -> None:
        source = copy.deepcopy(self.source)
        source["artifacts"][1]["version"] = "2.9.2"
        source["artifacts"][1]["purl"] = "pkg:generic/deno@2.9.2"

        corrected, proof = correct_syft_binary_identity(
            source,
            syft_version="1.45.0",
            binary_evidence=None,
        )

        self.assertEqual(corrected, source)
        self.assertEqual(proof["status"], "not_applicable")
        self.assertEqual(proof["reason"], "classifier_identity_matches_installed_package")

    def test_file_normalizer_binds_source_derived_and_image_digests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "raw.syft.json"
            output_path = root / "scanner.syft.json"
            proof_path = root / "proof.json"
            source_path.write_text(json.dumps(self.source), encoding="utf-8")

            proof = normalize_syft_binary_identity_file(
                source_path=source_path,
                output_path=output_path,
                proof_path=proof_path,
                image_digest=f"sha256:{'a' * 64}",
                syft_version="1.44.0",
                binary_evidence=self.evidence,
            )

            self.assertEqual(proof["source_sbom_sha256"], _sha256(source_path))
            self.assertEqual(proof["scanner_sbom_sha256"], _sha256(output_path))
            self.assertEqual(proof["image_digest"], f"sha256:{'a' * 64}")
            self.assertEqual(json.loads(proof_path.read_text(encoding="utf-8")), proof)


def _source_sbom() -> dict:
    record_digest = base64.urlsafe_b64encode(bytes.fromhex(DENO_SHA256)).decode("ascii").rstrip("=")
    artifacts = [
        {"id": "unrelated", "name": "openssl", "version": "3.0", "type": "deb", "foundBy": "dpkg"},
        {
            "id": "synthetic-deno",
            "name": "deno",
            "version": "0.76.0",
            "type": "binary",
            "foundBy": "binary-classifier-cataloger",
            "purl": "pkg:generic/deno@0.76.0",
            "locations": [{"path": path} for path in DENO_PATHS],
            "metadata": {
                "matches": [
                    {"classifier": "deno-binary", "location": {"path": path}}
                    for path in DENO_PATHS
                ]
            },
        },
        _python_package(
            package_id="python-deno-hermes",
            root="/opt/hermes-agent/venv/lib/python3.13/site-packages",
            record_digest=record_digest,
        ),
        _python_package(
            package_id="python-deno-system",
            root="/usr/local/lib/python3.13/site-packages",
            record_digest=record_digest,
        ),
    ]
    return {
        "artifacts": artifacts,
        "artifactRelationships": [
            {"parent": "image", "child": "unrelated", "type": "contains"},
            {"parent": "image", "child": "synthetic-deno", "type": "contains"},
            {"parent": "synthetic-deno", "child": "file-a", "type": "evident-by"},
            {"parent": "synthetic-deno", "child": "file-b", "type": "evident-by"},
            {"parent": "image", "child": "python-deno-hermes", "type": "contains"},
            {"parent": "image", "child": "python-deno-system", "type": "contains"},
        ],
    }


def _python_package(*, package_id: str, root: str, record_digest: str) -> dict:
    return {
        "id": package_id,
        "name": "deno",
        "version": "2.9.2",
        "type": "python",
        "foundBy": "python-installed-package-cataloger",
        "purl": "pkg:pypi/deno@2.9.2",
        "metadata": {
            "sitePackagesRootPath": root,
            "files": [
                {
                    "path": "../../../bin/deno",
                    "digest": {"algorithm": "sha256", "value": record_digest},
                    "size": str(DENO_SIZE),
                }
            ],
        },
    }


def _binary_evidence() -> dict[str, dict]:
    return {
        path: {"sha256": DENO_SHA256, "size": DENO_SIZE, "executed_version": "2.9.2"}
        for path in DENO_PATHS
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
