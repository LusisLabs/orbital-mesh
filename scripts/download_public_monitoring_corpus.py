#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.monitoring_corpus import PUBLIC_MONITORING_CORPUS


DEFAULT_OUTPUT_DIR = REPO_ROOT / ".mesh-runtime-state" / "monitoring-corpus" / "raw"
DEFAULT_MANIFEST = REPO_ROOT / ".mesh-runtime-state" / "monitoring-corpus" / "raw_manifest.json"

AcquisitionKind = Literal[
    "direct_file",
    "github_archive",
    "zenodo_record",
    "zenodo_record_metadata",
    "reference_only",
    "auth_required",
]


@dataclass(frozen=True)
class PublicCorpusDownloadSpec:
    name: str
    slug: str
    acquisition_kind: AcquisitionKind
    url: str
    license_note: str
    size_note: str
    artifact_name: str | None = None


DOWNLOAD_SPECS: tuple[PublicCorpusDownloadSpec, ...] = (
    PublicCorpusDownloadSpec(
        name="Loghub",
        slug="loghub",
        acquisition_kind="github_archive",
        url="https://github.com/logpai/loghub/archive/refs/heads/master.zip",
        artifact_name="loghub-master.zip",
        license_note="Use upstream repository license and dataset notices.",
        size_note="Large GitHub archive; contains many log datasets.",
    ),
    PublicCorpusDownloadSpec(
        name="AIOps Challenge 2020",
        slug="aiops-challenge-2020",
        acquisition_kind="github_archive",
        url="https://github.com/NetManAIOps/AIOps-Challenge-2020-Data/archive/refs/heads/master.zip",
        artifact_name="aiops-challenge-2020-data-master.zip",
        license_note="Use upstream repository license and data-use terms.",
        size_note="Large benchmark archive.",
    ),
    PublicCorpusDownloadSpec(
        name="Train Ticket anomaly datasets",
        slug="train-ticket-anomaly-datasets",
        acquisition_kind="zenodo_record",
        url="https://zenodo.org/api/records/6979726",
        license_note="Use Zenodo record license and citation requirements.",
        size_note="May contain multiple large files.",
    ),
    PublicCorpusDownloadSpec(
        name="Eadro microservice datasets",
        slug="eadro-microservice-datasets",
        acquisition_kind="zenodo_record",
        url="https://zenodo.org/api/records/7615394",
        license_note="Use Zenodo record license and citation requirements.",
        size_note="May contain multiple large files.",
    ),
    PublicCorpusDownloadSpec(
        name="LO2v2 microservice logs and metrics",
        slug="lo2v2-microservice-logs-and-metrics",
        acquisition_kind="zenodo_record_metadata",
        url="https://zenodo.org/api/records/18937117",
        license_note="Use Zenodo record license and citation requirements.",
        size_note="Very large public dataset; default acquisition stores metadata only.",
    ),
    PublicCorpusDownloadSpec(
        name="OpenTelemetry Astronomy Shop demo",
        slug="opentelemetry-astronomy-shop-demo",
        acquisition_kind="github_archive",
        url="https://github.com/open-telemetry/opentelemetry-demo/archive/refs/heads/main.zip",
        artifact_name="opentelemetry-demo-main.zip",
        license_note="Use upstream repository license.",
        size_note="Demo workload archive for generating OTLP logs, metrics, and traces.",
    ),
    PublicCorpusDownloadSpec(
        name="OpenTelemetry telemetrygen",
        slug="opentelemetry-telemetrygen",
        acquisition_kind="github_archive",
        url="https://github.com/open-telemetry/opentelemetry-collector-contrib/archive/refs/heads/main.zip",
        artifact_name="opentelemetry-collector-contrib-main.zip",
        license_note="Use upstream repository license.",
        size_note="Large collector-contrib archive containing telemetrygen and related OTLP tooling.",
    ),
    PublicCorpusDownloadSpec(
        name="Google Borg cluster traces",
        slug="google-borg-cluster-traces",
        acquisition_kind="github_archive",
        url="https://github.com/google/cluster-data/archive/refs/heads/master.zip",
        artifact_name="google-cluster-data-master.zip",
        license_note="Use upstream repository license and Google trace usage terms.",
        size_note="Repository archive is not the whole trace corpus; follow upstream pointers for full trace files.",
    ),
    PublicCorpusDownloadSpec(
        name="Alibaba Cluster Trace Program",
        slug="alibaba-cluster-trace-program",
        acquisition_kind="github_archive",
        url="https://github.com/alibaba/clusterdata/archive/refs/heads/master.zip",
        artifact_name="alibaba-clusterdata-master.zip",
        license_note="Use upstream repository license and trace usage terms.",
        size_note="Large repository archive; full traces may be referenced externally.",
    ),
    PublicCorpusDownloadSpec(
        name="DeathStarBench",
        slug="deathstarbench",
        acquisition_kind="github_archive",
        url="https://github.com/delimitrou/DeathStarBench/archive/refs/heads/master.zip",
        artifact_name="deathstarbench-master.zip",
        license_note="Use upstream repository license.",
        size_note="Benchmark harness archive, not a fixed labeled corpus.",
    ),
    PublicCorpusDownloadSpec(
        name="Ethereum ETL and public BigQuery exports",
        slug="ethereum-etl-and-public-bigquery-exports",
        acquisition_kind="reference_only",
        url="https://ethereum-etl.readthedocs.io/",
        artifact_name="ethereum-etl-reference.html",
        license_note="Docs and tooling reference; public BigQuery exports require cloud-project access.",
        size_note="No single raw archive. Store reference page locally; use ethereum-etl or BigQuery for raw chain extracts.",
    ),
    PublicCorpusDownloadSpec(
        name="Elliptic Bitcoin dataset",
        slug="elliptic-bitcoin-dataset",
        acquisition_kind="auth_required",
        url="https://www.kaggle.com/datasets/ellipticco/elliptic-data-set/data",
        license_note="Kaggle authentication and dataset terms required.",
        size_note="Not downloadable anonymously by this script.",
    ),
    PublicCorpusDownloadSpec(
        name="Ethereum/Gnosis validator monitoring references",
        slug="ethereum-gnosis-validator-monitoring-references",
        acquisition_kind="reference_only",
        url="https://docs.ethstaker.org/scaled-node-operators/monitoring-at-scale/",
        artifact_name="ethstaker-monitoring-at-scale.html",
        license_note="Operational documentation reference, not anomaly-labeled raw data.",
        size_note="Small documentation page.",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", action="append", default=[], help="Source slug or exact source name. Defaults to all.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-bytes", type=int, default=0, help="Optional per-file byte ceiling. Zero means no ceiling.")
    args = parser.parse_args()

    output_dir = _resolve_path(args.output_dir)
    manifest_path = _resolve_path(args.manifest)
    selected = _selected_specs(args.source)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    catalog_names = {record.name for record in PUBLIC_MONITORING_CORPUS}
    results = [
        _acquire_spec(
            spec,
            output_dir=output_dir,
            overwrite=args.overwrite,
            timeout_seconds=args.timeout_seconds,
            max_bytes=args.max_bytes,
        )
        for spec in selected
    ]
    payload = {
        "schema_version": "mesh.public_monitoring_raw_manifest.v1",
        "generated_at": _now_iso(),
        "output_dir": str(output_dir),
        "catalog_source_count": len(catalog_names),
        "requested_source_count": len(selected),
        "downloaded_count": sum(1 for result in results if result["status"] in {"downloaded", "already_present"}),
        "skipped_count": sum(1 for result in results if result["status"].startswith("skipped")),
        "failed_count": sum(1 for result in results if result["status"] == "failed"),
        "results": results,
    }
    _write_json(manifest_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload["failed_count"]:
        raise SystemExit(1)


def _acquire_spec(
    spec: PublicCorpusDownloadSpec,
    *,
    output_dir: Path,
    overwrite: bool,
    timeout_seconds: float,
    max_bytes: int,
) -> dict[str, Any]:
    source_dir = output_dir / spec.slug
    source_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "name": spec.name,
        "slug": spec.slug,
        "acquisition_kind": spec.acquisition_kind,
        "url": spec.url,
        "license_note": spec.license_note,
        "size_note": spec.size_note,
    }
    _write_json(source_dir / "source.json", {**base, "downloaded_at": _now_iso()})
    if spec.acquisition_kind == "auth_required":
        return {**base, "status": "skipped_auth_required", "path": None}
    if spec.acquisition_kind == "zenodo_record_metadata":
        return _download_zenodo_metadata(spec, source_dir, base, overwrite, timeout_seconds)
    if spec.acquisition_kind == "zenodo_record":
        return _download_zenodo_record(spec, source_dir, base, overwrite, timeout_seconds, max_bytes)
    artifact_name = spec.artifact_name or f"{spec.slug}.raw"
    path = source_dir / artifact_name
    try:
        status = _download_url(spec.url, path, overwrite=overwrite, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    except (OSError, RuntimeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return {**base, "status": "failed", "path": str(path), "error": str(exc)}
    return {**base, **_artifact_payload(path), "status": status}


def _download_zenodo_record(
    spec: PublicCorpusDownloadSpec,
    source_dir: Path,
    base: dict[str, Any],
    overwrite: bool,
    timeout_seconds: float,
    max_bytes: int,
) -> dict[str, Any]:
    record_path = source_dir / "record.json"
    try:
        _download_url(spec.url, record_path, overwrite=overwrite, timeout_seconds=timeout_seconds, max_bytes=0)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        files = record.get("files") if isinstance(record, dict) else None
        if not isinstance(files, list):
            return {**base, "status": "failed", "path": str(record_path), "error": "Zenodo record has no files list"}
        artifacts = []
        for item in files:
            if not isinstance(item, dict):
                continue
            links = item.get("links") if isinstance(item.get("links"), dict) else {}
            file_url = links.get("self") or links.get("download")
            key = str(item.get("key") or item.get("filename") or "zenodo-file")
            if not file_url:
                continue
            file_path = source_dir / _safe_filename(key)
            status = _download_url(
                str(file_url),
                file_path,
                overwrite=overwrite,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
            artifacts.append({**_artifact_payload(file_path), "status": status, "zenodo_key": key})
    except (OSError, RuntimeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {**base, "status": "failed", "path": str(record_path), "error": str(exc)}
    return {**base, "status": "downloaded" if artifacts else "failed", "record_path": str(record_path), "artifacts": artifacts}


def _download_zenodo_metadata(
    spec: PublicCorpusDownloadSpec,
    source_dir: Path,
    base: dict[str, Any],
    overwrite: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    record_path = source_dir / "record.json"
    try:
        status = _download_url(spec.url, record_path, overwrite=overwrite, timeout_seconds=timeout_seconds, max_bytes=0)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        files = record.get("files") if isinstance(record, dict) else []
        file_count = len(files) if isinstance(files, list) else 0
        total_bytes = sum(
            int(item.get("size", 0))
            for item in files
            if isinstance(item, dict) and isinstance(item.get("size", 0), int | float)
        )
    except (OSError, RuntimeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {**base, "status": "failed", "path": str(record_path), "error": str(exc)}
    return {
        **base,
        **_artifact_payload(record_path),
        "status": status,
        "record_path": str(record_path),
        "file_count": file_count,
        "declared_total_bytes": total_bytes,
        "metadata_only": True,
    }


def _download_url(
    url: str,
    path: Path,
    *,
    overwrite: bool,
    timeout_seconds: float,
    max_bytes: int,
) -> str:
    if path.is_file() and not overwrite:
        return "already_present"
    tmp_path = path.with_suffix(path.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "mesh-monitoring-corpus-downloader/1.0"})
    bytes_seen = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response, tmp_path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            bytes_seen += len(chunk)
            if max_bytes and bytes_seen > max_bytes:
                raise RuntimeError(f"download exceeded --max-bytes={max_bytes}: {url}")
            digest.update(chunk)
            handle.write(chunk)
    tmp_path.replace(path)
    (path.with_suffix(path.suffix + ".sha256")).write_text(f"{digest.hexdigest()}  {path.name}\n", encoding="utf-8")
    return "downloaded"


def _artifact_payload(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": _sha256(path) if path.is_file() else None,
    }


def _selected_specs(selectors: list[str]) -> tuple[PublicCorpusDownloadSpec, ...]:
    if not selectors:
        return DOWNLOAD_SPECS
    normalized = {selector.strip().lower() for selector in selectors if selector.strip()}
    specs = tuple(
        spec
        for spec in DOWNLOAD_SPECS
        if spec.slug.lower() in normalized or spec.name.lower() in normalized
    )
    missing = normalized - {spec.slug.lower() for spec in specs} - {spec.name.lower() for spec in specs}
    if missing:
        raise SystemExit(f"unknown public corpus source selector(s): {', '.join(sorted(missing))}")
    return specs


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe or "downloaded-file"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
