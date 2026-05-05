from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from control_plane_server import darkharness_checkpoint_packet_response, darkharness_packet_response
from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig, load_fixture, validate_payload

from tests.test_perennial_materialization import _decision, _evaluation, _scenario_analysis


def _config(tmp: str, **overrides: Any) -> RuntimeConfig:
    values = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
        "server_host": "127.0.0.1",
        "server_port": 0,
        "vault_mirror_mode": "sync",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


class DarkharnessExportPathTests(unittest.TestCase):
    def test_coordinator_builds_schema_valid_packet_for_allowed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                run_id = _seed_run(coordinator, allowed=True)
                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                self.assertEqual(packet["packet"], "darkharness.pilot_packet.v1")
                self.assertEqual(packet["boundaries"]["raw_reservoir_egress"], "deny")
                self.assertTrue(packet["boundaries"]["production_actions_approval_required"])
                self.assertEqual(len(packet["implemented_evidence"]["allowed_action_proofs"]), 1)
                validate_payload("perennial/darkharness-pilot-packet.schema.json", packet)
            finally:
                coordinator.stop_background_workers()

    def test_coordinator_represents_denied_action_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                run_id = _seed_run(coordinator, allowed=False)
                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                self.assertEqual(len(packet["implemented_evidence"]["denied_action_proofs"]), 1)
                [commit] = packet["perennial_records"]["governance_commits"]
                self.assertEqual(commit["outcome"]["gate_result"], "denied")
                self.assertEqual(packet["boundaries"]["external_model_calls"], "deny")
            finally:
                coordinator.stop_background_workers()

    def test_missing_required_evidence_blocks_export_without_fabricating_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                session = coordinator.state_store.create_run_session(
                    goal_id=None,
                    scenario_key="checkout_latency",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="pilot",
                    orchestration_mode="shadow",
                    artifacts={},
                )

                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(session.run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                self.assertEqual(packet["status"], "blocked")
                self.assertIn("decision_record_present", packet["missing_evidence"])
                self.assertIn("evaluation_record_present", packet["missing_evidence"])
                self.assertIn("merkle_proof_valid", packet["missing_evidence"])
                self.assertNotIn("perennial_records", packet)
            finally:
                coordinator.stop_background_workers()

    def test_endpoint_response_helper_returns_packet_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                run_id = _seed_run(coordinator, allowed=True)
                before_session = coordinator.state_store.get_run_session(run_id)
                self.assertIsNotNone(before_session)
                assert before_session is not None
                before_artifacts = json.loads(json.dumps(before_session.artifacts, sort_keys=True))
                before_event_count = len(coordinator.state_store.list_run_events(run_id))

                with _patched_pilot_inputs(coordinator):
                    payload, status = darkharness_packet_response(coordinator, run_id)

                after_session = coordinator.state_store.get_run_session(run_id)
                self.assertIsNotNone(after_session)
                assert after_session is not None
                after_event_count = len(coordinator.state_store.list_run_events(run_id))

                self.assertEqual(status.value, 200)
                self.assertEqual(payload["packet"], "darkharness.pilot_packet.v1")
                self.assertEqual(before_event_count, after_event_count)
                self.assertEqual(before_artifacts, json.loads(json.dumps(after_session.artifacts, sort_keys=True)))
                self.assertFalse((Path(tmp) / "run_exports" / f"{run_id}.json").exists())
            finally:
                coordinator.stop_background_workers()

    def test_endpoint_response_helper_returns_conflict_for_incomplete_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                session = coordinator.state_store.create_run_session(
                    goal_id=None,
                    scenario_key="checkout_latency",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="pilot",
                    orchestration_mode="shadow",
                    artifacts={},
                )

                with _patched_pilot_inputs(coordinator):
                    payload, status = darkharness_packet_response(coordinator, session.run_id)

                self.assertEqual(status.value, 409)
                self.assertEqual(payload["status"], "blocked")
                self.assertIn("decision_record_present", payload["missing_evidence"])
            finally:
                coordinator.stop_background_workers()

    def test_coordinator_uses_configured_darkharness_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _write_registry(tmp)
            coordinator = RunCoordinator(_config(tmp, darkharness_registry_path=str(registry_path)))
            try:
                run_id = _seed_run(coordinator, allowed=True)
                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                self.assertEqual(packet["customer_boundary"], "customer-b-onprem")
                self.assertEqual(packet["perennial_records"]["sensitive_reservoirs"][0]["reservoir_id"], "reservoir_customer_b_ops")
                [record] = packet["perennial_records"]["agent_action_records"]
                self.assertEqual(record["boundary"]["tenant_id"], "customer-b")
                self.assertEqual(record["boundary"]["reservoir_refs"], ["reservoir_customer_b_ops"])
                self.assertEqual(record["governance"]["operator_authority_refs"], ["operator-approval://evt_approval"])
            finally:
                coordinator.stop_background_workers()

    def test_invalid_configured_registry_blocks_packet_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _write_registry(tmp, raw_reservoir_egress="approved_exception")
            coordinator = RunCoordinator(_config(tmp, darkharness_registry_path=str(registry_path)))
            try:
                run_id = _seed_run(coordinator, allowed=True)
                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                self.assertEqual(packet["status"], "blocked")
                self.assertTrue(any(item.startswith("registry_invalid:") for item in packet["missing_evidence"]))
                self.assertNotIn("perennial_records", packet)
            finally:
                coordinator.stop_background_workers()

    def test_policy_blocks_allowed_production_action_without_operator_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                run_id = _seed_run(coordinator, allowed=True, approvals=[])
                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                self.assertEqual(packet["status"], "blocked")
                self.assertIn(
                    "policy_violation:production_action_has_operator_approval",
                    packet["missing_evidence"],
                )
                self.assertFalse(packet["checks"]["production_action_has_operator_approval"])
                self.assertNotIn("perennial_records", packet)
            finally:
                coordinator.stop_background_workers()

    def test_configured_signing_key_adds_signature_proof_to_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    darkharness_signing_key="test-darkharness-signing-secret",
                    darkharness_signing_key_id="test-key",
                )
            )
            try:
                run_id = _seed_run(coordinator, allowed=True)
                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                [proof_envelope] = packet["perennial_records"]["proof_envelopes"]
                signature = proof_envelope["implemented_proofs"]["signature"]
                [governance_commit] = packet["perennial_records"]["governance_commits"]
                self.assertEqual(signature["algorithm"], "hmac-sha256")
                self.assertEqual(signature["key_id"], "test-key")
                self.assertEqual(signature["status"], "verified")
                self.assertEqual(
                    governance_commit["proof"]["signature_ref"],
                    f"signature://test-key/{signature['payload_sha256']}",
                )
            finally:
                coordinator.stop_background_workers()

    def test_mesh_brain_artifacts_become_perennial_action_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                run_id = _seed_run(coordinator, allowed=True)
                _attach_mesh_brain_artifacts(coordinator, run_id)

                with _patched_pilot_inputs(coordinator):
                    packet = coordinator.build_darkharness_packet(run_id)

                self.assertIsNotNone(packet)
                assert packet is not None
                action_records = packet["perennial_records"]["agent_action_records"]
                action_types = {record["action"]["action_type"] for record in action_records}
                self.assertIn("restart_deployment", action_types)
                self.assertIn("mesh_brain_dataset_provenance", action_types)
                self.assertIn("mesh_brain_training_job", action_types)
                self.assertIn("mesh_brain_eval_score", action_types)
                self.assertIn("mesh_brain_serving_smoke", action_types)
                self.assertIn("mesh_brain_model_kernel_proof", action_types)
                self.assertIn("mesh_brain_quality_update", action_types)
                mesh_records = [
                    record
                    for record in action_records
                    if record["action"]["action_type"].startswith("mesh_brain_")
                ]
                self.assertTrue(mesh_records)
                self.assertTrue(all(record["action"]["production_impact"] == "none" for record in mesh_records))
                restart_record = next(
                    record
                    for record in action_records
                    if record["action"]["action_type"] == "restart_deployment"
                )
                self.assertTrue(
                    all(
                        record["boundary"]["tenant_id"] == restart_record["boundary"]["tenant_id"]
                        for record in mesh_records
                    )
                )
                [governance_commit] = packet["perennial_records"]["governance_commits"]
                primary_record = next(
                    record
                    for record in action_records
                    if record["action_record_id"] == governance_commit["subject"]["action_record_id"]
                )
                self.assertEqual(primary_record["action"]["action_type"], "restart_deployment")
                self.assertIn(
                    "mesh_brain://model-kernel/mb_kernel_1",
                    governance_commit["inputs"]["evidence_refs"],
                )
                self.assertIn(
                    "mesh_brain://live-serving/mb_live_1",
                    governance_commit["inputs"]["evidence_refs"],
                )
                validate_payload("perennial/darkharness-pilot-packet.schema.json", packet)
            finally:
                coordinator.stop_background_workers()

    def test_checkpoint_packet_combines_allowed_denied_and_rollback_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                allowed_run_id = _seed_run(coordinator, allowed=True, pilot_go_no_go_evidence=True)
                denied_run_id = _seed_run(coordinator, allowed=False)
                rollback_run_id = _record_mesh_brain_checkpoint_evidence(coordinator)

                with patch.object(coordinator, "build_readiness", return_value={"status": "ready", "profile": "pilot"}):
                    packet = coordinator.build_darkharness_pilot_checkpoint_packet()

                self.assertEqual(packet["packet"], "darkharness.pilot_packet.v1")
                self.assertEqual(packet["implemented_evidence"]["go_no_go"]["status"], "go")
                exported_run_ids = {
                    export["run_id"]
                    for export in packet["implemented_evidence"]["run_exports"]
                }
                self.assertIn(allowed_run_id, exported_run_ids)
                self.assertIn(denied_run_id, exported_run_ids)
                self.assertIn(rollback_run_id, exported_run_ids)
                self.assertEqual(len(packet["implemented_evidence"]["allowed_action_proofs"]), 1)
                self.assertEqual(len(packet["implemented_evidence"]["denied_action_proofs"]), 1)
                self.assertGreaterEqual(len(packet["implemented_evidence"]["merkle_proofs"]), 3)
                action_types = {
                    record["action"]["action_type"]
                    for record in packet["perennial_records"]["agent_action_records"]
                }
                self.assertIn("restart_deployment", action_types)
                self.assertIn("mesh_brain_model_kernel_proof", action_types)
                self.assertIn("mesh_brain_serving_smoke", action_types)
                self.assertIn("mesh_brain_quality_update", action_types)
                self.assertIn("multi_run_checkpoint_export", packet["claim_boundary"]["implemented"])
                self.assertIn("rollback_drill_proof", packet["claim_boundary"]["implemented"])
                validate_payload("perennial/darkharness-pilot-packet.schema.json", packet)
            finally:
                coordinator.stop_background_workers()

    def test_checkpoint_endpoint_helper_returns_conflict_until_go_no_go_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                with patch.object(coordinator, "build_readiness", return_value={"status": "blocked", "profile": "pilot"}):
                    payload, status = darkharness_checkpoint_packet_response(coordinator)

                self.assertEqual(status.value, 409)
                self.assertEqual(payload["status"], "blocked")
                self.assertIn("readiness_green", payload["missing_evidence"])
            finally:
                coordinator.stop_background_workers()


