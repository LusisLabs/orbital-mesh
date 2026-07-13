#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from normalize_syft_binary_identity import (
    SYNTHETIC_DENO_VERSION,
    BinaryIdentityCorrectionError,
    normalize_syft_binary_identity_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate release-image SBOM and vulnerability scan artifacts.")
    parser.add_argument("--image-tag", required=True, help="Built release image tag to scan.")
    parser.add_argument("--image-digest", required=True, help="sha256 digest recorded for the release image.")
    parser.add_argument("--raw-output-dir", required=True, help="Directory for raw scanner artifacts.")
    parser.add_argument("--output-dir", required=True, help="Directory for normalized release assurance artifacts.")
    parser.add_argument("--syft-bin", default="syft", help="Syft executable path.")
    parser.add_argument("--grype-bin", default="grype", help="Grype executable path.")
    parser.add_argument("--docker-bin", default="docker", help="Docker executable used for file identity evidence.")
    parser.add_argument(
        "--exception-policy",
        default="",
        help="Optional Mesh-owned release vulnerability exception policy JSON.",
    )
    args = parser.parse_args()

    _validate_digest(args.image_digest)
    syft_bin = _resolve_binary(args.syft_bin, "Syft")
    grype_bin = _resolve_binary(args.grype_bin, "Grype")

    raw_output_dir = Path(args.raw_output_dir)
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    source_syft_path = raw_output_dir / "raw-sbom.syft.json"
    scanner_syft_path = raw_output_dir / "scanner-sbom.syft.json"
    correction_path = raw_output_dir / "binary-identity-corrections.json"
    sbom_path = raw_output_dir / "raw-sbom.cdx.json"
    scan_path = raw_output_dir / "raw-vulnerability-scan.grype.json"

    _run_to_file(
        [syft_bin, args.image_tag, "-o", "syft-json"],
        output_path=source_syft_path,
        failure_context="Syft raw SBOM generation failed",
    )
    syft_version = _tool_version(syft_bin, "Syft")
    source_payload = _load_json_object(source_syft_path, "Syft raw SBOM")
    binary_evidence = None
    if _has_known_deno_classifier_candidate(source_payload):
        docker_bin = _resolve_binary(args.docker_bin, "Docker")
        binary_evidence = _collect_deno_binary_evidence(docker_bin, args.image_tag)
    try:
        correction = normalize_syft_binary_identity_file(
            source_path=source_syft_path,
            output_path=scanner_syft_path,
            proof_path=correction_path,
            image_digest=args.image_digest,
            syft_version=syft_version,
            binary_evidence=binary_evidence,
        )
    except BinaryIdentityCorrectionError as exc:
        raise SystemExit(f"Syft binary identity correction failed: {exc}") from exc
    _run_command(
        [syft_bin, "convert", str(scanner_syft_path), "-o", f"cyclonedx-json={sbom_path}"],
        failure_context="Syft CycloneDX conversion failed",
    )
    _run_to_file(
        [grype_bin, f"sbom:{scanner_syft_path}", "-o", "json"],
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
            *(["--exception-policy", args.exception_policy] if args.exception_policy else []),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if normalized.returncode != 0:
        summary = _blocking_findings_summary(Path(args.output_dir) / "vulnerability-scan.json")
        raise SystemExit(normalized.stderr + normalized.stdout + summary)

    normalized_payload = json.loads(normalized.stdout)
    print(
        json.dumps(
            {
                "schema_version": "mesh.release_image_assurance.v1",
                "status": "complete",
                "generated_at": _timestamp(),
                "image": {"tag": args.image_tag, "digest": args.image_digest},
                "scanner": {
                    "sbom": "syft",
                    "sbom_version": syft_version,
                    "vulnerability": "grype",
                    "input": "derived-syft-sbom",
                },
                "raw_artifacts": {
                    "source_syft_sbom": str(source_syft_path),
                    "scanner_syft_sbom": str(scanner_syft_path),
                    "binary_identity_corrections": str(correction_path),
                    "sbom": str(sbom_path),
                    "vulnerability_scan": str(scan_path),
                },
                "binary_identity_correction": correction,
                "normalized_artifacts": {
                    "sbom": normalized_payload["sbom"],
                    "vulnerability_scan": normalized_payload["vulnerability_scan"],
                },
                "finding_count": normalized_payload["finding_count"],
                "blocking_finding_count": normalized_payload["blocking_finding_count"],
                "accepted_exception_count": normalized_payload.get("accepted_exception_count", 0),
                "unaccepted_blocking_finding_count": normalized_payload.get("unaccepted_blocking_finding_count", 0),
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


def _run_command(command: list[str], *, failure_context: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"{failure_context}: {detail}")
    return result


def _tool_version(executable: str, label: str) -> str:
    result = _run_command([executable, "version", "-o", "json"], failure_context=f"{label} version check failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} version output was not JSON") from exc
    version = str(payload.get("version") or "") if isinstance(payload, dict) else ""
    if not version:
        raise SystemExit(f"{label} version output did not include version")
    return version


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{label} was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} root must be an object")
    return payload


def _has_known_deno_classifier_candidate(payload: dict[str, Any]) -> bool:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("name") == "deno"
        and item.get("version") == SYNTHETIC_DENO_VERSION
        and item.get("type") == "binary"
        and item.get("foundBy") == "binary-classifier-cataloger"
        for item in artifacts
    )


def _collect_deno_binary_evidence(docker_bin: str, image_tag: str) -> dict[str, dict[str, Any]]:
    paths = (
        "/opt/hermes-agent/venv/bin/deno",
        "/usr/local/bin/deno",
    )
    created = _run_command(
        [docker_bin, "create", "--network", "none", image_tag],
        failure_context="Docker evidence container creation failed",
    )
    container_id = created.stdout.strip()
    if not container_id:
        raise SystemExit("Docker evidence container creation did not return a container id")
    evidence: dict[str, dict[str, Any]] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="mesh-deno-identity-") as temp_dir:
            for index, path in enumerate(paths):
                destination = Path(temp_dir) / f"deno-{index}"
                _run_command(
                    [docker_bin, "cp", f"{container_id}:{path}", str(destination)],
                    failure_context=f"Docker evidence copy failed for {path}",
                )
                version_result = _run_command(
                    [
                        docker_bin,
                        "run",
                        "--rm",
                        "--network",
                        "none",
                        "--read-only",
                        "--cap-drop=ALL",
                        "--security-opt=no-new-privileges",
                        "--user",
                        "65534:65534",
                        "--entrypoint",
                        path,
                        image_tag,
                        "--version",
                    ],
                    failure_context=f"isolated Deno version check failed for {path}",
                )
                match = re.search(r"(?m)^deno\s+([0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)", version_result.stdout)
                if not match:
                    raise SystemExit(f"isolated Deno version output was invalid for {path}")
                evidence[path] = {
                    "sha256": _file_sha256(destination),
                    "size": destination.stat().st_size,
                    "executed_version": match.group(1),
                }
    finally:
        subprocess.run([docker_bin, "rm", "-f", container_id], capture_output=True, text=True, check=False)
    return evidence


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_digest(value: str) -> None:
    if not value.startswith("sha256:"):
        raise SystemExit("--image-digest must be sha256:<64 hex>")
    tail = value[len("sha256:") :]
    if len(tail) != 64 or any(char not in "0123456789abcdefABCDEF" for char in tail):
        raise SystemExit("--image-digest must be sha256:<64 hex>")


def _blocking_findings_summary(scan_path: Path) -> str:
    if not scan_path.exists():
        return ""
    try:
        payload = json.loads(scan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return ""
    blocking: list[tuple[str, str, str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").lower()
        if severity not in {"high", "critical"}:
            continue
        if isinstance(item.get("accepted_exception"), dict):
            continue
        blocking.append(
            (
                severity,
                str(item.get("id") or "unknown"),
                str(item.get("package") or "unknown"),
                str(item.get("version") or "unknown"),
            )
        )
    if not blocking:
        return ""

    lines = ["\nblocking vulnerability findings:\n"]
    for severity, vuln_id, package, version in sorted(blocking):
        lines.append(f"- {severity}\t{vuln_id}\t{package}\t{version}\n")
    return "".join(lines)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
