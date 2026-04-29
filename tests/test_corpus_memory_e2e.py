import json
from pathlib import Path

from shared.mesh_runtime import ActiveMemoryStore, FileStateStore, RuntimeConfig
from shared.mesh_runtime.corpus_store import (
    CorpusQuery,
    IncidentCorpusDatabase,
    project_database_to_memory,
)
from shared.mesh_runtime.incident_corpus import write_session_corpus
from shared.mesh_runtime.monitoring_corpus import build_public_monitoring_corpus_rows
from shared.mesh_runtime.reasoning_bank import ReasoningBankService
from shared.mesh_runtime.contracts import Trigger


SERVICE = "el-1-reth-lighthouse"


def test_corpus_database_to_memory_e2e(tmp_path: Path) -> None:
    session_dir = tmp_path / "reth-kurtosis-loop" / "session_test"
    _write_successful_cycle(session_dir / "000001_peer_starvation_restart")
    _write_human_hold_cycle(session_dir / "000005_disk_pressure_escalate")

    corpus_result = write_session_corpus(session_dir)
    database = IncidentCorpusDatabase(tmp_path / "corpus" / "incident_corpus.sqlite")
    imported = database.import_jsonl(corpus_result.jsonl_path)

    assert imported == 2
    assert database.summary()["row_count"] == 2
    assert database.outcome_counts() == {"human_hold": 1, "successful": 1}

    successful_rows = database.query(
        CorpusQuery(service=SERVICE, outcome="successful", text="peer starvation", limit=10)
    )
    assert len(successful_rows) == 1
    assert successful_rows[0]["training_fact"]["promotion_candidate"] is True

    state_dir = tmp_path / "state"
    state_store = FileStateStore(RuntimeConfig(state_directory=state_dir, vault_path=state_dir / "vault"))
    projections = project_database_to_memory(database, state_store, query=CorpusQuery(service=SERVICE, limit=10))
    assert len(projections) == 2
    assert any(item["claim_id"] for item in projections)
    repeated = project_database_to_memory(database, state_store, query=CorpusQuery(service=SERVICE, limit=10))
    assert repeated == projections
    assert len(state_store.list_observations({"service": SERVICE}, {"kind": "incident_corpus_row", "limit": 10})) == 2

    retrieval = state_store.retrieve_memory(
        {
            "query": "peer starvation recovered after restart",
            "scope": {"service": SERVICE},
            "limit": 10,
            "channels": ["lexical", "graph"],
        }
    )
    contents = [item["content"] for item in retrieval["results"]]
    assert any("peer_starvation_restart" in content for content in contents)
    assert any("verified corpus evidence" in content for content in contents)

    compaction = ActiveMemoryStore(state_dir).project_packet(
        run_id="run_active",
        service=SERVICE,
        packet=retrieval["packet"],
        source_event_ids=["corpus_projection"],
        merkle_root="root_test",
    )
    active = ActiveMemoryStore(state_dir).active_facts(SERVICE)

    assert compaction.active_facts
    assert active["services"][SERVICE]
    assert any("peer_starvation_restart" in fact["content"] for fact in active["services"][SERVICE])


def test_public_bootstrap_rows_are_queryable_but_not_breakthrough_evidence(tmp_path: Path) -> None:
    database = IncidentCorpusDatabase(tmp_path / "corpus" / "incident_corpus.sqlite")
    imported = database.import_rows(build_public_monitoring_corpus_rows())

    summary = database.summary()
    aiops_rows = database.query(CorpusQuery(text="AIOps traces root cause", limit=10))

    assert imported == 13
    assert summary["row_count"] == 13
    assert summary["source_kinds"] == {"public_dataset": 8, "public_tooling": 5}
    assert summary["breakthrough"]["row_count"] == 0
    assert summary["breakthrough"]["input_row_count"] == 13
    assert summary["breakthrough"]["ready"] is False
    assert any(row["labels"]["source_name"] == "AIOps Challenge 2020" for row in aiops_rows)