def _seed_run(
    coordinator: RunCoordinator,
    *,
    allowed: bool,
    approvals: list[dict[str, Any]] | None = None,
    pilot_go_no_go_evidence: bool = False,
) -> str:
    decision = _decision("dec_darkharness", autonomy_tier="approval_required")
    evaluation = _evaluation(
        "eval_darkharness",
        final_recommendation="execute" if allowed else "reject",
        blocking_reasons=[] if allowed else ["production-impacting action requires operator approval"],
    )
    approval_records = approvals if approvals is not None else ([{"event_id": "evt_approval", "operator_id": "operator.launcher"}] if allowed else [])
    session = coordinator.state_store.create_run_session(
        goal_id=None,
        scenario_key="checkout_latency",
        steering_mode="approval_gate",
        auto_mode=False,
        pause_points=["before_execute"],
        evaluation_mode="pilot",
        orchestration_mode="shadow",
        artifacts={
            "decision": decision,
            "evaluation": evaluation,
            "scenario_analysis": _scenario_analysis(),
            "approvals": approval_records,
            **({"execution": {"external_refs": {"live_execution": True}}} if pilot_go_no_go_evidence else {}),
        },
    )
    if pilot_go_no_go_evidence:
        coordinator.state_store.append_run_event(
            session.run_id,
            stage="awaiting_operator",
            event_type="steering_command",
            payload={"command_type": "approve", "operator": {"operator_id": "operator.launcher"}},
            summary={"status": "accepted"},
            integration_name="control_plane",
            status="accepted",
        )
    coordinator.state_store.append_run_event(
        session.run_id,
        stage="executing",
        event_type="execution_recorded" if allowed else "steering_rejected",
        payload={
            "operator_id": "operator.launcher" if allowed else None,
            "action_type": "restart_deployment",
            "service": "checkout-api",
            "namespace": "payments-pilot",
            "resource_ref": "deployment/checkout-api",
            "production_impact": "possible" if allowed else "direct",
            "denial_reasons": [] if allowed else ["production-impacting action requires operator approval"],
        },
        summary={"status": "executed" if allowed else "denied"},
        integration_name="control_plane",
        status="executed" if allowed else "denied",
    )
    return str(session.run_id)


