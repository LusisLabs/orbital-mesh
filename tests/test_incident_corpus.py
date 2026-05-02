import json
from pathlib import Path

from shared.mesh_runtime.incident_corpus import (
    build_incident_corpus_row,
    classify_training_outcome,
    promotion_candidate,
    write_session_corpus,
)


def test_builds_human_hold_row_from_reth_cycle(tmp_path: Path) -> None:
    cycle = _cycle_dir(tmp_path, "000005_disk_pressure_escalate")
    _write(
        cycle / "summary.json",
        {
            "cycle": 5,
            "profile": "disk_pressure_escalate",
            "run_id": "run_123",
            "stage": "evaluation_ready",
            "status": "policy_held",
            "decision_type": "escalate",
            "evaluation_recommendation": "human_review",
        },
    )
    _write(cycle / "signal_payload.json", _reth_signal(error_signatures=["disk_pressure"], disk_used_pct=97.0))
    _write(
        cycle / "run_final.json",
        {
            "run_id": "run_123",
            "stage": "evaluation_ready",
            "scenario_key": "reth_node_degraded",
            "latest_merkle_root": "abc",
            "artifacts": {
                "decision": {"decision_type": "escalate", "confidence": 0.74, "risk": {"level": "high"}},
                "evaluation": {"final_recommendation": "human_review", "passed": False},
                "evidence_pack": _reth_signal(error_signatures=["disk_pressure"], disk_used_pct=97.0),
            },
        },
    )
    _write(cycle / "scenario_analysis.json", {"confidence": 0.74, "risk_level": "high"})

    row = build_incident_corpus_row(cycle)

    assert row["schema_version"] == "mesh.incident_corpus.v1"
    assert row["source"]["profile"] == "disk_pressure_escalate"
    assert row["target_class"] == "ethereum_execution_client"
    assert row["training_fact"]["outcome"] == "human_hold"
    assert row["training_fact"]["promotion_candidate"] is False
    assert row["evidence_envelope"]["inbound_signal"]["signal_type"] == "reth_node"
    assert row["evidence_envelope"]["current_probe_pack"]["storage"]["disk_used_pct"] == 97.0
    assert row["evidence_envelope"]["topology_context"]["latest_merkle_root"] == "abc"


def test_successful_execution_can_be_promotion_candidate(tmp_path: Path) -> None:
    cycle = _cycle_dir(tmp_path, "000001_peer_starvation_restart")
    _write(
        cycle / "summary.json",
        {
            "cycle": 1,
            "profile": "peer_starvation_restart",
            "run_id": "run_456",
            "stage": "completed",
            "status": "completed",
            "decision_type": "restart_systemd_service",
            "evaluation_recommendation": "execute",
            "execution_status": "succeeded",
            "feedback_outcome": "successful",
        },
    )
    _write(cycle / "signal_payload.json", _reth_signal(error_signatures=["peer_starvation"], peer_count=1))
    _write(
        cycle / "run_final.json",
        {
            "run_id": "run_456",
            "stage": "completed",
            "artifacts": {
                "decision": {"decision_type": "restart_systemd_service", "confidence": 0.88},
                "evaluation": {"final_recommendation": "execute", "passed": True},
                "execution": {"status": "succeeded"},
                "feedback": {"outcome": "successful"},
            },
        },
    )
    _write(cycle / "scenario_analysis.json", {"confidence": 0.88, "risk_level": "medium"})

    row = build_incident_corpus_row(cycle)

    assert row["training_fact"]["outcome"] == "successful"
    assert row["training_fact"]["promotion_candidate"] is True
    assert "successful_feedback" in row["training_fact"]["promotion_reasons"]
    assert promotion_candidate(row)[0] is True


