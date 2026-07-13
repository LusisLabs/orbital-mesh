#!/usr/bin/env python3
"""Apply narrow, evidence-bound corrections to known Syft binary identities."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import posixpath
import shutil
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "mesh.syft_binary_identity_correction.v1"
KNOWN_SYFT_VERSION = "1.44.0"
UPSTREAM_ISSUE = "https://github.com/anchore/syft/issues/5057"
SYNTHETIC_DENO_VERSION = "0.76.0"
EXPECTED_DENO_PATHS = (
    "/opt/hermes-agent/venv/bin/deno",
    "/usr/local/bin/deno",
)


class BinaryIdentityCorrectionError(ValueError):
    """Raised when a proposed scanner identity correction lacks exact evidence."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove only the proven Syft 1.44.0 Deno 0.76.0 classifier artifact."
    )
    parser.add_argument("--input", required=True, help="Complete raw Syft JSON input.")
    parser.add_argument("--output", required=True, help="Write the derived scanner Syft JSON here.")
    parser.add_argument("--proof", required=True, help="Write the correction proof JSON here.")
    parser.add_argument("--image-digest", required=True, help="Exact sha256 image digest.")
    parser.add_argument("--syft-version", required=True, help="Syft version that produced the input.")
    parser.add_argument(
        "--binary-evidence",
        required=True,
        help="JSON mapping exact container paths to sha256, size, and executed_version evidence.",
    )
    args = parser.parse_args()

    try:
        evidence = _load_json_object(Path(args.binary_evidence))
        proof = normalize_syft_binary_identity_file(
            source_path=Path(args.input),
            output_path=Path(args.output),
            proof_path=Path(args.proof),
            image_digest=args.image_digest,
            syft_version=args.syft_version,
            binary_evidence=evidence,
        )
    except (OSError, json.JSONDecodeError, BinaryIdentityCorrectionError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0


def normalize_syft_binary_identity_file(
    *,
    source_path: Path,
    output_path: Path,
    proof_path: Path,
    image_digest: str,
    syft_version: str,
    binary_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    _validate_digest(image_digest)
    source = _load_json_object(source_path)
    corrected, correction = correct_syft_binary_identity(
        source,
        syft_version=syft_version,
        binary_evidence=binary_evidence,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if correction["status"] == "not_applicable":
        shutil.copyfile(source_path, output_path)
    else:
        output_path.write_text(json.dumps(corrected, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    proof = {
        "schema_version": SCHEMA_VERSION,
        "status": correction["status"],
        "image_digest": image_digest,
        "syft_version": syft_version,
        "upstream_issue": UPSTREAM_ISSUE,
        "source_sbom_sha256": _file_sha256(source_path),
        "scanner_sbom_sha256": _file_sha256(output_path),
        **{key: value for key, value in correction.items() if key != "status"},
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof


def correct_syft_binary_identity(
    source: dict[str, Any],
    *,
    syft_version: str,
    binary_evidence: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifacts = source.get("artifacts")
    relationships = source.get("artifactRelationships")
    if not isinstance(artifacts, list) or not all(isinstance(item, dict) for item in artifacts):
        raise BinaryIdentityCorrectionError("Syft input artifacts must be an array of objects")
    if not isinstance(relationships, list) or not all(isinstance(item, dict) for item in relationships):
        raise BinaryIdentityCorrectionError("Syft input artifactRelationships must be an array of objects")

    all_deno_binary_artifacts = [
        item
        for item in artifacts
        if item.get("name") == "deno"
        and item.get("type") == "binary"
    ]
    deno_binary_artifacts = [
        item
        for item in all_deno_binary_artifacts
        if item.get("foundBy") == "binary-classifier-cataloger"
    ]
    python_packages = [
        item
        for item in artifacts
        if item.get("name") == "deno"
        and item.get("type") == "python"
        and item.get("foundBy") == "python-installed-package-cataloger"
        and str(item.get("purl") or "").startswith("pkg:pypi/deno@")
    ]

    if all_deno_binary_artifacts and not deno_binary_artifacts:
        raise BinaryIdentityCorrectionError("Deno binary artifact uses an unreviewed cataloger")
    if not all_deno_binary_artifacts:
        return copy.deepcopy(source), {
            "status": "not_applicable",
            "reason": "deno_binary_classifier_artifact_absent",
            "removed_artifact_count": 0,
            "removed_relationship_count": 0,
        }

    python_versions = {str(item.get("version") or "") for item in python_packages}
    if len(deno_binary_artifacts) == 1 and len(python_versions) == 1:
        classified_version = str(deno_binary_artifacts[0].get("version") or "")
        if classified_version in python_versions:
            return copy.deepcopy(source), {
                "status": "not_applicable",
                "reason": "classifier_identity_matches_installed_package",
                "removed_artifact_count": 0,
                "removed_relationship_count": 0,
            }

    if syft_version != KNOWN_SYFT_VERSION:
        raise BinaryIdentityCorrectionError(
            f"Deno classifier mismatch is only reviewed for Syft {KNOWN_SYFT_VERSION}; got {syft_version}"
        )
    if len(deno_binary_artifacts) != 1:
        raise BinaryIdentityCorrectionError("expected exactly one Deno binary classifier artifact")

    synthetic = deno_binary_artifacts[0]
    _validate_synthetic_deno_artifact(synthetic)
    package_evidence = _validate_python_deno_packages(python_packages, binary_evidence)

    synthetic_id = str(synthetic.get("id") or "")
    if not synthetic_id:
        raise BinaryIdentityCorrectionError("synthetic Deno artifact is missing id")
    corrected = copy.deepcopy(source)
    corrected["artifacts"] = [item for item in corrected["artifacts"] if item.get("id") != synthetic_id]
    corrected["artifactRelationships"] = [
        item
        for item in corrected["artifactRelationships"]
        if item.get("parent") != synthetic_id and item.get("child") != synthetic_id
    ]
    removed_artifacts = len(artifacts) - len(corrected["artifacts"])
    removed_relationships = len(relationships) - len(corrected["artifactRelationships"])
    if removed_artifacts != 1:
        raise BinaryIdentityCorrectionError("correction must remove exactly one artifact")

    before_non_target = [item for item in artifacts if item.get("id") != synthetic_id]
    if corrected["artifacts"] != before_non_target:
        raise BinaryIdentityCorrectionError("correction changed a non-target artifact")

    return corrected, {
        "status": "corrected",
        "reason": "syft_issue_5057_deno_exporter_version_misclassified_as_runtime",
        "removed_artifact_count": removed_artifacts,
        "removed_relationship_count": removed_relationships,
        "removed_artifact": {
            "id": synthetic_id,
            "name": synthetic["name"],
            "version": synthetic["version"],
            "purl": synthetic["purl"],
            "paths": list(EXPECTED_DENO_PATHS),
        },
        "installed_package_version": package_evidence["version"],
        "binary_evidence": package_evidence["binary_evidence"],
    }


def _validate_synthetic_deno_artifact(artifact: dict[str, Any]) -> None:
    expected = {
        "name": "deno",
        "version": SYNTHETIC_DENO_VERSION,
        "type": "binary",
        "foundBy": "binary-classifier-cataloger",
        "purl": f"pkg:generic/deno@{SYNTHETIC_DENO_VERSION}",
    }
    mismatches = [key for key, value in expected.items() if artifact.get(key) != value]
    if mismatches:
        raise BinaryIdentityCorrectionError(
            "synthetic Deno artifact does not match the reviewed identity: " + ", ".join(mismatches)
        )

    locations = artifact.get("locations")
    if not isinstance(locations, list):
        raise BinaryIdentityCorrectionError("synthetic Deno locations must be an array")
    paths = tuple(sorted(str(item.get("path") or "") for item in locations if isinstance(item, dict)))
    if paths != tuple(sorted(EXPECTED_DENO_PATHS)):
        raise BinaryIdentityCorrectionError("synthetic Deno paths do not match the reviewed path set")

    metadata = artifact.get("metadata")
    matches = metadata.get("matches") if isinstance(metadata, dict) else None
    if not isinstance(matches, list) or len(matches) != 2:
        raise BinaryIdentityCorrectionError("synthetic Deno classifier evidence must contain exactly two matches")
    match_paths = tuple(
        sorted(
            str((item.get("location") or {}).get("path") or "")
            for item in matches
            if isinstance(item, dict) and isinstance(item.get("location"), dict)
        )
    )
    if match_paths != tuple(sorted(EXPECTED_DENO_PATHS)):
        raise BinaryIdentityCorrectionError("Deno classifier match paths do not match the reviewed path set")
    if any(item.get("classifier") != "deno-binary" for item in matches if isinstance(item, dict)):
        raise BinaryIdentityCorrectionError("Deno classifier must be deno-binary")


def _validate_python_deno_packages(
    packages: list[dict[str, Any]], binary_evidence: dict[str, Any] | None
) -> dict[str, Any]:
    if len(packages) != 2:
        raise BinaryIdentityCorrectionError("expected exactly two installed Python Deno packages")
    versions = {str(item.get("version") or "") for item in packages}
    if len(versions) != 1 or "" in versions:
        raise BinaryIdentityCorrectionError("installed Python Deno package versions must agree")
    version = next(iter(versions))
    if not isinstance(binary_evidence, dict):
        raise BinaryIdentityCorrectionError("binary evidence is required for a Deno identity correction")
    if set(binary_evidence) != set(EXPECTED_DENO_PATHS):
        raise BinaryIdentityCorrectionError("binary evidence paths do not match the reviewed path set")

    package_by_binary_path: dict[str, dict[str, Any]] = {}
    for package in packages:
        metadata = package.get("metadata")
        if not isinstance(metadata, dict):
            raise BinaryIdentityCorrectionError("Python Deno package metadata is missing")
        root = str(metadata.get("sitePackagesRootPath") or "")
        files = metadata.get("files")
        if not root.startswith("/") or not isinstance(files, list):
            raise BinaryIdentityCorrectionError("Python Deno package file metadata is invalid")
        owned = [
            item
            for item in files
            if isinstance(item, dict)
            and posixpath.normpath(posixpath.join(root, str(item.get("path") or "")))
            in EXPECTED_DENO_PATHS
        ]
        if len(owned) != 1:
            raise BinaryIdentityCorrectionError("each Python Deno package must own exactly one reviewed binary path")
        record = owned[0]
        path = posixpath.normpath(posixpath.join(root, str(record["path"])))
        digest = record.get("digest")
        if not isinstance(digest, dict) or digest.get("algorithm") != "sha256":
            raise BinaryIdentityCorrectionError("Python RECORD must provide a sha256 digest for Deno")
        try:
            record_sha256 = base64.urlsafe_b64decode(str(digest.get("value") or "") + "==").hex()
            record_size = int(record.get("size"))
        except (ValueError, TypeError) as exc:
            raise BinaryIdentityCorrectionError("Python RECORD Deno digest or size is invalid") from exc
        package_by_binary_path[path] = {
            "record_sha256": record_sha256,
            "record_size": record_size,
            "package_id": package.get("id"),
            "package_purl": package.get("purl"),
        }

    if set(package_by_binary_path) != set(EXPECTED_DENO_PATHS):
        raise BinaryIdentityCorrectionError("Python Deno package ownership does not cover both reviewed paths")

    normalized_evidence: dict[str, dict[str, Any]] = {}
    observed_hashes: set[str] = set()
    observed_sizes: set[int] = set()
    for path in EXPECTED_DENO_PATHS:
        observed = binary_evidence[path]
        if not isinstance(observed, dict):
            raise BinaryIdentityCorrectionError(f"binary evidence must be an object for {path}")
        observed_sha256 = str(observed.get("sha256") or "")
        try:
            observed_size = int(observed.get("size"))
        except (ValueError, TypeError) as exc:
            raise BinaryIdentityCorrectionError(f"binary evidence size is invalid for {path}") from exc
        executed_version = str(observed.get("executed_version") or "")
        record = package_by_binary_path[path]
        if observed_sha256 != record["record_sha256"]:
            raise BinaryIdentityCorrectionError(f"binary sha256 does not match Python RECORD for {path}")
        if observed_size != record["record_size"]:
            raise BinaryIdentityCorrectionError(f"binary size does not match Python RECORD for {path}")
        if executed_version != version:
            raise BinaryIdentityCorrectionError(f"executed Deno version does not match installed package for {path}")
        observed_hashes.add(observed_sha256)
        observed_sizes.add(observed_size)
        normalized_evidence[path] = {
            "sha256": observed_sha256,
            "size": observed_size,
            "executed_version": executed_version,
            **record,
        }

    if len(observed_hashes) != 1 or len(observed_sizes) != 1:
        raise BinaryIdentityCorrectionError("reviewed Deno binaries must be byte-identical")
    return {"version": version, "binary_evidence": normalized_evidence}


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BinaryIdentityCorrectionError(f"JSON root must be an object: {path}")
    return payload


def _validate_digest(value: str) -> None:
    if not value.startswith("sha256:"):
        raise BinaryIdentityCorrectionError("image digest must be sha256:<64 hex>")
    tail = value.removeprefix("sha256:")
    if len(tail) != 64 or any(char not in "0123456789abcdefABCDEF" for char in tail):
        raise BinaryIdentityCorrectionError("image digest must be sha256:<64 hex>")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
