import json
from pathlib import Path

from shared.mesh_runtime.monitoring_corpus import (
    INTERNAL_CORPUS_TARGETS,
    PUBLIC_MONITORING_CORPUS,
    build_public_monitoring_corpus_rows,
    corpus_gap_summary,
    internal_targets_for_environment,
    public_records_for_domain,
    public_records_for_telemetry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_catalog_covers_web2_and_crypto_bootstrap_sources() -> None:
    web2_names = {record.name for record in public_records_for_domain("web2")}
    crypto_names = {record.name for record in public_records_for_domain("crypto")}

    assert "Loghub" in web2_names
    assert "AIOps Challenge 2020" in web2_names
    assert "Train Ticket anomaly datasets" in web2_names
    assert "OpenTelemetry Astronomy Shop demo" in web2_names
    assert "OpenTelemetry telemetrygen" in web2_names
    assert "LO2v2 microservice logs and metrics" in web2_names
    assert "Ethereum ETL and public BigQuery exports" in crypto_names
    assert "Elliptic Bitcoin dataset" in crypto_names


def test_internal_targets_span_prod_and_development_nodes() -> None:
    production_targets = {target.name for target in internal_targets_for_environment("production")}
    development_targets = {target.name for target in internal_targets_for_environment("development")}

    assert "ethereum_execution_client" in production_targets
    assert "ethereum_consensus_and_validator" in production_targets
    assert "rpc_gateway_and_indexer" in production_targets
    assert "devnet_and_kurtosis_enclave" in development_targets
    assert "kubernetes_service" in development_targets


def test_crypto_gap_summary_keeps_internal_corpus_as_required_edge() -> None:
    summary = corpus_gap_summary("crypto")

    assert summary["requires_internal_corpus"] is True
    assert summary["public_record_count"] >= 3
    assert summary["internal_target_count"] >= 4
    assert "runbooks" in summary["required_planes"]


def test_catalog_records_have_actionable_limitations() -> None:
    for record in PUBLIC_MONITORING_CORPUS:
        assert record.url.startswith("https://")
        assert record.mesh_use
        assert record.limitation

    for target in INTERNAL_CORPUS_TARGETS:
        assert target.required_signals
        assert target.why_it_matters


def test_lookup_by_telemetry_plane() -> None:
    trace_sources = {record.name for record in public_records_for_telemetry("traces")}

    assert "AIOps Challenge 2020" in trace_sources
    assert "Train Ticket anomaly datasets" in trace_sources
    assert "OpenTelemetry Astronomy Shop demo" in trace_sources


def test_public_source_fixture_matches_catalog() -> None:
    fixture = json.loads((REPO_ROOT / "fixtures" / "monitoring_corpus" / "public_sources.json").read_text(encoding="utf-8"))
    fixture_names = {source["name"] for source in fixture["sources"]}
    catalog_names = {record.name for record in PUBLIC_MONITORING_CORPUS}

    assert fixture["schema_version"] == "mesh.public_monitoring_sources.v1"
    assert fixture_names == catalog_names
    assert "offline fixtures" in fixture["policy"]


def test_public_catalog_builds_non_promotable_corpus_rows() -> None:
    rows = build_public_monitoring_corpus_rows()
    by_name = {row["labels"]["source_name"]: row for row in rows}

    assert len(rows) == len(PUBLIC_MONITORING_CORPUS)
    assert by_name["Loghub"]["source"]["kind"] == "public_dataset"
    assert by_name["AIOps Challenge 2020"]["source"]["collector"] == "public_monitoring_catalog"
    assert by_name["Google Borg cluster traces"]["training_fact"]["promotion_candidate"] is False
    assert by_name["Alibaba Cluster Trace Program"]["training_fact"]["outcome"] == "skipped"
    assert by_name["DeathStarBench"]["source"]["kind"] == "public_tooling"
    assert by_name["Ethereum ETL and public BigQuery exports"]["target_class"] == "chain_data_reference"
    assert "validator" in by_name["Ethereum/Gnosis validator monitoring references"]["labels"]["coverage"]
    assert by_name["OpenTelemetry Astronomy Shop demo"]["source"]["kind"] == "public_tooling"
    assert "kubernetes_service" in by_name["OpenTelemetry telemetrygen"]["labels"]["coverage"]