def test_row_preserves_quality_measurements_retrieval_impact_and_coverage(tmp_path: Path) -> None:
    cycle = _cycle_dir(tmp_path, "000002_peer_starvation_restart")
    _write(
        cycle / "summary.json",
        {
            "cycle": 2,
            "profile": "peer_starvation_restart",
            "run_id": "run_quality",
            "stage": "completed",
            "status": "completed",
            "decision_type": "restart_systemd_service",
            "measurements": {"false_positive_reduction_pct": 0.25},
        },
    )
    _write(cycle / "signal_payload.json", _reth_signal(error_signatures=["peer_starvation"], peer_count=1))
    _write(
        cycle / "run_final.json",
        {
            "run_id": "run_quality",
            "stage": "completed",
            "quality_measurements": {"unsafe_actions_prevented": 1},
            "artifacts": {
                "decision": {
                    "decision_type": "restart_systemd_service",
                    "confidence": 0.9,
                    "quality_measurements": {"retrieval_improved_decision": True},
                },
                "evaluation": {"final_recommendation": "execute", "passed": True},
                "execution": {
                    "status": "succeeded",
                    "operational_delta": {"time_to_diagnosis_reduction_seconds": 45},
                },
                "feedback": {"outcome": "successful"},
            },
        },
    )
    _write(cycle / "scenario_analysis.json", {"confidence": 0.9, "risk_level": "medium"})

    row = build_incident_corpus_row(cycle)

    measurements = row["training_fact"]["quality_measurements"]
    assert measurements["false_positive_reduction_pct"] == 0.25
    assert measurements["unsafe_actions_prevented"] == 1
    assert measurements["time_to_diagnosis_reduction_seconds"] == 45
    assert measurements["retrieval_improved_decision"] is True
    assert "decision.quality_measurements.retrieval_improved_decision" in measurements["evidence_refs"]
    assert "reth" in row["labels"]["coverage"]


def test_geth_signal_exports_as_execution_client_corpus_row(tmp_path: Path) -> None:
    cycle = _cycle_dir(tmp_path, "000003_geth_peer_starvation")
    _write(
        cycle / "summary.json",
        {
            "cycle": 3,
            "profile": "geth_peer_starvation",
            "stage": "completed",
            "status": "completed",
            "decision_type": "restart_systemd_service",
        },
    )
    _write(
        cycle / "signal_payload.json",
        {
            "signal_type": "otel_metric_regression",
            "signal_id": "sig_geth_test",
            "environment": "testnet",
            "service": "geth-rpc-01",
            "metric_regression": {"metric_name": "geth.peer_count", "observed_value": 1.0},
            "related_context": {"node_kind": "geth", "host": "geth-rpc-01", "systemd_service": "geth.service"},
        },
    )

    row = build_incident_corpus_row(cycle)

    assert row["source"]["collector"] == "geth_internal_loop"
    assert row["target_class"] == "ethereum_execution_client"
    assert row["environment"] == "testnet"
    assert "geth" in row["labels"]["coverage"]


def test_kubernetes_signal_exports_as_kubernetes_corpus_row(tmp_path: Path) -> None:
    cycle = _cycle_dir(tmp_path, "000006_kubernetes_crash_loop")
    _write(
        cycle / "summary.json",
        {
            "cycle": 6,
            "profile": "kubernetes_crash_loop",
            "stage": "evaluation_ready",
            "status": "policy_held",
            "decision_type": "rollback_deployment",
        },
    )
    _write(
        cycle / "signal_payload.json",
        {
            "signal_type": "kubernetes_deployment_issue",
            "signal_id": "sig_k8s_test",
            "environment": "development",
            "service": "semantic-search",
            "namespace": "search",
            "deployment": {"name": "semantic-search", "rollout_status": "degraded"},
            "related_context": {"kube_context": "k3d-mesh-e2e"},
        },
    )

    row = build_incident_corpus_row(cycle)

    assert row["source"]["collector"] == "kubernetes_live_loop"
    assert row["target_class"] == "kubernetes_service"
    assert row["environment"] == "development"
    assert "kubernetes_service" in row["labels"]["coverage"]


