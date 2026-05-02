"""Clean public monitoring corpus manifests into runtime-safe indexes."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_clean_public_corpus_index(
    *,
    raw_manifest_path: Path,
    public_fixture_path: Path,
    output_dir: Path,
    zip_sample_limit: int = 50,
) -> dict[str, Any]:
    """Write cleaned public-corpus JSONL and a manifest for runtime projection."""

    raw_manifest = _read_json(raw_manifest_path)
    public_fixture = _read_json(public_fixture_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = public_fixture.get("sources") if isinstance(public_fixture, dict) else []
    results = raw_manifest.get("results") if isinstance(raw_manifest, dict) else []
    by_name = {str(item.get("name")): item for item in results if isinstance(item, dict)}

    records = [
        _clean_record(source, by_name.get(str(source.get("name")), {}), zip_sample_limit=zip_sample_limit)
        for source in sources
        if isinstance(source, dict)
    ]
    jsonl_path = output_dir / "public_sources.clean.jsonl"
    jsonl_path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")
    report = {
        "schema_version": "mesh.public_monitoring_clean_manifest.v1",
        "generated_at": _now_iso(),
        "raw_manifest_path": str(raw_manifest_path),
        "public_fixture_path": str(public_fixture_path),
        "jsonl_path": str(jsonl_path),
        "record_count": len(records),
        "source_counts": _counts(record["source_kind"] for record in records),
        "acquisition_status_counts": _counts(record["acquisition_status"] for record in records),
        "telemetry_plane_counts": _counts(
            plane for record in records for plane in record.get("telemetry_planes", ())
        ),
        "records": [
            {
                "source_name": record["source_name"],
                "slug": record["slug"],
                "acquisition_status": record["acquisition_status"],
                "artifact_count": len(record["artifacts"]),
                "clean_path": str(jsonl_path),
            }
            for record in records
        ],
    }
    manifest_path = output_dir / "clean_manifest.json"
    _write_json(manifest_path, report)
    return report


def _clean_record(source: dict[str, Any], acquisition: dict[str, Any], *, zip_sample_limit: int) -> dict[str, Any]:
    name = str(source.get("name") or "unknown")
    slug = _slug(name)
    artifacts = _clean_artifacts(acquisition, zip_sample_limit=zip_sample_limit)
    telemetry_planes = tuple(str(item) for item in source.get("telemetry_planes", ()) or ())
    mesh_use = tuple(str(item) for item in source.get("mesh_use", ()) or ())
    labels = tuple(str(item) for item in source.get("labels", ()) or ())
    return {
        "schema_version": "mesh.public_monitoring_clean_record.v1",
        "source_name": name,
        "slug": slug,
        "source_kind": source.get("source_kind"),
        "domains": tuple(str(item) for item in source.get("domains", ()) or ()),
        "environments": tuple(str(item) for item in source.get("environments", ()) or ()),
        "telemetry_planes": telemetry_planes,
        "mesh_use": mesh_use,
        "labels": labels,
        "url": source.get("url"),
        "limitation": source.get("limitation"),
        "acquisition_kind": acquisition.get("acquisition_kind"),
        "acquisition_status": acquisition.get("status", "not_acquired"),
        "license_note": acquisition.get("license_note"),
        "size_note": acquisition.get("size_note"),
        "metadata_only": bool(acquisition.get("metadata_only")),
        "declared_total_bytes": acquisition.get("declared_total_bytes"),
        "artifacts": artifacts,
        "agentic_flow": {
            "memory_tier": "semantic",
            "reasoning_bank_role": "public_bootstrap_advisory",
            "retrieval_scope": "shared",
            "allowed_uses": _allowed_uses(telemetry_planes, mesh_use, labels),
            "disallowed_uses": (
                "autonomous_action_promotion",
                "breakthrough_threshold_evidence",
                "procedural_memory_without_internal_corroboration",
            ),
            "promotion_rule": "requires_internal_corpus_corroboration",
        },
    }


def _clean_artifacts(acquisition: dict[str, Any], *, zip_sample_limit: int) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if isinstance(acquisition.get("path"), str):
        artifacts.append(_artifact_record(Path(acquisition["path"]), acquisition, zip_sample_limit=zip_sample_limit))
    if isinstance(acquisition.get("record_path"), str) and acquisition.get("record_path") != acquisition.get("path"):
        artifacts.append(_artifact_record(Path(acquisition["record_path"]), acquisition, zip_sample_limit=zip_sample_limit))
    raw_artifacts = acquisition.get("artifacts")
    if isinstance(raw_artifacts, list):
        for artifact in raw_artifacts:
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                artifacts.append(_artifact_record(Path(artifact["path"]), artifact, zip_sample_limit=zip_sample_limit))
    return _dedupe_artifacts(artifacts)


def _artifact_record(path: Path, source: dict[str, Any], *, zip_sample_limit: int) -> dict[str, Any]:
    exists = path.is_file()
    record: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
        "bytes": path.stat().st_size if exists else source.get("bytes", 0),
        "sha256": source.get("sha256"),
        "kind": _artifact_kind(path),
    }
    if exists and path.suffix.lower() == ".zip":
        record.update(_zip_summary(path, limit=zip_sample_limit))
    if exists and path.name == "record.json":
        record.update(_zenodo_record_summary(path))
    return record


def _zip_summary(path: Path, *, limit: int) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return {"zip_valid": False, "zip_entry_count": 0, "zip_sample": ()}
    return {
        "zip_valid": True,
        "zip_entry_count": len(names),
        "zip_sample": tuple(names[:limit]),
    }


def _zenodo_record_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"zenodo_file_count": 0, "zenodo_declared_bytes": 0}
    files = payload.get("files") if isinstance(payload, dict) else []
    if not isinstance(files, list):
        return {"zenodo_file_count": 0, "zenodo_declared_bytes": 0}
    return {
        "zenodo_file_count": len(files),
        "zenodo_declared_bytes": sum(
            int(item.get("size", 0))
            for item in files
            if isinstance(item, dict) and isinstance(item.get("size", 0), int | float)
        ),
    }


def _allowed_uses(telemetry_planes: tuple[str, ...], mesh_use: tuple[str, ...], labels: tuple[str, ...]) -> tuple[str, ...]:
    uses = {"retrieval_grounding", "parser_regression"}
    if "traces" in telemetry_planes or "root_cause" in mesh_use:
        uses.add("root_cause_benchmark")
    if "metrics" in telemetry_planes:
        uses.add("metric_anomaly_regression")
    if "logs" in telemetry_planes:
        uses.add("log_parser_regression")
    if "opentelemetry" in labels or "otlp" in labels:
        uses.add("otlp_pipeline_regression")
    return tuple(sorted(uses))


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return "archive_zip"
    if suffix == ".json":
        return "metadata_json"
    if suffix in {".html", ".htm"}:
        return "reference_html"
    return "raw_file"


def _dedupe_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        by_path[str(artifact["path"])] = artifact
    return list(by_path.values())


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
