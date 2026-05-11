from __future__ import annotations

import json
import tempfile
import unittest
from importlib import util
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/generate_pilot_breakthrough_packet.py"
SPEC = util.spec_from_file_location("generate_pilot_breakthrough_packet", SCRIPT_PATH)
assert SPEC is not None
generate_pilot_breakthrough_packet = util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generate_pilot_breakthrough_packet)

HEAD = "a" * 40
DIGEST = f"sha256:{'b' * 64}"
RUN_ID = "run_20260508T033245_ad9bd5ac"


class PilotBreakthroughPacketTests(unittest.TestCase):
    def test_writes_reproducible_packet_for_bounded_closed_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proof_path = _write_json(tmp_path / "proof.json", _proof(HEAD))
            chaos_path = _write_json(tmp_path / "chaos-summary.json", _chaos_summary(tmp_path))
            node_path = _write_json(tmp_path / "node-summary.json", _node_summary(tmp_path))
            output_dir = tmp_path / "packet"

            result = generate_pilot_breakthrough_packet.generate_pilot_breakthrough_packet(
                repo_root=REPO_ROOT,
                output_dir=output_dir,
                base_url="http://mesh.local",
                timeout_seconds=1.0,
                run_id=RUN_ID,
                proof_bundle=proof_path,
                chaos_summary=chaos_path,
                node_summary=node_path,
                requester=_requester(),
                current_head=HEAD,
            )

            self.assertEqual(result["status"], "pass", result)
            packet = _load_json(output_dir / "packet.json")
            self.assertEqual(packet["status"], "pass")
            self.assertTrue(packet["checks"]["runtime_build_commit_matches_head"])
            self.assertTrue(packet["checks"]["closed_loop_action_class"])
            self.assertEqual(packet["product_claim"], generate_pilot_breakthrough_packet.PRODUCT_CLAIM)
            self.assertEqual(packet["expansion_order"], generate_pilot_breakthrough_packet.EXPANSION_ORDER)
            self.assertEqual(len(packet["evidence_files"]), 6)
            self.assertIn("--timeout-seconds 1", packet["commands"]["pilot_clearance"])
            self.assertIn(f"--expected-head {HEAD}", packet["commands"]["pilot_clearance"])
            self.assertIn("--timeout-seconds 1", packet["commands"]["packet_generation"])

            run_summary = _load_json(output_dir / "closed-loop-run-summary.json")
            self.assertEqual(run_summary["run_id"], RUN_ID)
            self.assertEqual(run_summary["decision"]["execution_plan"]["parameters"]["namespace"], "search")
            self.assertEqual(run_summary["feedback"]["metric_comparison"]["rollout_status"], "healthy")

    def test_blocks_when_release_bound_runtime_does_not_match_repo_head(self) -> None:
        release_commit = "c" * 40
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proof_path = _write_json(tmp_path / "proof.json", _proof(HEAD))
            chaos_path = _write_json(tmp_path / "chaos-summary.json", _chaos_summary(tmp_path))
            node_path = _write_json(tmp_path / "node-summary.json", _node_summary(tmp_path))

            result = generate_pilot_breakthrough_packet.generate_pilot_breakthrough_packet(
                repo_root=REPO_ROOT,
                output_dir=tmp_path / "packet",
                base_url="http://mesh.local",
                timeout_seconds=1.0,
                run_id=RUN_ID,
                proof_bundle=proof_path,
                chaos_summary=chaos_path,
                node_summary=node_path,
                requester=_requester(commit=release_commit),
                current_head=HEAD,
            )

            self.assertEqual(result["status"], "blocked", result)
            self.assertIn("runtime_build_commit_matches_head", result["missing"])

    def test_can_generate_historical_release_bound_packet_when_explicitly_allowed(self) -> None:
        release_commit = "c" * 40
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proof_path = _write_json(tmp_path / "proof.json", _proof(HEAD))
            chaos_path = _write_json(tmp_path / "chaos-summary.json", _chaos_summary(tmp_path))
            node_path = _write_json(tmp_path / "node-summary.json", _node_summary(tmp_path))

            result = generate_pilot_breakthrough_packet.generate_pilot_breakthrough_packet(
                repo_root=REPO_ROOT,
                output_dir=tmp_path / "packet",
                base_url="http://mesh.local",
                timeout_seconds=1.0,
                run_id=RUN_ID,
                proof_bundle=proof_path,
                chaos_summary=chaos_path,
                node_summary=node_path,
                require_runtime_head=False,
                requester=_requester(commit=release_commit),
                current_head=HEAD,
            )

            self.assertEqual(result["status"], "pass", result)


def _requester(*, commit: str = HEAD) -> Any:
    responses = {
        "/api/health": {
            "status": "ok",
            "timestamp": "2026-05-08T07:30:00Z",
            "commit": commit,
            "image_digest": DIGEST,
        },
        "/api/readiness": {
            "profile": "pilot",
            "status": "ready",
            "checked_at": "2026-05-08T07:30:01Z",
            "blockers": [],
        },
        "/api/pilot/go-no-go": _go_no_go(commit),
        f"/api/runs/{RUN_ID}/export": _run_export(),
    }

    def request(url: str, timeout_seconds: float, headers: dict[str, str] | None) -> dict[str, Any]:
        del timeout_seconds
        if url.endswith(f"/api/runs/{RUN_ID}/export"):
            assert headers is not None
            assert headers["X-Mesh-Operator"] == "mesh-compose-chaos"
            return responses[f"/api/runs/{RUN_ID}/export"]
        for suffix, payload in responses.items():
            if url.endswith(suffix):
                return payload
        raise AssertionError(f"unexpected URL: {url}")

    return request


