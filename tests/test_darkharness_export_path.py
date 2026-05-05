from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from control_plane_server import darkharness_packet_response
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


def _seed_run(coordinator: RunCoordinator, *, allowed: bool) -> str:
    decision = _decision("dec_darkharness", autonomy_tier="approval_required")
    evaluation = _evaluation(
        "eval_darkharness",
        final_recommendation="execute" if allowed else "reject",
        blocking_reasons=[] if allowed else ["production-impacting action requires operator approval"],
    )
    approvals = [{"event_id": "evt_approval", "operator_id": "operator.launcher"}] if allowed else []
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
            "approvals": approvals,
        },
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