def test_lighthouse_validator_signal_exports_explicit_coverage(tmp_path: Path) -> None:
    cycle = _cycle_dir(tmp_path, "000007_lighthouse_missed_attestations")
    _write(
        cycle / "summary.json",
        {
            "cycle": 7,
            "profile": "lighthouse_missed_attestations",
            "stage": "evaluation_ready",
            "status": "policy_held",
            "decision_type": "escalate",
        },
    )
    _write(
        cycle / "signal_payload.json",
        {
            "signal_type": "otel_metric_regression",
            "signal_id": "sig_lighthouse_validator_test",
            "environment": "testnet",
            "service": "lighthouse-validator-01",
            "component_kind": "lighthouse",
            "role": "validator",
            "metric_regression": {"metric_name": "validator.missed_attestations", "observed_value": 2.0},
            "related_context": {"component_kind": "lighthouse"},
        },
    )

    row = build_incident_corpus_row(cycle)

    assert row["source"]["collector"] == "consensus_validator_internal_loop"
    assert row["target_class"] == "ethereum_consensus_and_validator"
    assert row["labels"]["coverage"] == ("lighthouse", "validator")


def test_rpc_gateway_indexer_signal_exports_explicit_coverage(tmp_path: Path) -> None:
    cycle = _cycle_dir(tmp_path, "000008_rpc_gateway_indexing_lag")
    _write(
        cycle / "summary.json",
        {
            "cycle": 8,
            "profile": "rpc_gateway_indexing_lag",
            "stage": "evaluation_ready",
            "status": "policy_held",
            "decision_type": "escalate",
        },
    )
    _write(
        cycle / "signal_payload.json",
        {
            "signal_type": "otel_metric_regression",
            "signal_id": "sig_rpc_indexer_test",
            "environment": "development",
            "service": "rpc-indexer-gateway",
            "component_kind": "rpc_gateway",
            "metric_regression": {"metric_name": "indexer.indexing_lag", "observed_value": 120.0},
            "related_context": {"component_kind": "indexer"},
        },
    )

    row = build_incident_corpus_row(cycle)

    assert row["source"]["collector"] == "rpc_indexer_internal_loop"
    assert row["target_class"] == "rpc_gateway_and_indexer"
    assert row["labels"]["coverage"] == ("indexer", "rpc_gateway")


def test_session_report_surfaces_repeated_promotion_patterns(tmp_path: Path) -> None:
    first = _cycle_dir(tmp_path, "000001_peer_starvation_restart")
    second = _cycle_dir(tmp_path, "000002_peer_starvation_restart")
    for cycle, run_id in ((first, "run_success_1"), (second, "run_success_2")):
        _write(
            cycle / "summary.json",
            {
                "profile": "peer_starvation_restart",
                "run_id": run_id,
                "stage": "completed",
                "status": "completed",
                "decision_type": "restart_systemd_service",
                "evaluation_recommendation": "execute",
                "execution_status": "succeeded",
                "feedback_outcome": "successful",
            },
        )
        _write(cycle / "signal_payload.json", _reth_signal(error_signatures=["peer_starvation"], peer_count=1))
        _write(
            cycle / "run_final.json",
            {
                "run_id": run_id,
                "stage": "completed",
                "artifacts": {
                    "decision": {"decision_type": "restart_systemd_service", "confidence": 0.9},
                    "evaluation": {"final_recommendation": "execute", "passed": True},
                    "execution": {"status": "succeeded"},
                    "feedback": {"outcome": "successful"},
                },
            },
        )
        _write(cycle / "scenario_analysis.json", {"confidence": 0.9, "risk_level": "medium"})

    result = write_session_corpus(tmp_path)
    report = json.loads(result.report_path.read_text(encoding="utf-8"))

    key = "ethereum_execution_client:peer_starvation_restart:restart_systemd_service"
    assert report["promotion_candidate_count"] == 2
    assert report["promotion_patterns"][key] == 2
    assert report["repeated_promotion_patterns"][key] == 2


