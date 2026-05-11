from pathlib import Path

from scripts.verify_corpus_breakthrough import verify_corpus_breakthrough
from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase
from shared.mesh_runtime.monitoring_corpus import build_public_monitoring_corpus_rows


def test_corpus_breakthrough_verifier_fails_missing_database_without_creating_it(tmp_path: Path) -> None:
    database_path = tmp_path / "missing" / "incident_corpus.sqlite"

    payload = verify_corpus_breakthrough(database_path)

    assert payload["status"] == "fail"
    assert payload["missing"] == ["corpus_database"]
    assert payload["errors"] == ["database_missing"]
    assert database_path.exists() is False


def test_corpus_breakthrough_verifier_excludes_public_bootstrap_rows(tmp_path: Path) -> None:
    database = IncidentCorpusDatabase(tmp_path / "corpus" / "incident_corpus.sqlite")
    database.import_rows(build_public_monitoring_corpus_rows())

    payload = verify_corpus_breakthrough(database.path)

    assert payload["status"] == "fail"
    assert payload["ready"] is False
    assert payload["breakthrough"]["input_row_count"] == 13
    assert payload["breakthrough"]["row_count"] == 0
    assert "incident_volume" in payload["missing"]


def test_corpus_breakthrough_verifier_passes_when_all_measured_internal_gates_pass(tmp_path: Path) -> None:
    database = IncidentCorpusDatabase(tmp_path / "corpus" / "incident_corpus.sqlite")
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
    database.import_rows(rows)

    payload = verify_corpus_breakthrough(database.path)

    assert payload["status"] == "pass"
    assert payload["ready"] is True
    assert payload["missing"] == []
    assert all(item["status"] == "pass" for item in payload["checklist"])


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
