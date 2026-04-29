"""Monitoring corpus catalog for Mesh Intelligence.

The public datasets here are bootstrap material, not the moat. Mesh's edge is
the private corpus assembled from production and development node telemetry:
logs, metrics, traces, probe evidence, run events, operator decisions, and
post-action feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Literal


Domain = Literal["crypto", "web2", "infrastructure"]
Environment = Literal["production", "development", "testnet", "benchmark"]
TelemetryPlane = Literal["logs", "metrics", "traces", "events", "graphs", "runbooks"]
SourceKind = Literal["public_dataset", "public_tooling", "internal_corpus"]
CorpusUse = Literal["bootstrap", "evaluation", "training", "live_baseline", "root_cause"]


@dataclass(frozen=True)
class MonitoringCorpusRecord:
    """A dataset or telemetry source that can support Mesh monitoring intelligence."""

    name: str
    source_kind: SourceKind
    domains: tuple[Domain, ...]
    environments: tuple[Environment, ...]
    telemetry_planes: tuple[TelemetryPlane, ...]
    url: str
    labels: tuple[str, ...]
    mesh_use: tuple[CorpusUse, ...]
    limitation: str


@dataclass(frozen=True)
class MonitoringTargetClass:
    """A class of node or service Mesh should monitor internally."""

    name: str
    domains: tuple[Domain, ...]
    environments: tuple[Environment, ...]
    telemetry_planes: tuple[TelemetryPlane, ...]
    required_signals: tuple[str, ...]
    why_it_matters: str


PUBLIC_MONITORING_CORPUS: tuple[MonitoringCorpusRecord, ...] = (
    MonitoringCorpusRecord(
        name="Loghub",
        source_kind="public_dataset",
        domains=("web2", "infrastructure"),
        environments=("benchmark",),
        telemetry_planes=("logs",),
        url="https://github.com/logpai/loghub",
        labels=("some_labeled", "system_logs", "log_parsing"),
        mesh_use=("bootstrap", "evaluation"),
        limitation="Broad system-log coverage, but not crypto-node specific and not private production telemetry.",
    ),
    MonitoringCorpusRecord(
        name="AIOps Challenge 2020",
        source_kind="public_dataset",
        domains=("web2", "infrastructure"),
        environments=("benchmark",),
        telemetry_planes=("metrics", "traces", "events"),
        url="https://github.com/NetManAIOps/AIOps-Challenge-2020-Data",
        labels=("failure_windows", "business_metrics", "platform_metrics", "call_traces"),
        mesh_use=("bootstrap", "evaluation", "root_cause"),
        limitation="Useful multimodal failure benchmark; license and domain differ from node-operator production data.",
    ),
    MonitoringCorpusRecord(
        name="Train Ticket anomaly datasets",
        source_kind="public_dataset",
        domains=("web2",),
        environments=("benchmark",),
        telemetry_planes=("logs", "metrics", "traces"),
        url="https://zenodo.org/records/6979726",
        labels=("microservices", "prometheus", "jaeger", "version_faults"),
        mesh_use=("bootstrap", "evaluation", "root_cause"),
        limitation="Excellent service-fault shape, but synthetic benchmark traffic.",
    ),
    MonitoringCorpusRecord(
        name="Eadro microservice datasets",
        source_kind="public_dataset",
        domains=("web2",),
        environments=("benchmark",),
        telemetry_planes=("logs", "metrics", "traces"),
        url="https://zenodo.org/records/7615394",
        labels=("root_cause_localization", "social_network", "train_ticket"),
        mesh_use=("evaluation", "root_cause"),
        limitation="Good multimodal RCA data; still benchmark-scoped rather than internal fleet behavior.",
    ),
    MonitoringCorpusRecord(
        name="LO2v2 microservice logs and metrics",
        source_kind="public_dataset",
        domains=("web2",),
        environments=("benchmark",),
        telemetry_planes=("logs", "metrics", "events"),
        url="https://zenodo.org/records/18937117",
        labels=("microservices", "api_anomaly", "logs", "metrics", "large_dataset"),
        mesh_use=("bootstrap", "evaluation", "root_cause"),
        limitation="Recent open microservice anomaly dataset, but full data volume is hundreds of GB and not trace-complete.",
    ),
    MonitoringCorpusRecord(
        name="OpenTelemetry Astronomy Shop demo",
        source_kind="public_tooling",
        domains=("web2", "infrastructure"),
        environments=("development", "benchmark"),
        telemetry_planes=("logs", "metrics", "traces", "events"),
        url="https://github.com/open-telemetry/opentelemetry-demo",
        labels=("opentelemetry", "otlp", "microservices", "synthetic_load", "feature_flags", "collector"),
        mesh_use=("bootstrap", "evaluation", "root_cause"),
        limitation="Generates realistic OpenTelemetry signals, but it is a demo workload rather than production incident data.",
    ),
    MonitoringCorpusRecord(
        name="OpenTelemetry telemetrygen",
        source_kind="public_tooling",
        domains=("web2", "infrastructure"),
        environments=("development", "benchmark"),
        telemetry_planes=("logs", "metrics", "traces", "events"),
        url="https://github.com/open-telemetry/opentelemetry-collector-contrib",
        labels=("opentelemetry", "otlp", "telemetry_generator", "collector_pipeline", "load_testing"),
        mesh_use=("bootstrap", "evaluation"),
        limitation="Synthetic signal generator for OTLP pipeline tests, not a labeled incident dataset.",
    ),
    MonitoringCorpusRecord(
        name="Google Borg cluster traces",
        source_kind="public_dataset",
        domains=("infrastructure",),
        environments=("production", "benchmark"),
        telemetry_planes=("events", "metrics"),
        url="https://github.com/google/cluster-data",
        labels=("production_cluster", "workload_traces", "resource_management"),
        mesh_use=("bootstrap", "evaluation"),
        limitation="Production-scale infrastructure traces, not application logs or blockchain node semantics.",
    ),
    MonitoringCorpusRecord(
        name="Alibaba Cluster Trace Program",
        source_kind="public_dataset",
        domains=("infrastructure", "web2"),
        environments=("production", "benchmark"),
        telemetry_planes=("events", "metrics", "traces"),
        url="https://github.com/alibaba/clusterdata",
        labels=("production_cluster", "microservices", "gpu", "resource_management"),
        mesh_use=("bootstrap", "evaluation"),
        limitation="Large production traces; telemetry schema is cluster-management oriented.",
    ),
    MonitoringCorpusRecord(
        name="DeathStarBench",
        source_kind="public_tooling",
        domains=("web2",),
        environments=("development", "benchmark"),
        telemetry_planes=("logs", "metrics", "traces"),
        url="https://github.com/delimitrou/DeathStarBench",
        labels=("microservices", "benchmark_harness", "cloud_edge"),
        mesh_use=("bootstrap", "evaluation"),
        limitation="Benchmark harness, not a standing dataset unless Mesh records generated runs.",
    ),
    MonitoringCorpusRecord(
        name="Ethereum ETL and public BigQuery exports",
        source_kind="public_tooling",
        domains=("crypto",),
        environments=("production", "development"),
        telemetry_planes=("events", "graphs"),
        url="https://ethereum-etl.readthedocs.io/",
        labels=("blocks", "transactions", "logs", "traces", "chain_reorgs"),
        mesh_use=("bootstrap", "live_baseline"),
        limitation="On-chain truth and event data, not runtime logs from execution or consensus clients.",
    ),
    MonitoringCorpusRecord(
        name="Elliptic Bitcoin dataset",
        source_kind="public_dataset",
        domains=("crypto",),
        environments=("production", "benchmark"),
        telemetry_planes=("graphs", "events"),
        url="https://www.kaggle.com/datasets/ellipticco/elliptic-data-set/data",
        labels=("licit_illicit", "transaction_graph", "temporal_graph"),
        mesh_use=("evaluation",),
        limitation="Fraud graph benchmark; useful for graph anomaly patterns, not node health monitoring.",
    ),
    MonitoringCorpusRecord(
        name="Ethereum/Gnosis validator monitoring references",
        source_kind="public_tooling",
        domains=("crypto",),
        environments=("production", "testnet"),
        telemetry_planes=("metrics", "events", "runbooks"),
        url="https://docs.ethstaker.org/scaled-node-operators/monitoring-at-scale/",
        labels=("validator_performance", "beacon_api", "prometheus", "grafana"),
        mesh_use=("bootstrap", "live_baseline", "root_cause"),
        limitation="Operational guidance and metric vocabulary, not downloadable anomaly-labeled logs.",
    ),
)


INTERNAL_CORPUS_TARGETS: tuple[MonitoringTargetClass, ...] = (
    MonitoringTargetClass(
        name="ethereum_execution_client",
        domains=("crypto",),
        environments=("production", "development", "testnet"),
        telemetry_planes=("logs", "metrics", "events"),
        required_signals=(
            "peer_count",
            "head_block",
            "sync_state",
            "block_lag",
            "rpc_error_rate",
            "disk_used_pct",
            "client_version",
        ),
        why_it_matters="Execution-client stalls and peer isolation directly affect RPC correctness and validator duties.",
    ),
    MonitoringTargetClass(
        name="ethereum_consensus_and_validator",
        domains=("crypto",),
        environments=("production", "development", "testnet"),
        telemetry_planes=("logs", "metrics", "events"),
        required_signals=(
            "slot_lag",
            "missed_attestations",
            "missed_proposals",
            "finalized_epoch",
            "validator_balance_delta",
            "beacon_peer_count",
        ),
        why_it_matters="Consensus lag and validator duty misses are revenue and safety failures.",
    ),
    MonitoringTargetClass(
        name="rollup_or_appchain_node",
        domains=("crypto",),
        environments=("production", "development", "testnet"),
        telemetry_planes=("logs", "metrics", "events", "graphs"),
        required_signals=(
            "sequencer_liveness",
            "batch_submission_lag",
            "derivation_lag",
            "safe_head_lag",
            "bridge_event_lag",
        ),
        why_it_matters="Rollup operators need cross-layer correlation between local node state and L1 settlement.",
    ),
    MonitoringTargetClass(
        name="rpc_gateway_and_indexer",
        domains=("crypto", "web2"),
        environments=("production", "development"),
        telemetry_planes=("logs", "metrics", "traces", "events"),
        required_signals=(
            "request_rate",
            "latency_p95",
            "error_rate",
            "upstream_node_health",
            "cache_hit_rate",
            "indexing_lag",
        ),
        why_it_matters="Gateway and indexer degradation is where user-facing Web2 symptoms meet crypto-node causes.",
    ),
    MonitoringTargetClass(
        name="kubernetes_service",
        domains=("web2", "infrastructure"),
        environments=("production", "development"),
        telemetry_planes=("logs", "metrics", "traces", "events"),
        required_signals=(
            "pod_restart_count",
            "deployment_generation",
            "latency_p95",
            "error_rate",
            "cpu_saturation",
            "memory_pressure",
        ),
        why_it_matters="This is the common Web2 substrate for APIs, operators, indexers, and control-plane services.",
    ),
    MonitoringTargetClass(
        name="stateful_dependency",
        domains=("web2", "infrastructure", "crypto"),
        environments=("production", "development"),
        telemetry_planes=("logs", "metrics", "events"),
        required_signals=(
            "disk_used_pct",
            "write_latency",
            "replication_lag",
            "connection_saturation",
            "backup_status",
        ),
        why_it_matters="Databases, queues, and object stores create second-order failures that naive service monitoring misses.",
    ),
    MonitoringTargetClass(
        name="devnet_and_kurtosis_enclave",
        domains=("crypto", "web2", "infrastructure"),
        environments=("development", "testnet"),
        telemetry_planes=("logs", "metrics", "events", "runbooks"),
        required_signals=(
            "enclave_service_state",
            "fault_overlay",
            "expected_failure_mode",
            "actual_recovery_time",
            "post_action_probe_result",
        ),
        why_it_matters="Development telemetry supplies labeled faults that public crypto-node datasets do not provide.",
    ),
)


def public_records_for_domain(domain: Domain) -> tuple[MonitoringCorpusRecord, ...]:
    """Return public corpus records that apply to a monitoring domain."""

    return tuple(record for record in PUBLIC_MONITORING_CORPUS if domain in record.domains)


def public_records_for_telemetry(telemetry_plane: TelemetryPlane) -> tuple[MonitoringCorpusRecord, ...]:
    """Return public corpus records that include a telemetry plane."""

    return tuple(record for record in PUBLIC_MONITORING_CORPUS if telemetry_plane in record.telemetry_planes)


def internal_targets_for_domain(domain: Domain) -> tuple[MonitoringTargetClass, ...]:
    """Return internal target classes Mesh should cover for a domain."""

    return tuple(target for target in INTERNAL_CORPUS_TARGETS if domain in target.domains)


def internal_targets_for_environment(environment: Environment) -> tuple[MonitoringTargetClass, ...]:
    """Return internal target classes Mesh should observe in an environment."""

    return tuple(target for target in INTERNAL_CORPUS_TARGETS if environment in target.environments)


def corpus_gap_summary(domain: Domain) -> dict[str, object]:
    """Summarize why internal telemetry is required for a domain."""

    public_records = public_records_for_domain(domain)
    internal_targets = internal_targets_for_domain(domain)
    public_planes = sorted({plane for record in public_records for plane in record.telemetry_planes})
    required_planes = sorted({plane for target in internal_targets for plane in target.telemetry_planes})
    missing_planes = tuple(plane for plane in required_planes if plane not in public_planes)
    return {
        "domain": domain,
        "public_record_count": len(public_records),
        "internal_target_count": len(internal_targets),
        "public_planes": tuple(public_planes),
        "required_planes": tuple(required_planes),
        "missing_public_planes": missing_planes,
        "requires_internal_corpus": True,
    }


def build_public_monitoring_corpus_rows(
    records: tuple[MonitoringCorpusRecord, ...] = PUBLIC_MONITORING_CORPUS,
) -> list[dict[str, Any]]:
    """Convert public monitoring-source catalog records into corpus rows.

    Public rows are offline bootstrap and evaluation material. They are stored
    in the same query database as internal rows so parser and retrieval tests can
    exercise Loghub, AIOps, cluster-trace, benchmark, and crypto-reference
    coverage, but they are deliberately non-promotable and do not count toward
    Breakthrough readiness.
    """

    generated_at = _now_iso()
    return [_public_record_row(record, generated_at=generated_at) for record in records]


def _public_record_row(record: MonitoringCorpusRecord, *, generated_at: str) -> dict[str, Any]:
    slug = _slug(record.name)
    return {
        "schema_version": "mesh.incident_corpus.v1",
        "row_id": f"public_monitoring_source:{slug}",
        "created_at": generated_at,
        "source": {
            "kind": record.source_kind,
            "collector": "public_monitoring_catalog",
            "session_id": "public_monitoring_sources",
            "cycle_dir": slug,
            "profile": "public_bootstrap_reference",
            "cycle": None,
            "run_id": f"public:{slug}",
            "url": record.url,
        },
        "domain": record.domains[0],
        "environment": record.environments[0],
        "service": slug,
        "target_class": _public_target_class(record),
        "labels": {
            "source_name": record.name,
            "source_kind": record.source_kind,
            "domains": record.domains,
            "environments": record.environments,
            "telemetry_planes": record.telemetry_planes,
            "mesh_use": record.mesh_use,
            "public_labels": record.labels,
            "fault_profile": "public_bootstrap_reference",
            "error_signatures": (),
            "outcome": "skipped",
            "decision_type": "offline_fixture",
            "evaluation_recommendation": "evaluate_only",
            "execution_status": "not_applicable",
            "feedback_outcome": "not_applicable",
            "coverage": _public_coverage(record),
        },
        "evidence_envelope": {
            "inbound_signal": {
                "signal_type": "public_monitoring_source",
                "source_name": record.name,
                "source_url": record.url,
                "telemetry_planes": record.telemetry_planes,
                "domains": record.domains,
                "environments": record.environments,
                "labels": record.labels,
            },
            "current_probe_pack": {},
            "topology_context": {
                "service": slug,
                "environment": record.environments[0],
                "source_url": record.url,
                "limitation": record.limitation,
            },
            "scenario_analysis": {
                "summary": record.limitation,
                "mesh_use": record.mesh_use,
                "risk_level": "benchmark_only",
            },
            "decision": {"decision_type": "offline_fixture", "confidence": 1.0},
            "evaluation": {"final_recommendation": "evaluate_only", "passed": True},
            "action": {"status": "not_applicable"},
            "feedback": {"outcome": "not_applicable"},
            "post_action_observations": {},
        },
        "training_fact": {
            "outcome": "skipped",
            "decision_type": "offline_fixture",
            "evaluation_recommendation": "evaluate_only",
            "execution_status": "not_applicable",
            "feedback_outcome": "not_applicable",
            "stage": "offline_bootstrap",
            "status": "cataloged",
            "confidence": 1.0,
            "risk_level": "benchmark_only",
            "quality_measurements": {},
            "promotion_candidate": False,
            "promotion_reasons": ("public_source_requires_internal_corroboration",),
        },
        "audit": {
            "signal_collection": {"source_url": record.url},
            "evidence_graph": {},
            "merkle": {},
            "run_event_count": 0,
            "artifact_files": ("fixtures/monitoring_corpus/public_sources.json",),
        },
    }


def _public_target_class(record: MonitoringCorpusRecord) -> str:
    labels = set(record.labels)
    planes = set(record.telemetry_planes)
    domains = set(record.domains)
    name = record.name.lower()
    if "validator" in labels or "beacon_api" in labels or "validator" in name:
        return "ethereum_consensus_and_validator"
    if "blocks" in labels or "chain_reorgs" in labels or "crypto" in domains:
        return "chain_data_reference"
    if "microservices" in labels or "traces" in planes:
        return "kubernetes_service"
    if "production_cluster" in labels or "resource_management" in labels:
        return "stateful_dependency"
    return "public_monitoring_reference"


def _public_coverage(record: MonitoringCorpusRecord) -> tuple[str, ...]:
    labels = set(record.labels)
    name = record.name.lower()
    coverage: set[str] = set()
    if "validator" in labels or "validator" in name:
        coverage.add("validator")
    if "beacon_api" in labels or "ethstaker" in name or "gnosis" in name:
        coverage.add("lighthouse")
    if "prometheus" in labels or "microservices" in labels or "production_cluster" in labels:
        coverage.add("kubernetes_service")
    if "logs" in record.telemetry_planes and "crypto" not in record.domains:
        coverage.add("kubernetes_service")
    if "blocks" in labels or "transactions" in labels or "chain_reorgs" in labels:
        coverage.update(("rpc_gateway", "indexer"))
    return tuple(sorted(coverage))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown-public-source"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