def _record_mesh_brain_checkpoint_evidence(coordinator: RunCoordinator) -> str:
    _record_completed_probe(
        coordinator,
        "mesh_brain_model_kernel_probe",
        {
            "mesh_brain_model_kernel_run_record": {
                "run_id": "mb_kernel_checkpoint",
                "status": "completed",
                "final_release_decision": "pass",
                "artifact_refs": _hashed_refs("mesh_brain_model_kernel_probe_summary"),
            }
        },
    )
    _record_completed_probe(
        coordinator,
        "mesh_brain_live_serving_smoke",
        {
            "mesh_brain_live_serving_run_record": {
                "run_id": "mb_live_checkpoint",
                "tenant_id": "tenant_a",
                "status": "completed",
                "final_release_decision": "canary",
                "artifact_refs": _hashed_refs("mesh_brain_live_serving_summary"),
                "summary_metrics": {
                    "task_type": "crops",
                    "live_smoke_gate": "pass",
                    "live_response_eval": "pass",
                    "live_judge_eval": "pass",
                },
            }
        },
    )
    return _record_completed_probe(
        coordinator,
        "mesh_brain_rollback_drill",
        {
            "mesh_brain_rollback_drill_run_record": {
                "run_id": "mb_rollback_checkpoint",
                "status": "completed",
                "final_release_decision": "pass",
                "artifact_refs": _hashed_refs("mesh_brain_rollback_drill_summary"),
                "summary_metrics": {"restored_previous_artifact": True},
            }
        },
    )


