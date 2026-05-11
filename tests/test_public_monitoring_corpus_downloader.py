import hashlib
import json
from pathlib import Path
from unittest import mock

import scripts.download_public_monitoring_corpus as downloader
import scripts.export_monitoring_corpus as exporter
from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase
from shared.mesh_runtime.monitoring_corpus import build_public_monitoring_corpus_rows


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._offset = 0

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_download_direct_source_writes_artifact_and_hash(tmp_path: Path) -> None:
    spec = downloader.PublicCorpusDownloadSpec(
        name="Tiny Source",
        slug="tiny-source",
        acquisition_kind="github_archive",
        url="https://example.test/tiny.zip",
        artifact_name="tiny.zip",
        license_note="test",
        size_note="test",
    )
    payload = b"raw dataset bytes"

    with mock.patch.object(downloader.urllib.request, "urlopen", return_value=_Response(payload)):
        result = downloader._acquire_spec(
            spec,
            output_dir=tmp_path,
            overwrite=False,
            timeout_seconds=1,
            max_bytes=0,
        )

    artifact = tmp_path / "tiny-source" / "tiny.zip"
    assert result["status"] == "downloaded"
    assert artifact.read_bytes() == payload
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / "tiny-source" / "source.json").is_file()
    assert (tmp_path / "tiny-source" / "tiny.zip.sha256").is_file()


def test_auth_required_source_is_manifested_without_download(tmp_path: Path) -> None:
    spec = downloader.PublicCorpusDownloadSpec(
        name="Auth Source",
        slug="auth-source",
        acquisition_kind="auth_required",
        url="https://example.test/auth",
        artifact_name=None,
        license_note="auth",
        size_note="auth",
    )

    with mock.patch.object(downloader.urllib.request, "urlopen") as urlopen:
        result = downloader._acquire_spec(
            spec,
            output_dir=tmp_path,
            overwrite=False,
            timeout_seconds=1,
            max_bytes=0,
        )

    assert result["status"] == "skipped_auth_required"
    assert (tmp_path / "auth-source" / "source.json").is_file()
    urlopen.assert_not_called()


def test_zenodo_record_downloads_declared_files(tmp_path: Path) -> None:
    spec = downloader.PublicCorpusDownloadSpec(
        name="Zenodo Source",
        slug="zenodo-source",
        acquisition_kind="zenodo_record",
        url="https://zenodo.test/api/records/1",
        artifact_name=None,
        license_note="zenodo",
        size_note="zenodo",
    )
    record = {"files": [{"key": "trace.jsonl", "links": {"self": "https://zenodo.test/files/trace.jsonl"}}]}
    calls = [_Response(json.dumps(record).encode()), _Response(b'{"metric":1}\n')]

    with mock.patch.object(downloader.urllib.request, "urlopen", side_effect=calls):
        result = downloader._acquire_spec(
            spec,
            output_dir=tmp_path,
            overwrite=False,
            timeout_seconds=1,
            max_bytes=0,
        )

    assert result["status"] == "downloaded"
    assert result["artifacts"][0]["zenodo_key"] == "trace.jsonl"
    assert (tmp_path / "zenodo-source" / "record.json").is_file()
    assert (tmp_path / "zenodo-source" / "trace.jsonl").read_text(encoding="utf-8") == '{"metric":1}\n'


def test_zenodo_metadata_source_downloads_record_only(tmp_path: Path) -> None:
    spec = downloader.PublicCorpusDownloadSpec(
        name="Large Zenodo Source",
        slug="large-zenodo-source",
        acquisition_kind="zenodo_record_metadata",
        url="https://zenodo.test/api/records/2",
        artifact_name=None,
        license_note="zenodo",
        size_note="large",
    )
    record = {"files": [{"key": "huge.zip", "size": 1234567890, "links": {"self": "https://zenodo.test/files/huge.zip"}}]}

    with mock.patch.object(downloader.urllib.request, "urlopen", return_value=_Response(json.dumps(record).encode())) as urlopen:
        result = downloader._acquire_spec(
            spec,
            output_dir=tmp_path,
            overwrite=False,
            timeout_seconds=1,
            max_bytes=0,
        )

    assert result["status"] == "downloaded"
    assert result["metadata_only"] is True
    assert result["file_count"] == 1
    assert result["declared_total_bytes"] == 1234567890
    assert (tmp_path / "large-zenodo-source" / "record.json").is_file()
    assert urlopen.call_count == 1


