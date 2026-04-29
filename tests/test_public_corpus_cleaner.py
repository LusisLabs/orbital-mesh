import json
import zipfile
from pathlib import Path

from shared.mesh_runtime.public_corpus_cleaner import build_clean_public_corpus_index


def test_cleaner_writes_runtime_safe_public_index(tmp_path: Path) -> None:
    archive = tmp_path / "raw" / "otel.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("demo/service/trace.json", "{}")
        zf.writestr("demo/service/metrics.json", "{}")
    raw_manifest = tmp_path / "raw_manifest.json"
    raw_manifest.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "name": "OpenTelemetry demo",
                        "slug": "opentelemetry-demo",
                        "status": "downloaded",
                        "acquisition_kind": "github_archive",
                        "path": str(archive),
                        "sha256": "abc",
                        "license_note": "test",
                        "size_note": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    public_fixture = tmp_path / "public_sources.json"
    public_fixture.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": "OpenTelemetry demo",
                        "source_kind": "public_tooling",
                        "domains": ["web2"],
                        "environments": ["benchmark"],
                        "telemetry_planes": ["logs", "metrics", "traces"],
                        "url": "https://example.test/otel",
                        "labels": ["opentelemetry", "otlp"],
                        "mesh_use": ["bootstrap", "evaluation", "root_cause"],
                        "limitation": "synthetic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = build_clean_public_corpus_index(
        raw_manifest_path=raw_manifest,
        public_fixture_path=public_fixture,
        output_dir=tmp_path / "clean",
        zip_sample_limit=1,
    )
    rows = [json.loads(line) for line in Path(report["jsonl_path"]).read_text(encoding="utf-8").splitlines()]

    assert report["record_count"] == 1
    assert rows[0]["agentic_flow"]["reasoning_bank_role"] == "public_bootstrap_advisory"
    assert "otlp_pipeline_regression" in rows[0]["agentic_flow"]["allowed_uses"]
    assert rows[0]["artifacts"][0]["zip_valid"] is True
    assert rows[0]["artifacts"][0]["zip_entry_count"] == 2
    assert rows[0]["artifacts"][0]["zip_sample"] == ["demo/service/trace.json"]