def _record_completed_probe(coordinator: RunCoordinator, scenario_key: str, artifacts: dict[str, Any]) -> str:
    session = coordinator.state_store.create_run_session(
        goal_id=None,
        scenario_key=scenario_key,
        steering_mode="system_probe",
        auto_mode=False,
        pause_points=[],
        evaluation_mode=scenario_key,
        orchestration_mode="native",
        artifacts=artifacts,
    )
    coordinator.state_store.append_run_event(
        session.run_id,
        stage="completed",
        event_type="run_completed",
        payload={"status": "completed", "scenario_key": scenario_key},
        summary={"status": "completed"},
        integration_name="mesh_brain",
        status="completed",
    )
    current = coordinator.state_store.get_run_session(session.run_id)
    assert current is not None
    current.stage = "completed"
    current.status = "completed"
    coordinator.state_store.save_run_session(current)
    return str(session.run_id)


def _hashed_refs(key: str) -> dict[str, dict[str, str]]:
    return {
        key: {
            "artifact_key": key,
            "path": f"/tmp/{key}.json",
            "sha256": "a" * 64,
            "content_type": "application/json",
        }
    }


def _attach_mesh_brain_artifacts(coordinator: RunCoordinator, run_id: str) -> None:
    coordinator._set_artifact(  # noqa: SLF001
        run_id,
        "mesh_brain_run_record",
        {
            "run_id": "mb_mvp_1",
            "tenant_id": "customer-a",
            "status": "completed",
            "artifact_refs": {
                "mesh_brain_dataset_manifest": {
                    "artifact_key": "mesh_brain_dataset_manifest",
                    "path": "/tmp/mesh-brain/dataset_manifest.json",
                },
                "mesh_brain_training_job": {
                    "artifact_key": "mesh_brain_training_job",
                    "path": "/tmp/mesh-brain/training_job.json",
                },
                "mesh_brain_eval_job": {
                    "artifact_key": "mesh_brain_eval_job",
                    "path": "/tmp/mesh-brain/eval_job.json",
                },
            },
            "summary_metrics": {
                "golden_eval_case_count": 3,
                "serving_backend": "deterministic",
            },
            "final_release_decision": "canary",
        },
    )
    coordinator._set_artifact(  # noqa: SLF001
        run_id,
        "mesh_brain_model_kernel_run_record",
        {
            "run_id": "mb_kernel_1",
            "tenant_id": "mesh_system",
            "status": "completed",
            "artifact_refs": {
                "mesh_brain_model_kernel_gate": {
                    "artifact_key": "mesh_brain_model_kernel_gate",
                    "path": "/tmp/mesh-brain/model_kernel_gate.json",
                },
            },
            "final_release_decision": "pass",
        },
    )
    coordinator._set_artifact(  # noqa: SLF001
        run_id,
        "mesh_brain_live_serving_run_record",
        {
            "run_id": "mb_live_1",
            "tenant_id": "customer-a",
            "status": "completed",
            "artifact_refs": {
                "mesh_brain_live_serving_summary": {
                    "artifact_key": "mesh_brain_live_serving_summary",
                    "path": "/tmp/mesh-brain/live_serving_summary.json",
                },
            },
            "final_release_decision": "canary",
        },
    )
    coordinator._set_artifact(  # noqa: SLF001
        run_id,
        "mesh_brain_backend_matrix_record",
        {
            "run_id": "mb_matrix_1",
            "tenant_id": "customer-a",
            "status": "completed",
            "artifact_refs": {
                "mesh_brain_backend_matrix_results": {
                    "artifact_key": "mesh_brain_backend_matrix_results",
                    "path": "/tmp/mesh-brain/backend_matrix_results.json",
                },
                "mesh_brain_backend_matrix_summary": {
                    "artifact_key": "mesh_brain_backend_matrix_summary",
                    "path": "/tmp/mesh-brain/backend_matrix_summary.json",
                },
            },
            "summary_metrics": {
                "passed_count": 2,
                "blocked_count": 0,
            },
            "final_release_decision": "pass",
        },
    )