def _proof(commit: str) -> dict[str, Any]:
    return {
        "schema_version": "mesh.breakthrough_evidence_bundle.v1",
        "bundle_sha256": "d" * 64,
        "git": {"commit": commit, "dirty": False},
        "breakthrough_proof": {"ready": True, "status": "regression_protected_breakthrough"},
        "replay": {"passed": True, "reports": [{"kind": "compose_chaos_score_replay", "passed": True}]},
        "summary_checks": [{"kind": "compose", "ready": True, "coverage_checks": {}}],
        "validation_commands": [{"command": ["python3", "-m", "unittest"], "passed": True, "exit_code": 0}],
    }


def _chaos_summary(tmp_path: Path) -> dict[str, Any]:
    events_path = tmp_path / "chaos-events.jsonl"
    events_path.write_text(json.dumps({"event": "score"}) + "\n", encoding="utf-8")
    return {
        "schema_version": "mesh.compose_chaos_summary.v1",
        "generated_at": "2026-05-08T07:00:00Z",
        "events_path": str(events_path),
        "experiments_total": 1,
        "experiments_passed": 1,
        "metrics": {"correct_decision_rate": 1.0},
        "breakthrough_probe": {"ready": True, "status": "breakthrough_signal"},
        "capabilities": {
            "known_axes": ["choose_rollback"],
            "passed_axes": ["choose_rollback"],
            "missing_axes": [],
            "failed_or_unproven_axes": [],
        },
        "substrate_coverage": {"container": {"passed": 1}},
        "multi_fault_coverage": {"missing_experiments": []},
    }


def _node_summary(tmp_path: Path) -> dict[str, Any]:
    events_path = tmp_path / "node-events.jsonl"
    events_path.write_text(json.dumps({"event": "score"}) + "\n", encoding="utf-8")
    return {
        "schema_version": "mesh.production_node_breakthrough_summary.v1",
        "generated_at": "2026-05-08T07:00:00Z",
        "events_path": str(events_path),
        "experiments_total": 1,
        "experiments_passed": 1,
        "metrics": {"correct_decision_rate": 1.0},
        "breakthrough_probe": {"ready": True, "status": "breakthrough_signal"},
        "capabilities": {
            "known_axes": ["classify_restartable_stateless_service"],
            "passed_axes": ["classify_restartable_stateless_service"],
            "missing_axes": [],
            "failed_or_unproven_axes": [],
        },
    }


def _go_no_go(commit: str) -> dict[str, Any]:
    return {
        "packet_version": "pilot.go_no_go.v1",
        "status": "go",
        "generated_at": "2026-05-08T07:30:02Z",
        "missing_evidence": [],
        "checks": {"readiness_green": True, "release_provenance_complete": True},
        "release_provenance": {
            "schema_version": "mesh.release_provenance.v1",
            "status": "complete",
            "missing": [],
            "checks": {"git_commit": True, "image_digest": True, "ci_attestation": True},
            "packet_sha256": "e" * 64,
            "git": {"commit": commit},
            "image": {"digest": DIGEST},
        },
    }


def _run_export() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "status": "completed",
        "stage": "completed",
        "scenario_key": "live_kubernetes:search/semantic-search",
        "event_count": 59,
        "events_truncated": False,
        "latest_event_id": "evt_0059_22b6d19c",
        "latest_event_sequence": 59,
        "latest_merkle_root": "f" * 64,
        "merkle": {"run_id": RUN_ID, "leaf_count": 59, "root_hash": "f" * 64},
        "artifacts": {
            "trigger": {
                "trigger_id": "trg_sig_k8s_search_semantic-search",
                "trigger_type": "kubernetes_deployment_unhealthy",
                "service": "semantic-search",
            },
            "run_admission": {
                "schema_version": "mesh.run_admission.v1",
                "decision": "admitted",
                "blockers": [],
                "target_lock_key": "unknown:local:semantic-search",
            },
            "operator": {"operator_id": "local-admin", "roles": ["admin", "approver", "launcher"]},
            "decision": {
                "decision_id": "dec_1",
                "decision_type": "rollback_deployment",
                "autonomy_tier": "escalated",
                "confidence": 0.86,
                "execution_plan": {
                    "system": "kubernetes_service",
                    "action": "rollback_deployment",
                    "parameters": {
                        "cluster": "mesh-compose",
                        "kube_context": "mesh-compose",
                        "namespace": "search",
                        "deployment_name": "semantic-search",
                        "revision": "2",
                    },
                },
                "risk": {"level": "medium"},
            },
            "execution": {
                "execution_id": "exe_1",
                "status": "succeeded",
                "executor": "native",
                "applied_action": {"action": "rollback_deployment"},
                "idempotency_key": "dec_1:rollback_deployment",
                "failure": None,
            },
            "feedback": {
                "feedback_id": "fb_1",
                "outcome": "successful",
                "metric_comparison": {"desired_replicas": 3, "ready_replicas": 3, "rollout_status": "healthy"},
                "prediction_accuracy": {"observed_time_to_effect": "immediate"},
                "recommended_follow_up": "record_rollout_recovery",
            },
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


if __name__ == "__main__":
    unittest.main()