def test_exporter_attaches_raw_manifest_artifacts_to_public_rows(tmp_path: Path) -> None:
    manifest = tmp_path / "raw_manifest.json"
    artifact = tmp_path / "raw" / "loghub" / "loghub-master.zip"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"loghub")
    manifest.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "name": "Loghub",
                        "status": "already_present",
                        "path": str(artifact),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = exporter._attach_raw_manifest(build_public_monitoring_corpus_rows(), manifest)
    loghub = next(row for row in rows if row["labels"]["source_name"] == "Loghub")

    assert loghub["source"]["raw_acquisition_status"] == "already_present"
    assert loghub["labels"]["raw_artifact_count"] == 1
    assert str(artifact) in loghub["source"]["raw_artifact_paths"]
    assert str(manifest) in loghub["audit"]["artifact_files"]


def test_exporter_require_breakthrough_fails_public_only_database(tmp_path: Path) -> None:
    exit_code = exporter.main(
        [
            "--reth-loop-dir",
            str(tmp_path / "missing-loop"),
            "--database",
            str(tmp_path / "corpus.sqlite"),
            "--public-fixture",
            str(tmp_path / "public_sources.json"),
            "--raw-manifest",
            str(tmp_path / "raw_manifest.json"),
            "--clean-manifest",
            str(tmp_path / "clean_manifest.json"),
            "--require-breakthrough",
        ]
    )

    assert exit_code == 1


def test_exporter_require_breakthrough_passes_measured_internal_database(tmp_path: Path) -> None:
    database = IncidentCorpusDatabase(tmp_path / "corpus.sqlite")
    rows = [_breakthrough_row(index) for index in range(100)]
    rows[0]["training_fact"]["quality_measurements"] = {"false_positive_reduction_pct": 0.31}
    rows[1]["evidence_envelope"]["decision"] = {"retrieval_improved_decision": True}
    rows[2]["labels"]["coverage"] = ["reth", "geth"]
    rows[3]["labels"]["coverage"] = ["lighthouse", "validator"]
    rows[4]["labels"]["coverage"] = ["rpc_gateway", "indexer"]
    rows[5]["labels"]["coverage"] = ["kubernetes_service"]
    for index in (7, 8, 9):
        rows[index]["training_fact"].update(
            {
                "outcome": "successful",
                "decision_type": "restart_systemd_service" if index < 9 else "escalate",
                "promotion_candidate": True,
            }
        )
        rows[index]["source"]["profile"] = "peer_starvation_restart" if index < 9 else "disk_pressure_escalate"
    database.import_rows(rows)

    exit_code = exporter.main(
        [
            "--reth-loop-dir",
            str(tmp_path / "missing-loop"),
            "--database",
            str(database.path),
            "--public-fixture",
            str(tmp_path / "public_sources.json"),
            "--raw-manifest",
            str(tmp_path / "raw_manifest.json"),
            "--clean-manifest",
            str(tmp_path / "clean_manifest.json"),
            "--skip-public-bootstrap",
            "--require-breakthrough",
        ]
    )

    assert exit_code == 0


def _breakthrough_row(index: int) -> dict[str, object]:
    return {
        "schema_version": "mesh.incident_corpus.v1",
        "row_id": f"row_{index}",
        "created_at": "2026-04-27T00:00:00Z",
        "source": {
            "kind": "internal_corpus",
            "collector": "test",
            "session_id": "session",
            "cycle_dir": f"{index:06d}_cycle",
            "profile": "healthy_baseline",
            "cycle": index,
            "run_id": f"run_{index}",
        },
        "domain": "crypto",
        "environment": "production",
        "service": "service",
        "target_class": "ethereum_execution_client",
        "labels": {"fault_profile": "healthy_baseline", "error_signatures": []},
        "evidence_envelope": {},
        "training_fact": {
            "outcome": "false_positive",
            "decision_type": "no_action",
            "evaluation_recommendation": "hold",
            "execution_status": None,
            "feedback_outcome": None,
            "promotion_candidate": False,
        },
        "audit": {"artifact_files": []},
    }