def _patched_pilot_inputs(coordinator: RunCoordinator) -> Any:
    return patch.multiple(
        coordinator,
        build_readiness=lambda: {"status": "ready", "profile": "pilot"},
        generate_pilot_go_no_go=lambda: {
            "packet_version": "pilot.go_no_go.v1",
            "status": "go",
            "final_release_decision": "pass",
            "postgres_restart_proof": None,
        },
    )


def _write_registry(tmp: str, *, raw_reservoir_egress: str = "deny") -> Path:
    fixture = load_fixture("perennial", "allowed_action.json")["contracts"]
    pilot_scope = json.loads(json.dumps(fixture["pilot_scope"]))
    reservoir = json.loads(json.dumps(fixture["sensitive_reservoir"]))
    pilot_scope["customer_boundary"] = "customer-b-onprem"
    pilot_scope["data_boundary"]["raw_reservoir_egress"] = raw_reservoir_egress
    reservoir["reservoir_id"] = "reservoir_customer_b_ops"
    reservoir["name"] = "Customer B operational evidence"
    path = Path(tmp) / "darkharness-registry.json"
    path.write_text(
        json.dumps(
            {
                "registry": "darkharness.registry.v1",
                "tenant_id": "customer-b",
                "pilot_scope": pilot_scope,
                "sensitive_reservoirs": [reservoir],
                "trust_ladder_ref": "trust://customer-b/checkout-api/pilot",
                "owner_registry_ref": "registry://owners/customer-b/checkout-api",
                "policy_refs": ["policy://darkharness/pilot/approval-required"],
            }
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
