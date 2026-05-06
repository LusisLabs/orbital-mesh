#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate release-image SBOM and vulnerability scan artifacts.")
    parser.add_argument("--image-tag", required=True, help="Built release image tag to scan.")
    parser.add_argument("--image-digest", required=True, help="sha256 digest recorded for the release image.")
    parser.add_argument("--raw-output-dir", required=True, help="Directory for raw scanner artifacts.")
    parser.add_argument("--output-dir", required=True, help="Directory for normalized release assurance artifacts.")
    parser.add_argument("--syft-bin", default="syft", help="Syft executable path.")
    parser.add_argument("--grype-bin", default="grype", help="Grype executable path.")
    args = parser.parse_args()

    _validate_digest(args.image_digest)
    syft_bin = _resolve_binary(args.syft_bin, "Syft")
    grype_bin = _resolve_binary(args.grype_bin, "Grype")

    raw_output_dir = Path(args.raw_output_dir)
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = raw_output_dir / "raw-sbom.cdx.json"
    scan_path = raw_output_dir / "raw-vulnerability-scan.grype.json"

    _run_to_file(
        [syft_bin, args.image_tag, "-o", "cyclonedx-json"],
        output_path=sbom_path,
        failure_context="Syft SBOM generation failed",
    )
    _run_to_file(
        [grype_bin, args.image_tag, "-o", "json"],
        output_path=scan_path,
        failure_context="Grype vulnerability scan failed",
    )

    normalizer = Path(__file__).resolve().with_name("normalize_release_assurance_artifacts.py")
    normalized = subprocess.run(
        [
            sys.executable,
            str(normalizer),
            "--sbom-input",
            str(sbom_path),
            "--scan-input",
            str(scan_path),
            "--scanner",
            "grype",
            "--output-dir",
            args.output_dir,
            "--image-digest",
            args.image_digest,
            "--require-scan",
            "--fail-on-blocking",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if normalized.returncode != 0:
        raise SystemExit(normalized.stderr + normalized.stdout)

    normalized_payload = json.loads(normalized.stdout)
    print(
        json.dumps(
            {
                "schema_version": "mesh.release_image_assurance.v1",
                "status": "complete",
                "generated_at": _timestamp(),
                "image": {"tag": args.image_tag, "digest": args.image_digest},
                "scanner": {"sbom": "syft", "vulnerability": "grype"},
                "raw_artifacts": {
                    "sbom": str(sbom_path),
                    "vulnerability_scan": str(scan_path),
                },
                "normalized_artifacts": {
                    "sbom": normalized_payload["sbom"],
                    "vulnerability_scan": normalized_payload["vulnerability_scan"],
                },
                "finding_count": normalized_payload["finding_count"],
                "blocking_finding_count": normalized_payload["blocking_finding_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _resolve_binary(candidate: str, label: str) -> str:
    resolved = shutil.which(candidate)
    if not resolved:
        raise SystemExit(f"{label} binary not found: {candidate}")
    return resolved


def _run_to_file(command: list[str], *, output_path: Path, failure_context: str) -> None:
    with output_path.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{failure_context}: {result.stderr.strip()}")


def _validate_digest(value: str) -> None:
    if not value.startswith("sha256:"):
        raise SystemExit("--image-digest must be sha256:<64 hex>")
    tail = value[len("sha256:") :]
    if len(tail) != 64 or any(char not in "0123456789abcdefABCDEF" for char in tail):
        raise SystemExit("--image-digest must be sha256:<64 hex>")


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
