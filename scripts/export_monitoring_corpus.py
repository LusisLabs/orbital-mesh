#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict
from typing import Any
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase
from shared.mesh_runtime.incident_corpus import write_session_corpus
from shared.mesh_runtime.monitoring_corpus import PUBLIC_MONITORING_CORPUS, build_public_monitoring_corpus_rows


DEFAULT_RETH_LOOP_DIR = REPO_ROOT / ".mesh-runtime-state" / "reth-kurtosis-loop"
DEFAULT_PUBLIC_FIXTURE = REPO_ROOT / "fixtures" / "monitoring_corpus" / "public_sources.json"
DEFAULT_DATABASE = REPO_ROOT / ".mesh-runtime-state" / "corpus" / "incident_corpus.sqlite"
DEFAULT_RAW_MANIFEST = REPO_ROOT / ".mesh-runtime-state" / "monitoring-corpus" / "raw_manifest.json"
DEFAULT_CLEAN_MANIFEST = REPO_ROOT / ".mesh-runtime-state" / "monitoring-corpus" / "clean" / "clean_manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reth-loop-dir", type=Path, default=DEFAULT_RETH_LOOP_DIR)
    parser.add_argument("--session", action="append", default=[], help="Specific session directory name or path to export.")
    parser.add_argument("--public-fixture", type=Path, default=DEFAULT_PUBLIC_FIXTURE)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--raw-manifest", type=Path, default=DEFAULT_RAW_MANIFEST)
    parser.add_argument("--clean-manifest", type=Path, default=DEFAULT_CLEAN_MANIFEST)
    parser.add_argument(
        "--skip-public-bootstrap",
        action="store_true",
        help="Write the public-source fixture but do not import public bootstrap rows into the corpus database.",
    )
    args = parser.parse_args()

    public_fixture = _resolve_path(args.public_fixture)
    public_fixture.parent.mkdir(parents=True, exist_ok=True)
    public_payload = {
        "schema_version": "mesh.public_monitoring_sources.v1",
        "policy": "public datasets are offline fixtures for parser, anomaly, and regression evaluation only",
        "sources": [asdict(record) for record in PUBLIC_MONITORING_CORPUS],
    }
    _write_json(public_fixture, public_payload)
    public_rows = _attach_clean_manifest(
        _attach_raw_manifest(build_public_monitoring_corpus_rows(), _resolve_path(args.raw_manifest)),
        _resolve_path(args.clean_manifest),
    )

    session_dirs = _session_dirs(_resolve_path(args.reth_loop_dir), args.session)
    database = IncidentCorpusDatabase(_resolve_path(args.database))
    exports = []
    jsonl_paths = []
    for session_dir in session_dirs:
        result = write_session_corpus(session_dir)
        jsonl_paths.append(result.jsonl_path)
        exports.append(
            {
                "session_dir": str(session_dir),
                "row_count": result.row_count,
                "jsonl_path": str(result.jsonl_path),
                "report_path": str(result.report_path),
                "promotion_candidate_count": result.promotion_candidate_count,
            }
        )
    imported = database.import_jsonl_files(jsonl_paths)
    public_imported = 0 if args.skip_public_bootstrap else database.import_rows(public_rows)

    print(
        json.dumps(
            {
                "database": database.summary(),
                "database_imported_rows": imported,
                "public_bootstrap_imported_rows": public_imported,
                "public_fixture": str(public_fixture),
                "session_exports": exports,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _session_dirs(loop_dir: Path, selectors: list[str]) -> tuple[Path, ...]:
    if selectors:
        resolved = []
        for selector in selectors:
            path = Path(selector)
            if not path.is_absolute():
                path = loop_dir / selector
            if path.is_dir():
                resolved.append(path)
        return tuple(sorted(resolved))
    if not loop_dir.is_dir():
        return ()
    return tuple(sorted(path for path in loop_dir.iterdir() if path.is_dir() and path.name.startswith("session_")))


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _attach_raw_manifest(rows: list[dict[str, Any]], manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.is_file():
        return rows
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return rows
    results = manifest.get("results") if isinstance(manifest, dict) else None
    if not isinstance(results, list):
        return rows
    by_name = {str(result.get("name")): result for result in results if isinstance(result, dict)}
    enriched = copy.deepcopy(rows)
    for row in enriched:
        labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        source_name = str(labels.get("source_name") or "")
        result = by_name.get(source_name)
        if not result:
            continue
        artifact_paths = _raw_artifact_paths(result)
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        source["raw_manifest_path"] = str(manifest_path)
        source["raw_acquisition_status"] = result.get("status")
        source["raw_artifact_paths"] = tuple(artifact_paths)
        row["source"] = source
        labels["raw_artifact_count"] = len(artifact_paths)
        row["labels"] = labels
        envelope = row.get("evidence_envelope") if isinstance(row.get("evidence_envelope"), dict) else {}
        topology = envelope.get("topology_context") if isinstance(envelope.get("topology_context"), dict) else {}
        topology["raw_manifest_path"] = str(manifest_path)
        topology["raw_acquisition_status"] = result.get("status")
        topology["raw_artifact_paths"] = tuple(artifact_paths)
        envelope["topology_context"] = topology
        row["evidence_envelope"] = envelope
        audit = row.get("audit") if isinstance(row.get("audit"), dict) else {}
        existing = list(audit.get("artifact_files", ()) or ())
        audit["artifact_files"] = tuple(dict.fromkeys(existing + _relative_artifact_refs(artifact_paths, manifest_path)))
        row["audit"] = audit
    return enriched


def _attach_clean_manifest(rows: list[dict[str, Any]], manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.is_file():
        return rows
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return rows
    records = manifest.get("records") if isinstance(manifest, dict) else None
    if not isinstance(records, list):
        return rows
    by_name = {str(record.get("source_name")): record for record in records if isinstance(record, dict)}
    enriched = copy.deepcopy(rows)
    for row in enriched:
        labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        source_name = str(labels.get("source_name") or "")
        record = by_name.get(source_name)
        if not record:
            continue
        clean_paths = [str(manifest_path)]
        jsonl_path = manifest.get("jsonl_path")
        if isinstance(jsonl_path, str):
            clean_paths.append(jsonl_path)
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        source["clean_manifest_path"] = str(manifest_path)
        source["clean_artifact_paths"] = tuple(dict.fromkeys(clean_paths))
        row["source"] = source
        labels["clean_artifact_count"] = len(source["clean_artifact_paths"])
        row["labels"] = labels
        envelope = row.get("evidence_envelope") if isinstance(row.get("evidence_envelope"), dict) else {}
        topology = envelope.get("topology_context") if isinstance(envelope.get("topology_context"), dict) else {}
        topology["clean_manifest_path"] = str(manifest_path)
        topology["clean_artifact_paths"] = source["clean_artifact_paths"]
        envelope["topology_context"] = topology
        row["evidence_envelope"] = envelope
        audit = row.get("audit") if isinstance(row.get("audit"), dict) else {}
        existing = list(audit.get("artifact_files", ()) or ())
        audit["artifact_files"] = tuple(dict.fromkeys(existing + _relative_artifact_refs(clean_paths, manifest_path)))
        row["audit"] = audit
    return enriched


def _raw_artifact_paths(result: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    path = result.get("path")
    if isinstance(path, str) and path:
        paths.append(path)
    record_path = result.get("record_path")
    if isinstance(record_path, str) and record_path:
        paths.append(record_path)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                paths.append(artifact["path"])
    return paths


def _relative_artifact_refs(paths: list[str], manifest_path: Path) -> list[str]:
    refs = [str(manifest_path.relative_to(REPO_ROOT)) if manifest_path.is_relative_to(REPO_ROOT) else str(manifest_path)]
    for raw_path in paths:
        path = Path(raw_path)
        refs.append(str(path.relative_to(REPO_ROOT)) if path.is_absolute() and path.is_relative_to(REPO_ROOT) else str(path))
    return refs


if __name__ == "__main__":
    main()
