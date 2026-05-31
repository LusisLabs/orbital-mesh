from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path

from shared.mesh_runtime import (
    Decision,
    RunEvent,
    Trigger,
    build_connector_certification_matrix,
    build_deployment_compatibility_matrix,
    build_ownership_boundary,
    build_policy_lifecycle_packet,
    build_run_admission,
    build_timeline_proof,
    evaluate_evidence_sufficiency,
    load_connector_certification_registry,
    load_deployment_compatibility_registry,
    load_fixture,
    load_ownership_registry,
    load_schema,
    validate_payload,
)


class ContractValidationTests(unittest.TestCase):
    def test_kubernetes_signal_schema_is_loadable(self) -> None:
        schema = load_schema("kubernetes-signal.schema.json")
        self.assertEqual(schema["title"], "KubernetesDeploymentSignal")

    def test_ownership_registry_schema_is_loadable(self) -> None:
        schema = load_schema("ownership-registry.schema.json")
        self.assertEqual(schema["title"], "OwnershipRegistry")

    def test_connector_certification_schema_is_loadable(self) -> None:
        schema = load_schema("connector-certification-matrix.schema.json")
        self.assertEqual(schema["title"], "ConnectorCertificationMatrix")

    def test_credential_egress_policy_schema_is_loadable(self) -> None:
        schema = load_schema("credential-egress-policy.schema.json")
        self.assertEqual(schema["title"], "Mesh credential egress policy")

    def test_local_centaur_credential_egress_policy_validates(self) -> None:
        payload = json.loads(Path("config/centaur-credential-egress.local.json").read_text(encoding="utf-8"))
        validate_payload("credential-egress-policy.schema.json", payload)

    def test_deployment_compatibility_schema_is_loadable(self) -> None:
        schema = load_schema("deployment-compatibility-matrix.schema.json")
        self.assertEqual(schema["title"], "DeploymentCompatibilityMatrix")

    def test_policy_lifecycle_schema_is_loadable(self) -> None:
        schema = load_schema("policy-lifecycle-packet.schema.json")
        self.assertEqual(schema["title"], "PolicyLifecyclePacket")

    def test_evidence_sufficiency_schema_is_loadable(self) -> None:
        schema = load_schema("evidence-sufficiency.schema.json")
        self.assertEqual(schema["title"], "EvidenceSufficiency")

    def test_timeline_proof_schema_is_loadable(self) -> None:
        schema = load_schema("timeline-proof.schema.json")
        self.assertEqual(schema["title"], "TimelineProof")

    def test_run_admission_schema_is_loadable(self) -> None:
        schema = load_schema("run-admission.schema.json")
        self.assertEqual(schema["title"], "RunAdmission")

    def test_agent_attempt_thread_schema_is_loadable(self) -> None:
        schema = load_schema("agent-attempt-thread.schema.json")
        self.assertEqual(schema["title"], "Mesh agent attempt thread")

    def test_trigger_schema_is_loadable(self) -> None:
        schema = load_schema("trigger.schema.json")
        self.assertEqual(schema["title"], "Trigger")

    def test_trigger_payload_validates(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        payload = {
            "trigger_id": "trg_test",
            "trigger_type": "feature_flag_performance_regression",
            "triggered_at": signal["observed_at"],
            "environment": signal["environment"],
            "service": signal["service"],
            "endpoint": signal["endpoint"],
            "flag_key": signal["feature_flag"]["flag_key"],
            "current_rollout_pct": signal["feature_flag"]["current_rollout_pct"],
            "comparison_window": signal["comparison_window"],
            "segment": signal["segment"],
            "metrics": {
                "baseline_p95_latency_ms": signal["request_telemetry"]["baseline"]["p95_latency_ms"],
                "observed_p95_latency_ms": signal["request_telemetry"]["observed"]["p95_latency_ms"],
                "baseline_error_rate": signal["request_telemetry"]["baseline"]["error_rate"],
                "observed_error_rate": signal["request_telemetry"]["observed"]["error_rate"],
                "baseline_timeout_rate": signal["request_telemetry"]["baseline"]["timeout_rate"],
                "observed_timeout_rate": signal["request_telemetry"]["observed"]["timeout_rate"],
                "sample_size": signal["request_telemetry"]["sample_size"],
            },
            "related_context": {
                "release_id": signal["deployment"]["release_id"],
                "active_incidents": signal["related_context"]["active_incidents"],
                "similar_prior_cases": signal["related_context"]["similar_prior_cases"],
            },
        }
        validate_payload("trigger.schema.json", payload)
        model = Trigger.from_dict(payload)
        self.assertEqual(model.trigger_type, "feature_flag_performance_regression")

    def test_high_risk_decision_is_a_valid_contract(self) -> None:
        payload = load_fixture("decisions", "high_risk_decision.json")
        decision = Decision.from_dict(payload)
        self.assertEqual(decision.risk["level"], "high")

    def test_kubernetes_signal_payload_validates(self) -> None:
        payload = load_fixture("signals", "kubernetes_crashloop_patch.json")
        validate_payload("kubernetes-signal.schema.json", payload)

    def test_ownership_boundary_resolves_from_registry(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        registry_path = Path("config/ownership.registry.json")

        registry = load_ownership_registry(str(registry_path))
        self.assertIsNotNone(registry)
        boundary = build_ownership_boundary(
            registry_path=str(registry_path),
            signal_payload=signal,
            default_environment="production",
        )

        self.assertTrue(boundary["resolved"])
        self.assertEqual(boundary["service"], "api-gateway")
        self.assertEqual(boundary["namespace"], "edge")
        self.assertEqual(boundary["tenant_id"], "tenant_a")
        self.assertEqual(boundary["customer_id"], "design_partner_a")
        self.assertEqual(boundary["customer_boundary"], "single_customer")
        self.assertEqual(boundary["owner"]["owner_id"], "platform.gateway")
        self.assertEqual(boundary["data_boundary"]["retention_days"], 30)
        self.assertIn("reservoir://tenant_a/ops-signals", boundary["data_boundary"]["reservoir_refs"])
        self.assertTrue(boundary["data_boundary"]["export_policy"]["redaction_required"])
        self.assertFalse(boundary["data_boundary"]["legal_action_scope"]["allowed"])
        validate_payload("ownership-boundary.schema.json", boundary)

    def test_connector_certification_matrix_bounds_runtime_state_to_registry(self) -> None:
        registry_path = Path("config/connector-certification.registry.json")

        registry = load_connector_certification_registry(str(registry_path))
        self.assertIsNotNone(registry)
        matrix = build_connector_certification_matrix(
            registry_path=str(registry_path),
            runtime_states={
                "audit_sink": {"state": "production-ready"},
                "kubernetes": {"state": "pilot-ready"},
            },
        )

        self.assertEqual(matrix["schema_version"], "mesh.connector_certification.v1")
        self.assertEqual(matrix["status"], "complete")
        self.assertEqual(matrix["connectors"]["audit_sink"]["state"], "staging-ready")
        self.assertTrue(matrix["connectors"]["audit_sink"]["credential_boundary"]["runtime_secret_mount_required"])
        self.assertEqual(matrix["connectors"]["kubernetes"]["state"], "pilot-ready")
        self.assertTrue(
            matrix["connectors"]["kubernetes"]["credential_boundary"]["production_actuator_credentials_allowed"]
        )
        actuator_connector_ids = sorted(
            connector_id
            for connector_id, connector in matrix["connectors"].items()
            if connector["credential_boundary"].get("production_actuator_credentials_allowed")
        )
        self.assertEqual(actuator_connector_ids, ["kubernetes"])
        self.assertFalse(matrix["connectors"]["deepagents"]["credential_boundary"]["repo_write_credentials_allowed"])
        validate_payload("connector-certification-matrix.schema.json", matrix)

    def test_connector_certification_blocks_non_kubernetes_production_actuator_credentials(self) -> None:
        registry_path = Path("config/connector-certification.registry.json")
        registry = load_connector_certification_registry(str(registry_path))
        self.assertIsNotNone(registry)
        mutated_registry = json.loads(json.dumps(registry))
        for connector in mutated_registry["connectors"]:
            if connector["connector_id"] == "deepagents":
                connector["credential_boundary"]["production_actuator_credentials_allowed"] = True
                break

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / "connector-certification.registry.json"
            temp_path.write_text(json.dumps(mutated_registry), encoding="utf-8")
            matrix = build_connector_certification_matrix(registry_path=str(temp_path))

        self.assertIn(
            "non_kubernetes_connector_allows_production_actuator_credentials",
            matrix["connectors"]["deepagents"]["blockers"],
        )
        validate_payload("connector-certification-matrix.schema.json", matrix)

    def test_connector_certification_blocks_proposal_lane_credential_bleed(self) -> None:
        registry_path = Path("config/connector-certification.registry.json")

        matrix = build_connector_certification_matrix(
            registry_path=str(registry_path),
            runtime_states={
                "deepagents": {
                    "state": "proposal-only",
                    "production_actuator_credentials_present": True,
                    "repo_write_credentials_present": True,
                },
            },
        )

        self.assertIn(
            "proposal_lane_production_actuator_credentials_present",
            matrix["connectors"]["deepagents"]["blockers"],
        )
        self.assertIn(
            "proposal_lane_repo_write_credentials_present",
            matrix["connectors"]["deepagents"]["blockers"],
        )
        validate_payload("connector-certification-matrix.schema.json", matrix)

    def test_deployment_compatibility_matrix_keeps_ecs_as_next_target(self) -> None:
        registry_path = Path("config/deployment-compatibility.registry.json")

        registry = load_deployment_compatibility_registry(str(registry_path))
        self.assertIsNotNone(registry)
        matrix = build_deployment_compatibility_matrix(str(registry_path))

        self.assertEqual(matrix["schema_version"], "mesh.deployment_compatibility.v1")
        self.assertEqual(matrix["status"], "complete")
        self.assertIn("docker_compose", matrix["validated_targets"])
        self.assertIn("kubernetes", matrix["validated_targets"])
        self.assertEqual(matrix["next_validated_targets"], ["ecs_fargate"])
        self.assertIn("ecs_fargate_smoke_missing", matrix["targets"]["ecs_fargate"]["promotion_blockers"])
        validate_payload("deployment-compatibility-matrix.schema.json", matrix)

    def test_timeline_proof_contract_hashes_events_and_merkle_chain(self) -> None:
        events = [
            RunEvent(
                event_id="evt_0001_test",
                run_id="run_test",
                sequence=1,
                stage="queued",
                event_type="run_queued",
                recorded_at="2026-05-05T20:00:00.000001+00:00",
                payload={"status": "queued"},
            ),
            RunEvent(
                event_id="evt_0002_test",
                run_id="run_test",
                sequence=2,
                stage="completed",
                event_type="run_completed",
                recorded_at="2026-05-05T20:00:01.000001+00:00",
                payload={"status": "completed"},
                status="completed",
            ),
        ]

        packet = build_timeline_proof(run_id="run_test", events=events)

        self.assertEqual(packet["schema_version"], "mesh.timeline_proof.v1")
        self.assertTrue(packet["checks"]["sequence_gapless"])
        self.assertTrue(packet["checks"]["timestamp_non_decreasing"])
        self.assertTrue(packet["checks"]["latest_event_proof_valid"])
        self.assertRegex(packet["timeline"][0]["payload_sha256"], r"^[0-9a-f]{64}$")
        self.assertIsInstance(packet["timeline"][0]["time_unix_nano"], int)
        validate_payload("timeline-proof.schema.json", packet)

    def test_run_admission_blocks_target_lock_and_tenant_quota(self) -> None:
        boundary = {
            "tenant_id": "tenant_a",
            "environment": "production",
            "service": "api-gateway",
        }

        packet = build_run_admission(
            run_id="run_test",
            ownership_boundary=boundary,
            queue_depth=1,
            queue_size=100,
            worker_count=4,
            tenant_active_runs=4,
            tenant_active_run_quota=4,
            target_lock_holder="run_holder",
        )

        self.assertEqual(packet["decision"], "blocked")
        self.assertEqual(packet["target_lock_key"], "tenant_a:production:api-gateway")
        self.assertIn("tenant_active_run_quota_exceeded", packet["blockers"])
        self.assertIn("target_lock_held", packet["blockers"])
        validate_payload("run-admission.schema.json", packet)

    def test_policy_lifecycle_packet_signs_policy_hashes(self) -> None:
        packet = build_policy_lifecycle_packet(signing_key="test-policy-signing-key")

        self.assertEqual(packet["schema_version"], "mesh.policy_lifecycle.v1")
        self.assertEqual(packet["status"], "complete")
        self.assertTrue(packet["policy_hashes"])
        self.assertRegex(packet["combined_policy_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(packet["signature"]["algorithm"], "hmac-sha256")
        self.assertEqual(packet["missing"], [])
        validate_payload("policy-lifecycle-packet.schema.json", packet)

    def test_evidence_sufficiency_contract_counts_action_risk_refs(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        trigger = Trigger.from_dict(
            {
                "trigger_id": "trg_test",
                "trigger_type": "feature_flag_performance_regression",
                "triggered_at": signal["observed_at"],
                "environment": signal["environment"],
                "service": signal["service"],
                "endpoint": signal["endpoint"],
                "flag_key": signal["feature_flag"]["flag_key"],
                "current_rollout_pct": signal["feature_flag"]["current_rollout_pct"],
                "comparison_window": signal["comparison_window"],
                "segment": signal["segment"],
                "metrics": {
                    "baseline_p95_latency_ms": signal["request_telemetry"]["baseline"]["p95_latency_ms"],
                    "observed_p95_latency_ms": signal["request_telemetry"]["observed"]["p95_latency_ms"],
                    "baseline_error_rate": signal["request_telemetry"]["baseline"]["error_rate"],
                    "observed_error_rate": signal["request_telemetry"]["observed"]["error_rate"],
                    "baseline_timeout_rate": signal["request_telemetry"]["baseline"]["timeout_rate"],
                    "observed_timeout_rate": signal["request_telemetry"]["observed"]["timeout_rate"],
                    "sample_size": signal["request_telemetry"]["sample_size"],
                },
                "related_context": {
                    "release_id": signal["deployment"]["release_id"],
                    "active_incidents": signal["related_context"]["active_incidents"],
                    "similar_prior_cases": signal["related_context"]["similar_prior_cases"],
                },
            }
        )
        decision = Decision.from_dict(load_fixture("decisions", "high_risk_decision.json"))
        decision.execution_plan["rollback_plan"] = "restore prior revision"
        decision.reasoning["evidence_pack"] = {
            "sufficient": True,
            "probe_results": [{"probe_id": "probe_kube_events"}],
            "scenario_analysis": {"evidence_refs": ["evt_1"]},
        }

        packet = evaluate_evidence_sufficiency(trigger, decision)

        self.assertTrue(packet["passed"])
        self.assertEqual(packet["risk_tier"], "high")
        self.assertEqual(packet["required_evidence_count"], 4)
        validate_payload("evidence-sufficiency.schema.json", packet)

    def test_code_patch_decision_is_a_valid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            payload = {
                "decision_id": "dec_patch_test",
                "trigger_id": "trg_patch_test",
                "decision_type": "investigate_and_patch",
                "autonomy_tier": "autonomous",
                "summary": "Apply a bounded patch to the search parser.",
                "reasoning": {
                    "primary_hypothesis": "A parser timeout constant is forcing the degraded path.",
                    "evidence": ["p95 latency and timeout rate regressed after rollout"],
                    "evidence_pack": {"suspected_file": "app/search.py"},
                    "alternatives_considered": ["reduce rollout to 10%", "disable feature flag fully"],
                },
                "expected_outcome": {
                    "target_metrics": {
                        "p95_latency_ms": "<= 470",
                        "error_rate": "<= 0.015",
                    },
                    "time_to_effect": "10m",
                },
                "risk": {
                    "level": "medium",
                    "blast_radius": "single_repo_single_file",
                    "customer_impact_if_wrong": "temporary service instability from an incorrect bounded patch",
                },
                "confidence": 0.78,
                "execution_plan": {
                    "system": "repo_patch_service",
                    "action": "investigate_and_patch",
                    "parameters": {
                        "repo_path": str(repo_path),
                        "allowed_paths": ["app/search.py"],
                        "suspected_file": "app/search.py",
                        "test_commands": ["python3 -m unittest discover -s tests"],
                        "patch_template": {
                            "target_file": "app/search.py",
                            "find": "old",
                            "replace": "new",
                        },
                    },
                    "rollback_plan": "restore previous file contents from backup",
                },
            }
            decision = Decision.from_dict(payload)
        self.assertEqual(decision.execution_plan["system"], "repo_patch_service")


if __name__ == "__main__":
    unittest.main()