def test_public_bootstrap_rows_project_to_reasoning_bank_advisory_claims(tmp_path: Path) -> None:
    database = IncidentCorpusDatabase(tmp_path / "corpus" / "incident_corpus.sqlite")
    database.import_rows(build_public_monitoring_corpus_rows())
    state_dir = tmp_path / "state"
    state_store = FileStateStore(RuntimeConfig(state_directory=state_dir, vault_path=state_dir / "vault"))

    projections = project_database_to_memory(database, state_store, query=CorpusQuery(text="OpenTelemetry OTLP traces", limit=10))
    artifact = ReasoningBankService(state_store, max_strategies=5).retrieve_for_trigger(_otel_trigger())

    assert any(item["claim_id"] for item in projections)
    assert artifact["enabled"] is True
    assert any("OpenTelemetry" in strategy["statement"] for strategy in artifact["strategies"])
    assert all(strategy["tier"] == "semantic" for strategy in artifact["strategies"])


def _write_successful_cycle(cycle_dir: Path) -> None:
    cycle_dir.mkdir(parents=True)
    _write(
        cycle_dir / "summary.json",
        {
            "cycle": 1,
            "profile": "peer_starvation_restart",
            "run_id": "run_success",
            "stage": "completed",
            "status": "completed",
            "decision_type": "restart_systemd_service",
            "evaluation_recommendation": "execute",
            "execution_status": "succeeded",
            "feedback_outcome": "successful",
        },
    )
    _write(cycle_dir / "signal_payload.json", _reth_signal(error_signatures=["peer_starvation"], peer_count=1))
    _write(
        cycle_dir / "run_final.json",
        {
            "run_id": "run_success",
            "stage": "completed",
            "artifacts": {
                "decision": {"decision_type": "restart_systemd_service", "confidence": 0.91},
                "evaluation": {"final_recommendation": "execute", "passed": True},
                "execution": {"status": "succeeded"},
                "feedback": {"outcome": "successful"},
                "evidence_pack": _reth_signal(error_signatures=["peer_starvation"], peer_count=1),
            },
        },
    )
    _write(cycle_dir / "scenario_analysis.json", {"confidence": 0.91, "risk_level": "medium"})


def _write_human_hold_cycle(cycle_dir: Path) -> None:
    cycle_dir.mkdir(parents=True)
    _write(
        cycle_dir / "summary.json",
        {
            "cycle": 5,
            "profile": "disk_pressure_escalate",
            "run_id": "run_hold",
            "stage": "evaluation_ready",
            "status": "policy_held",
            "decision_type": "escalate",
            "evaluation_recommendation": "human_review",
        },
    )
    _write(cycle_dir / "signal_payload.json", _reth_signal(error_signatures=["disk_pressure"], disk_used_pct=97.0))
    _write(
        cycle_dir / "run_final.json",
        {
            "run_id": "run_hold",
            "stage": "evaluation_ready",
            "artifacts": {
                "decision": {"decision_type": "escalate", "confidence": 0.8, "risk": {"level": "high"}},
                "evaluation": {"final_recommendation": "human_review", "passed": False},
                "evidence_pack": _reth_signal(error_signatures=["disk_pressure"], disk_used_pct=97.0),
            },
        },
    )
    _write(cycle_dir / "scenario_analysis.json", {"confidence": 0.8, "risk_level": "high"})


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _reth_signal(
    *,
    error_signatures: list[str],
    disk_used_pct: float = 30.0,
    peer_count: int = 3,
) -> dict[str, object]:
    return {
        "signal_type": "reth_node",
        "signal_id": f"sig_reth_{error_signatures[0]}",
        "environment": "production",
        "service": SERVICE,
        "node": {
            "name": SERVICE,
            "client_version": "reth/v1.9.3",
            "deployment_mode": "docker",
            "network": "kurtosis",
            "role": "full",
        },
        "execution": {"peer_count": peer_count, "head_block": 100, "syncing": False, "block_lag": 0},
        "storage": {"disk_used_pct": disk_used_pct},
        "logs": {"error_signatures": error_signatures},
        "resource_attributes": {"service.name": SERVICE, "deployment.environment": "production"},
        "related_context": {"kurtosis_enclave": "mesh-reth", "kurtosis_service": SERVICE},
    }


def _otel_trigger() -> Trigger:
    return Trigger(
        trigger_id="trig_otel",
        trigger_type="otel_metric_regression",
        triggered_at="2026-04-28T00:00:00+00:00",
        environment="development",
        service="opentelemetry-astronomy-shop-demo",
        endpoint="/checkout",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=None,
        segment={},
        metrics={"observed_error_rate": 0.05, "baseline_error_rate": 0.01, "sample_size": 100},
        related_context={
            "metric_regression": {"metric_name": "otelcol_exporter_send_failed_spans", "direction": "increase"},
            "error_signatures": ["otlp", "traces", "collector"],
        },
    )