def test_write_session_corpus_emits_jsonl_and_report(tmp_path: Path) -> None:
    first = _cycle_dir(tmp_path, "000000_healthy_baseline")
    _write(first / "summary.json", {"cycle": 0, "profile": "healthy_baseline", "stage": "no_trigger", "status": "completed"})
    _write(first / "signal_payload.json", _reth_signal())

    second = _cycle_dir(tmp_path, "000004_signal_unavailable")
    _write(second / "summary.json", {"cycle": 4, "profile": "signal_unavailable", "stage": "signal_unavailable", "status": "skipped"})

    result = write_session_corpus(tmp_path)

    assert result.row_count == 2
    assert result.jsonl_path.is_file()
    assert result.report_path.is_file()
    lines = result.jsonl_path.read_text(encoding="utf-8").splitlines()
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert len(lines) == 2
    assert report["outcomes"]["false_positive"] == 1
    assert report["outcomes"]["skipped"] == 1
    assert report["environments"]["production"] == 1
    assert report["collectors"]["reth_kurtosis_full_loop"] == 1
    assert report["collectors"]["internal_corpus_loop"] == 1
    assert report["services"]["el-1-reth-lighthouse"] == 1
    assert report["target_classes"]["ethereum_execution_client"] == 1
    assert report["coverage"]["reth"] == 1
    assert (first / "corpus_row.json").is_file()
    assert (second / "corpus_row.json").is_file()


def test_outcome_classifier_covers_required_training_facts() -> None:
    assert _outcome(stage="no_trigger") == "false_positive"
    assert _outcome(status="policy_held", recommendation="human_review") == "human_hold"
    assert _outcome(execution_status="succeeded") == "executed"
    assert _outcome(execution_status="succeeded", feedback_outcome="successful") == "successful"
    assert _outcome(execution_status="failed") == "failed"
    assert _outcome(feedback_outcome="worsened") == "worsened"
    assert _outcome(decision_type="no_action", stage="completed") == "recovered_without_action"


def _outcome(
    *,
    stage: str = "completed",
    status: str = "completed",
    decision_type: str = "",
    recommendation: str = "",
    execution_status: str = "",
    feedback_outcome: str = "",
) -> str:
    return classify_training_outcome(
        summary={
            "stage": stage,
            "status": status,
            "decision_type": decision_type,
            "evaluation_recommendation": recommendation,
            "execution_status": execution_status,
            "feedback_outcome": feedback_outcome,
        },
        run={},
        decision={},
        evaluation={},
        execution={},
        feedback={},
    )


def _cycle_dir(session_dir: Path, name: str) -> Path:
    path = session_dir / name
    path.mkdir(parents=True)
    return path


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _reth_signal(
    *,
    error_signatures: list[str] | None = None,
    disk_used_pct: float = 30.0,
    peer_count: int = 3,
) -> dict[str, object]:
    return {
        "signal_type": "reth_node",
        "signal_id": "sig_reth_test",
        "environment": "production",
        "service": "el-1-reth-lighthouse",
        "node": {
            "name": "el-1-reth-lighthouse",
            "client_version": "reth/v1.9.3",
            "deployment_mode": "docker",
            "network": "kurtosis",
            "role": "full",
        },
        "execution": {"peer_count": peer_count, "head_block": 100, "syncing": False, "block_lag": 0},
        "storage": {"disk_used_pct": disk_used_pct},
        "logs": {"error_signatures": error_signatures or []},
        "resource_attributes": {"service.name": "el-1-reth-lighthouse", "deployment.environment": "production"},
        "related_context": {"kurtosis_enclave": "mesh-reth", "kurtosis_service": "el-1-reth-lighthouse"},
    }
