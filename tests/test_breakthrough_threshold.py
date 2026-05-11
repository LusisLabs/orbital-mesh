from shared.mesh_runtime.breakthrough import breakthrough_threshold_report, normalize_coverage_labels
from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase


def test_breakthrough_report_requires_all_threshold_dimensions() -> None:
    rows = [_row(index) for index in range(100)]
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

    report = breakthrough_threshold_report(rows)

    assert report["ready"] is True
    assert report["status"] == "breakthrough"
    assert report["criteria"]["incident_volume"]["passed"] is True
    assert report["criteria"]["measured_operational_reduction"]["observed"] == 1
    assert report["criteria"]["repeated_promotion"]["observed"] == 3
    assert report["criteria"]["cross_client_coverage"]["details"]["missing"] == ()
    assert report["criteria"]["retrieval_improved_live_decisions"]["observed"] == 1


def test_normalized_coverage_labels_prefer_explicit_labels_and_keep_legacy_fallback() -> None:
    explicit = _row(1)
    explicit["labels"]["coverage"] = ["RPC-Gateway", "indexer", "ignored"]
    legacy = _row(2)
    legacy["target_class"] = "kubernetes_service"
    legacy["service"] = "lighthouse-validator-k8s"

    assert normalize_coverage_labels(explicit) == {"rpc_gateway", "indexer"}
    assert {"kubernetes_service", "lighthouse", "validator"} <= normalize_coverage_labels(legacy)


def test_breakthrough_report_surfaces_missing_evidence() -> None:
    report = breakthrough_threshold_report([_row(1)])

    assert report["ready"] is False
    assert report["status"] == "below_threshold"
    assert report["criteria"]["incident_volume"]["passed"] is False
    assert "geth" in report["criteria"]["cross_client_coverage"]["details"]["missing"]
    assert report["criteria"]["retrieval_improved_live_decisions"]["passed"] is False


def test_breakthrough_report_excludes_public_bootstrap_rows() -> None:
    public_row = _row(1)
    public_row["source"]["kind"] = "public_dataset"
    public_row["training_fact"]["quality_measurements"] = {"unsafe_actions_prevented": 1}
    public_row["evidence_envelope"]["decision"] = {"retrieval_improved_decision": True}

    report = breakthrough_threshold_report([public_row])

    assert report["input_row_count"] == 1
    assert report["row_count"] == 0
    assert report["measured_delta_count"] == 0
    assert report["retrieval_improved_decision_count"] == 0


def test_measured_operational_reduction_requires_numeric_delta() -> None:
    boolean_row = _row(1)
    boolean_row["training_fact"]["quality_measurements"] = {"unsafe_actions_prevented": True}
    numeric_row = _row(2)
    numeric_row["training_fact"]["quality_measurements"] = {"unsafe_actions_prevented": 1}

    boolean_report = breakthrough_threshold_report([boolean_row])
    numeric_report = breakthrough_threshold_report([numeric_row])

    assert boolean_report["measured_delta_count"] == 0
    assert boolean_report["criteria"]["measured_operational_reduction"]["observed"] == 0
    assert numeric_report["measured_delta_count"] == 1
    assert numeric_report["criteria"]["measured_operational_reduction"]["observed"] == 1


def test_corpus_database_summary_includes_breakthrough_report(tmp_path) -> None:
    database = IncidentCorpusDatabase(tmp_path / "corpus.sqlite")
    rows = [_row(index) for index in range(3)]
    rows[0]["labels"]["coverage"] = ["reth"]
    rows[1]["environment"] = "development"
    rows[1]["target_class"] = "kubernetes_service"
    rows[1]["source"]["collector"] = "kubernetes_live_loop"
    for index in (0, 1):
        rows[index]["training_fact"].update(
            {
                "outcome": "successful",
                "decision_type": "restart_systemd_service",
                "promotion_candidate": True,
            }
        )
        rows[index]["source"]["profile"] = "peer_starvation_restart"
    database.import_rows(rows)

    summary = database.summary()

    assert summary["row_count"] == 3
    assert summary["environments"] == {"development": 1, "production": 2}
    assert summary["source_kinds"] == {"internal_corpus": 3}
    assert summary["target_classes"]["kubernetes_service"] == 1
    assert summary["collectors"]["kubernetes_live_loop"] == 1
    assert summary["coverage"]["reth"] == 1
    assert summary["promotion_patterns"]["ethereum_execution_client:peer_starvation_restart:restart_systemd_service"] == 1
    assert summary["promotion_patterns"]["kubernetes_service:peer_starvation_restart:restart_systemd_service"] == 1
    assert summary["breakthrough"]["schema_version"] == "mesh.breakthrough_threshold_report.v1"
    assert summary["breakthrough"]["row_count"] == 3


def _row(index: int) -> dict[str, object]:
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
