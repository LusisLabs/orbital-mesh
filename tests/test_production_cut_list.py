from __future__ import annotations

import json
import io
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from typing import Any, Callable, cast
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from services.decision.service import DecisionService
from services.feedback.service import FeedbackService
from services.ingest.service import IngestService
from services.trigger.service import TriggerService
from services.control_plane import RunCoordinator
from shared.mesh_runtime import ExecutionRecord, RuntimeConfig, load_fixture
from shared.mesh_runtime.integrations import build_readiness, invalidate_readiness_cache
from shared.mesh_runtime.orchestration_topology import ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION


RELEASE_GIT_COMMIT = "a" * 40
RELEASE_IMAGE_DIGEST = f"sha256:{'c' * 64}"


def _config(tmp: str, **overrides: Any) -> RuntimeConfig:
    backup_restore_rehearsal_path = Path(tmp) / "backup-restore-rehearsal.json"
    authenticated_ingress_proof_path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
    design_partner_packet_path = Path(tmp) / "design-partner-packet.json"
    if not design_partner_packet_path.exists():
        design_partner_packet_path.write_text(
            json.dumps(_design_partner_packet(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    values: dict[str, Any] = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
        "policy_signing_key": "test-policy-signing-key",
        "backup_restore_rehearsal_path": str(backup_restore_rehearsal_path),
        "authenticated_ingress_proof_path": str(authenticated_ingress_proof_path),
        "design_partner_packet_path": str(design_partner_packet_path),
    }
    values.update(overrides)
    if not backup_restore_rehearsal_path.exists() or values.get("readiness_profile"):
        backup_restore_rehearsal_path.write_text(
            json.dumps(
                _backup_restore_rehearsal(
                    environment=str(values.get("readiness_profile") or "local"),
                    state_backend=str(values.get("state_backend") or "file"),
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if not authenticated_ingress_proof_path.exists() or values.get("readiness_profile"):
        authenticated_ingress_proof_path.write_text(
            json.dumps(
                _authenticated_ingress_deployment_proof(
                    environment=str(values.get("readiness_profile") or "local"),
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return RuntimeConfig(**values)


def _pilot_ready_config(tmp: str) -> RuntimeConfig:
    return _config(
        tmp,
        readiness_profile="pilot",
        operator_identity_required=True,
        state_backend="postgres",
        database_url="postgresql://mesh:mesh@localhost:5432/mesh",
        force_approval_gate=True,
        live_feedback_required=True,
        feedback_prometheus_enabled=True,
        prometheus_url="http://prometheus.local",
        mesh_brain_artifact_uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
        mesh_brain_artifact_registry_path=str(Path(tmp) / "artifacts.json"),
        mesh_brain_artifact_upload_proof_path=_write_mesh_brain_artifact_upload_proof(tmp),
        mesh_brain_serving_base_url="http://mesh-brain-serving.private:8000",
        mesh_brain_serving_model="nvidia/nemotron-3-nano-4b",
        run_export_retention_reviewed=True,
        feature_flag_credentials_available=False,
        incident_credentials_available=False,
    )


def _write_mesh_brain_artifact_upload_proof(tmp: str) -> str:
    artifacts_path = Path(tmp) / "artifacts.json"
    proof_path = Path(tmp) / "mesh-brain-artifact-upload-proof.json"
    uri = "s3://mesh-prod-artifacts/mesh-brain/mesh_brain_model_kernel_probe_summary/eeeeeeeeeeeeeeee/artifact.json"
    sha256 = "e" * 64
    byte_count = 42
    artifacts_path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "run_id": "mesh_brain_artifact_upload_proof_run",
                        "artifact_key": "mesh_brain_model_kernel_probe_summary",
                        "uri": uri,
                        "path": str(Path(tmp) / "artifact.json"),
                        "content_hash": sha256,
                        "metadata": {
                            "production_artifact": {
                                "blob_uri": uri,
                                "sha256": sha256,
                                "byte_count": byte_count,
                                "immutable": True,
                            }
                        },
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    proof_path.write_text(
        json.dumps(
            {
                "schema_version": "mesh.artifact_upload_proof.v1",
                "uploads": [
                    {
                        "blob_uri": uri,
                        "sha256": sha256,
                        "byte_count": byte_count,
                        "provider": "s3",
                        "uploaded_at": "2026-05-10T00:00:00+00:00",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return str(proof_path)


def _record_generic_pilot_evidence(coordinator: RunCoordinator) -> None:
    session = coordinator.state_store.create_run_session(
        goal_id=coordinator.state_store.ensure_default_goal().goal_id,
        scenario_key="search_latency_regression",
        steering_mode="approval_gate",
        auto_mode=False,
        pause_points=[],
        evaluation_mode="native",
        orchestration_mode="native",
        artifacts={
            "decision": {"execution_plan": {"rollback_plan": "roll back deployment revision"}},
            "evaluation": {"blocking_reasons": ["approval required before execution"]},
            "execution": {"status": "succeeded", "external_refs": {"live_execution": True}},
        },
    )
    coordinator.state_store.append_run_event(
        session.run_id,
        stage="awaiting_operator",
        event_type="steering_command",
        payload={"command_type": "approve", "operator": {"operator_id": "approver@example.com"}},
        status="accepted",
    )
    coordinator.state_store.append_run_event(
        session.run_id,
        stage="completed",
        event_type="run_completed",
        payload={"status": "completed"},
        status="completed",
    )
    current = coordinator.state_store.get_run_session(session.run_id)
    assert current is not None
    current.stage = "completed"
    current.status = "completed"
    coordinator.state_store.save_run_session(current)


def _record_mesh_brain_gate_evidence(coordinator: RunCoordinator) -> None:
    _record_completed_probe(
        coordinator,
        "mesh_brain_model_kernel_probe",
        {
            "mesh_brain_model_kernel_run_record": {
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
    _record_completed_probe(
        coordinator,
        "mesh_brain_rollback_drill",
        {
            "mesh_brain_rollback_drill_run_record": {
                "status": "completed",
                "final_release_decision": "pass",
                "artifact_refs": _hashed_refs("mesh_brain_rollback_drill_summary"),
                "summary_metrics": {"restored_previous_artifact": True},
            }
        },
    )


def _record_completed_probe(coordinator: RunCoordinator, scenario_key: str, artifacts: dict[str, Any]) -> None:
    session = coordinator.state_store.create_run_session(
        goal_id=coordinator.state_store.ensure_default_goal().goal_id,
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
        status="completed",
    )
    current = coordinator.state_store.get_run_session(session.run_id)
    assert current is not None
    current.stage = "completed"
    current.status = "completed"
    coordinator.state_store.save_run_session(current)


def _record_filler_runs(coordinator: RunCoordinator, count: int) -> None:
    for index in range(count):
        _record_completed_probe(
            coordinator,
            f"filler_probe_{index:03d}",
            {"filler": {"index": index}},
        )


def _hashed_refs(key: str) -> dict[str, dict[str, str]]:
    return {
        key: {
            "artifact_key": key,
            "path": f"/tmp/{key}.json",
            "sha256": "a" * 64,
            "content_type": "application/json",
        }
    }


def _backup_restore_rehearsal(*, environment: str = "staging", state_backend: str = "postgres") -> dict[str, Any]:
    digest = "a" * 64
    return {
        "schema_version": "mesh.backup_restore_rehearsal.v1",
        "rehearsal_id": "restore_rehearsal_test",
        "generated_at": "2026-05-05T23:00:00Z",
        "environment": environment,
        "operator_id": "platform@example.com",
        "state_backend": state_backend,
        "backup_ref": "backup://orbital-mesh/staging/test",
        "restore_ref": "restore://orbital-mesh/staging/test",
        "rpo_seconds": 300,
        "rto_seconds": 900,
        "measured_restore_seconds": 300,
        "components": [
            {
                "component": component,
                "backup_uri": f"s3://mesh-backups/staging/{component}.json",
                "restored": True,
                "sha256_before": digest,
                "sha256_after": digest,
                "record_count": 1,
            }
            for component in (
                "state_store",
                "vault",
                "merkle_proofs",
                "integrations_config",
                "research_artifacts",
            )
        ],
    }


def _authenticated_ingress_deployment_proof(*, environment: str = "staging") -> dict[str, Any]:
    return {
        "schema_version": "mesh.authenticated_ingress_deployment_proof.v1",
        "proof_id": "authenticated_ingress_deployment_test",
        "generated_at": "2026-05-06T04:10:00Z",
        "environment": environment,
        "operator_id": "platform@example.com",
        "ingress_url": "https://mesh.staging.example.com",
        "tls": {
            "terminated": True,
            "public_listener": True,
            "minimum_version": "TLSv1.3",
            "certificate_ref": "acm://mesh-staging-cert",
            "evidence_ref": "ingress-proof://tls/test",
        },
        "identity_provider": {
            "type": "oidc",
            "sso_enforced": True,
            "identity_claim": "email",
            "roles_claim": "groups",
            "evidence_ref": "ingress-proof://oidc/test",
        },
        "header_sanitization": {
            "client_mesh_operator_header_stripped": True,
            "client_mesh_roles_header_stripped": True,
            "proxy_operator_header_stamped": True,
            "proxy_roles_header_stamped": True,
            "evidence_ref": "ingress-proof://headers/test",
        },
        "role_mapping": {
            "viewer": "group://mesh/viewers",
            "launcher": "group://mesh/launchers",
            "approver": "group://mesh/approvers",
            "admin": "group://mesh/admins",
            "evidence_ref": "ingress-proof://role-mapping/test",
        },
        "network_boundary": {
            "raw_service_publicly_reachable": False,
            "upstream_private": True,
            "allowed_proxy_ref": "security-group://mesh-ingress-to-control-plane",
            "evidence_ref": "ingress-proof://network/test",
        },
        "app_rehearsal": {
            "schema_version": "mesh.authenticated_ingress_rehearsal.v1",
            "status": "passed",
            "run_id": "run_ingress_rehearsal",
            "evidence_ref": "run-artifact://authenticated-ingress-rehearsal.json",
        },
        "audit": {
            "source_ip_or_proxy_identity_recorded": True,
            "operator_identity_recorded": True,
            "evidence_ref": "ingress-proof://audit/test",
        },
        "raw_secret_material_present": False,
    }


def _design_partner_packet() -> dict[str, Any]:
    return {
        "schema_version": "mesh.design_partner_packet.v1",
        "packet_id": "design_partner_test",
        "generated_at": "2026-05-06T04:40:00Z",
        "partner": {
            "partner_id": "partner-a",
            "technical_owner": "platform@example.com",
            "escalation_channel": "pager://partner-a/platform",
            "pilot_window_days": 30,
        },
        "pilot_scope": {
            "environment": "pilot",
            "kubernetes_contexts": ["prod-us-east-1"],
            "namespaces": ["mesh-targets"],
            "service_classes": ["search-api"],
            "approval_gate_forced": True,
            "live_execution_limited": True,
            "feature_flag_adapter_disabled": True,
            "incident_adapter_disabled": True,
            "proposal_lanes_advisory_only": True,
            "evidence_ref": "design-partner://scope/partner-a",
        },
        "success_metrics": {
            "allowed_action_with_feedback": True,
            "denied_action_with_blocker": True,
            "no_proposal_lane_credentials": True,
            "operator_identity_on_mutations": True,
            "kill_switch_rehearsed": True,
            "merkle_proofs_available": True,
            "postgres_restart_proof_passed": True,
            "evidence_ref": "design-partner://success-metrics/partner-a",
        },
        "data_handling": {
            "retention_days": 30,
            "training_use_opt_in": False,
            "audit_records_excluded_from_training_by_default": True,
            "raw_secrets_disallowed": True,
            "kubeconfig_contents_disallowed": True,
            "private_keys_disallowed": True,
            "customer_payloads_excluded": True,
            "evidence_ref": "design-partner://data-handling/partner-a",
        },
        "support_model": {
            "mesh_support_hours": "business-hours",
            "partner_owner_ref": "user://platform@example.com",
            "emergency_owner": "operator",
            "postmortem_packet_required": True,
            "evidence_ref": "design-partner://support/partner-a",
        },
        "rollback_plan": {
            "plan_ref": "rollback://partner-a/pilot",
            "kill_switch_ref": "runbook://kill-switch",
            "rollback_metadata_required": True,
            "human_review_on_ambiguous_execution": True,
        },
        "consent": {
            "partner_approved": True,
            "mesh_approved": True,
            "real_user_experiment_consent_required": True,
            "real_user_experiment_consent_ref": "consent://partner-a/real-user-experiment",
            "data_handling_terms_ref": "terms://partner-a/data-handling",
            "signed_at": "2026-05-06T04:40:00Z",
        },
        "evidence_summary": {
            "go_no_go_status": "go",
            "go_no_go_packet_sha256": "a" * 64,
            "release_provenance_sha256": "b" * 64,
            "run_export_ref": "run-export://partner-a/run_1",
            "readiness_ref": "readiness://partner-a/pilot",
        },
        "raw_secret_material_present": False,
    }


def _on_call_drill() -> dict[str, Any]:
    return {
        "schema_version": "mesh.on_call_drill.v1",
        "drill_id": "on_call_drill_test",
        "generated_at": "2026-05-05T23:45:00Z",
        "operator_id": "platform@example.com",
        "environment": "pilot",
        "recovery_target_seconds": 900,
        "measured_recovery_seconds": 420,
        "kill_switch": {
            "live_execution_disabled": True,
            "watchers_paused": True,
            "approval_gate_forced": True,
            "event_ref": "event://kill-switch/test",
        },
        "bad_target_revocation": {
            "target_ref": "kubernetes://cluster-a/default/bad-target",
            "revoked": True,
            "denied_action_ref": "run://denied-action/test",
        },
        "stuck_run_recovery": {
            "run_id": "run_stuck_test",
            "recovered": True,
            "event_ref": "event://run-recovered/test",
        },
        "failed_dependency": {
            "dependency": "prometheus",
            "degraded_state_visible": True,
            "operator_action_ref": "runbook://failed-dependency/test",
        },
        "provider_key_rotation": {
            "verification_ref": "credential-rotation://provider/test",
            "status": "pass",
            "break_glass_recorded": True,
        },
        "state_restore": {
            "verification_ref": "backup-restore://pilot/test",
            "status": "pass",
            "restore_ref": "restore://pilot/test",
        },
    }


def _complete_release_provenance(
    packet_sha256: str,
    *,
    git_commit: str = RELEASE_GIT_COMMIT,
    image_digest: str = RELEASE_IMAGE_DIGEST,
) -> dict[str, Any]:
    return {
        "schema_version": "mesh.release_provenance.v1",
        "status": "complete",
        "missing": [],
        "packet_sha256": packet_sha256,
        "checks": {
            "git_commit": True,
            "clean_git_tree": True,
            "image_tag": True,
            "image_digest": True,
            "base_image_digests": True,
            "dependency_lockfiles": True,
            "policy_hashes": True,
            "policy_lifecycle_signed": True,
            "connector_certification_registry": True,
            "deployment_compatibility_registry": True,
            "migration_version": True,
            "migration_rehearsal": True,
            "sbom_path": True,
            "vulnerability_scan_path": True,
            "ci_attestation": True,
            "build_command": True,
            "builder_identity": True,
            "readiness_profile": True,
            "environment": True,
        },
        "ci": {
            "attestation": {
                "provider": "github-actions",
                "run_id": "ci-run-1",
                "sha": git_commit,
                "expected_sha": git_commit,
                "sha_matches_git_commit": True,
                "valid": True,
            }
        },
        "git": {"commit": git_commit},
        "image": {"digest": image_digest},
    }


class ReadinessProfileTests(unittest.TestCase):
    def test_staging_profile_fails_required_identity_not_optional_clis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=False,
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["profile"], "staging")
        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("operator_identity_required", readiness["blockers"])
        self.assertEqual(
            readiness["blocker_details"]["operator_identity_required"]["env"],
            ["MESH_OPERATOR_IDENTITY_REQUIRED"],
        )
        self.assertEqual(
            readiness["blocker_details"]["operator_identity_required"]["state_slice"],
            "RuntimeConfig.operator_identity_required",
        )
        self.assertTrue(readiness["required_checks"]["ownership_registry_configured"])
        self.assertTrue(readiness["required_checks"]["failure_mode_library_configured"])
        self.assertTrue(readiness["required_checks"]["threat_model_register_reviewed"])
        self.assertTrue(readiness["required_checks"]["deployment_compatibility_registry_reviewed"])
        self.assertTrue(readiness["required_checks"]["backup_restore_rehearsal_verified"])
        self.assertNotIn("promptfoo", readiness["blockers"])

    def test_staging_profile_blocks_missing_ownership_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    ownership_registry_path=str(Path(tmp) / "missing-ownership.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("ownership_registry_configured", readiness["blockers"])

    def test_staging_profile_blocks_missing_connector_certification_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    connector_certification_registry_path=str(Path(tmp) / "missing-connectors.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("connector_certification_registry_configured", readiness["blockers"])

    def test_staging_profile_blocks_missing_threat_model_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    threat_model_register_path=str(Path(tmp) / "missing-threat-model.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("threat_model_register_reviewed", readiness["blockers"])

    def test_staging_profile_blocks_missing_data_classification_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    data_classification_policy_path=str(Path(tmp) / "missing-data-classification.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("data_classification_policy_reviewed", readiness["blockers"])

    def test_staging_profile_blocks_missing_agentic_operator_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    agentic_operator_source_provenance_path=str(
                        Path(tmp) / "missing-agentic-operator-source.json"
                    ),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("agentic_operator_source_provenance_recorded", readiness["blockers"])

    def test_staging_profile_blocks_missing_deployment_compatibility_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    deployment_compatibility_registry_path=str(
                        Path(tmp) / "missing-deployment-compatibility.json"
                    ),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("deployment_compatibility_registry_reviewed", readiness["blockers"])

    def test_staging_profile_passes_with_optional_lanes_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                _config(
                    tmp,
                    readiness_profile="staging",
                    operator_identity_required=True,
                    otel_receiver_enabled=True,
                    otel_receiver_token="token",
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["promptfoo"]["ready"])
        self.assertEqual(readiness["promptfoo"]["certification"], "staging-ready")
        self.assertEqual(readiness["hermes"]["certification"], "staging-ready")
        self.assertEqual(readiness["goose"]["certification"], "staging-ready")
        self.assertEqual(readiness["latentmas"]["certification"], "staging-ready")
        self.assertEqual(readiness["deepagents"]["certification"], "staging-ready")

    def test_pilot_profile_requires_postgres_live_feedback_and_disabled_unfinished_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(_pilot_ready_config(tmp), force=True).to_dict()

        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["required_checks"]["mesh_brain_artifact_uri_prefix_configured"])
        self.assertTrue(readiness["required_checks"]["mesh_brain_artifact_upload_proof_verified"])
        self.assertTrue(readiness["required_checks"]["mesh_brain_serving_backend_configured"])
        self.assertTrue(readiness["required_checks"]["run_export_retention_reviewed"])
        self.assertEqual(readiness["connector_certification"]["feature_flag_adapter"]["state"], "staging-ready")
        self.assertEqual(readiness["connector_certification"]["incident_adapter"]["state"], "staging-ready")

    def test_pilot_profile_blocks_unreviewed_run_export_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _pilot_ready_config(tmp)
            config.run_export_retention_reviewed = False
            readiness = build_readiness(config, force=True).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("run_export_retention_reviewed", readiness["blockers"])

    def test_pilot_profile_blocks_local_mesh_brain_artifact_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _pilot_ready_config(tmp)
            config.mesh_brain_artifact_uri_prefix = f"file://{tmp}/mesh-brain"
            readiness = build_readiness(config, force=True).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("mesh_brain_artifact_uri_prefix_configured", readiness["blockers"])
        detail = readiness["blocker_details"]["mesh_brain_artifact_uri_prefix_configured"]
        self.assertEqual(detail["env"], ["MESH_BRAIN_ARTIFACT_URI_PREFIX"])
        self.assertEqual(detail["observed"], f"file://{tmp}/mesh-brain")

    def test_pilot_profile_blocks_missing_mesh_brain_artifact_upload_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _pilot_ready_config(tmp)
            Path(cast(str, config.mesh_brain_artifact_upload_proof_path)).unlink()

            readiness = build_readiness(config, force=True).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("mesh_brain_artifact_upload_proof_verified", readiness["blockers"])
        detail = readiness["blocker_details"]["mesh_brain_artifact_upload_proof_verified"]
        self.assertEqual(detail["env"], ["MESH_BRAIN_ARTIFACT_REGISTRY_PATH", "MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH"])
        self.assertEqual(detail["observed"]["status"], "missing")
        self.assertIn("mesh_brain_artifact_upload_proof_path", detail["observed"]["missing"])

    def test_readiness_blocker_details_include_proof_path_and_provider_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_ingress = Path(tmp) / "missing-ingress.json"
            config = _pilot_ready_config(tmp)
            config.authenticated_ingress_proof_path = str(missing_ingress)
            config.feature_flag_credentials_available = True
            config.feature_flag_provider_proof_path = str(Path(tmp) / "missing-feature-proof.json")

            readiness = build_readiness(config, force=True).to_dict()

        ingress = readiness["blocker_details"]["authenticated_ingress_deployment_verified"]
        self.assertEqual(ingress["evidence_path"], str(missing_ingress))
        self.assertEqual(ingress["env"], ["MESH_AUTHENTICATED_INGRESS_PROOF_PATH"])
        feature_flag = readiness["blocker_details"]["unfinished_feature_flag_adapter_disabled"]
        self.assertEqual(feature_flag["env"], ["MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE", "MESH_FEATURE_FLAG_PROVIDER_PROOF_PATH"])
        self.assertEqual(
            feature_flag["observed"],
            {"credentials_available": True, "proof_path_configured": True, "readiness_profile": "pilot"},
        )

    def test_readiness_cache_key_tracks_mesh_brain_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalidate_readiness_cache()
            self.addCleanup(invalidate_readiness_cache)
            blocked_config = _pilot_ready_config(tmp)
            blocked_config.mesh_brain_artifact_uri_prefix = None

            blocked = build_readiness(blocked_config).to_dict()
            ready = build_readiness(_pilot_ready_config(tmp)).to_dict()

        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("mesh_brain_artifact_uri_prefix_configured", blocked["blockers"])
        self.assertEqual(ready["status"], "ready")

    def test_readiness_cache_key_tracks_default_steering_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalidate_readiness_cache()
            self.addCleanup(invalidate_readiness_cache)
            blocked_config = _pilot_ready_config(tmp)
            blocked_config.force_approval_gate = False
            blocked_config.default_steering_mode = "manual_review"
            ready_config = _pilot_ready_config(tmp)
            ready_config.force_approval_gate = False
            ready_config.default_steering_mode = "approval_gate"

            blocked = build_readiness(blocked_config).to_dict()
            ready = build_readiness(ready_config).to_dict()

        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("force_approval_gate", blocked["blockers"])
        self.assertEqual(ready["status"], "ready")


class ProductionComposeContractTests(unittest.TestCase):
    def test_prod_compose_defaults_to_private_boundary_and_required_durable_mesh_brain_config(self) -> None:
        compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")

        self.assertIn('${MESH_PUBLISH_HOST:-127.0.0.1}:${MESH_PUBLISH_PORT:-8787}:8787', compose)
        self.assertNotIn('- "${MESH_PUBLISH_PORT:-8787}:8787"', compose)
        for marker in (
            'MESH_READINESS_PROFILE: "${MESH_READINESS_PROFILE:-pilot}"',
            'MESH_STATE_BACKEND: "${MESH_STATE_BACKEND:-postgres}"',
            'MESH_DATABASE_URL: "${MESH_DATABASE_URL:?set Postgres database URL for production state}"',
            'MESH_OPERATOR_IDENTITY_REQUIRED: "${MESH_OPERATOR_IDENTITY_REQUIRED:-1}"',
            'MESH_DESIGN_PARTNER_PACKET_PATH: "${MESH_DESIGN_PARTNER_PACKET_PATH:?set design partner pilot packet path}"',
            'MESH_FORCE_APPROVAL_GATE: "${MESH_FORCE_APPROVAL_GATE:-1}"',
            'MESH_LIVE_FEEDBACK_REQUIRED: "${MESH_LIVE_FEEDBACK_REQUIRED:-1}"',
            'MESH_FEEDBACK_PROMETHEUS_ENABLED: "${MESH_FEEDBACK_PROMETHEUS_ENABLED:-1}"',
            'MESH_PROMETHEUS_URL: "${MESH_PROMETHEUS_URL:?set production Prometheus URL for feedback and telemetry}"',
            'MESH_BRAIN_ARTIFACT_URI_PREFIX: "${MESH_BRAIN_ARTIFACT_URI_PREFIX:?set durable object-storage URI prefix for Mesh Brain artifacts}"',
            'MESH_BRAIN_ARTIFACT_REGISTRY_PATH: "${MESH_BRAIN_ARTIFACT_REGISTRY_PATH:?set Mesh Brain artifact registry export path}"',
            'MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH: "${MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH:?set Mesh Brain artifact upload proof manifest path}"',
            'MESH_BRAIN_SERVING_BASE_URL: "${MESH_BRAIN_SERVING_BASE_URL:?set OpenAI-compatible Mesh Brain serving backend URL}"',
            'MESH_BRAIN_SERVING_MODEL: "${MESH_BRAIN_SERVING_MODEL:?set Mesh Brain serving model name}"',
            'MESH_RUN_EXPORT_RETENTION_DAYS: "${MESH_RUN_EXPORT_RETENTION_DAYS:-30}"',
            'MESH_RUN_EXPORT_RETENTION_REVIEWED: "${MESH_RUN_EXPORT_RETENTION_REVIEWED:?set MESH_RUN_EXPORT_RETENTION_REVIEWED=1 after reviewing pilot retention policy}"',
            'MESH_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH: "${MESH_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH:-/app/config/deployment-compatibility.registry.json}"',
            'MESH_POLICY_LIFECYCLE_MANIFEST_PATH: "${MESH_POLICY_LIFECYCLE_MANIFEST_PATH:-/app/config/policy-lifecycle.manifest.json}"',
            'MESH_FAILURE_MODE_LIBRARY_PATH: "${MESH_FAILURE_MODE_LIBRARY_PATH:-/app/config/failure-mode.library.json}"',
            'MESH_POLICY_SIGNING_KEY: "${MESH_POLICY_SIGNING_KEY:-}"',
            'MESH_POLICY_SIGNING_KEY_PATH: "${MESH_POLICY_SIGNING_KEY_PATH:-}"',
            'MESH_BUILD_COMMIT: "${MESH_BUILD_COMMIT:?set release git commit from release provenance packet}"',
            'MESH_BUILD_IMAGE_DIGEST: "${MESH_BUILD_IMAGE_DIGEST:?set release image digest from release provenance packet}"',
            'MESH_BACKUP_RESTORE_REHEARSAL_PATH: "${MESH_BACKUP_RESTORE_REHEARSAL_PATH:?set backup and restore rehearsal proof path}"',
            'MESH_MIGRATION_REHEARSAL_PATH: "${MESH_MIGRATION_REHEARSAL_PATH:?set Postgres migration rehearsal proof path}"',
            'MESH_ON_CALL_DRILL_PATH: "${MESH_ON_CALL_DRILL_PATH:?set production on-call drill proof path}"',
            'MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE: "${MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE:-false}"',
            'MESH_INCIDENT_CREDENTIALS_AVAILABLE: "${MESH_INCIDENT_CREDENTIALS_AVAILABLE:-false}"',
        ):
            self.assertIn(marker, compose)

    def test_env_example_documents_pilot_evidence_handoff(self) -> None:
        env_example = Path(".env.example").read_text(encoding="utf-8")

        for marker in (
            "MESH_AUTHENTICATED_INGRESS_PROOF_PATH=.mesh-runtime-state/proofs/authenticated-ingress-deployment-proof.json",
            "MESH_DESIGN_PARTNER_PACKET_PATH=.mesh-runtime-state/proofs/design-partner-packet.json",
            "MESH_BACKUP_RESTORE_REHEARSAL_PATH=.mesh-runtime-state/backup-restore-rehearsal.json",
            "# MESH_POLICY_SIGNING_KEY_PATH=/run/secrets/mesh-policy-signing-key",
            "# MESH_POLICY_SIGNING_KEY=<target HMAC key from secret manager>",
            "# MESH_BRAIN_ARTIFACT_URI_PREFIX=s3://mesh-prod-artifacts/mesh-brain",
            "MESH_BRAIN_ARTIFACT_REGISTRY_PATH=.mesh-runtime-state/artifacts.json",
            "MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH=.mesh-runtime-state/mesh-brain-artifact-upload-proof.json",
            "# MESH_BRAIN_SERVING_BASE_URL=https://mesh-brain-serving.example.internal/v1",
            "# MESH_BRAIN_SERVING_MODEL=nvidia/nemotron-3-nano-4b",
            "MESH_RUN_EXPORT_RETENTION_DAYS=30",
            "MESH_RUN_EXPORT_RETENTION_REVIEWED=0",
            "MESH_RELEASE_PROVENANCE_PATH=.mesh-runtime-state/release-provenance.json",
            "# MESH_BUILD_IMAGE_DIGEST=sha256:<release image digest>",
            "MESH_ON_CALL_DRILL_PATH=.mesh-runtime-state/on-call-drill.json",
        ):
            self.assertIn(marker, env_example)


class PilotGoNoGoMeshBrainGateTests(unittest.TestCase):
    def test_readiness_cache_timestamp_is_recorded_after_slow_probe(self) -> None:
        class SlowReadiness:
            def to_dict(self) -> dict[str, Any]:
                return {"status": "ready", "profile": "pilot", "blockers": []}

        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            monotonic_values = iter([100.0, 115.0, 116.0])
            try:
                with (
                    patch("services.control_plane.time.monotonic", side_effect=lambda: next(monotonic_values)),
                    patch("services.control_plane.build_readiness", return_value=SlowReadiness()) as readiness_probe,
                ):
                    first = coordinator.build_readiness()
                    second = coordinator.build_readiness()

                self.assertEqual(first["status"], "ready")
                self.assertEqual(first["profile"], "pilot")
                self.assertEqual(first["blockers"], [])
                self.assertIn("hardened_arena", first)
                self.assertIs(second, first)
                self.assertEqual(readiness_probe.call_count, 1)
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_requires_mesh_brain_kernel_live_canary_and_rollback_drill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    mesh_brain_artifact_registry_path=str(Path(tmp) / "artifacts.json"),
                    mesh_brain_artifact_upload_proof_path=_write_mesh_brain_artifact_upload_proof(tmp),
                    build_commit=RELEASE_GIT_COMMIT,
                    build_image_digest=RELEASE_IMAGE_DIGEST,
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)

                blocked = coordinator.generate_pilot_go_no_go()

                self.assertEqual(blocked["status"], "blocked")
                self.assertIn("mesh_brain_model_kernel_gate_observed", blocked["missing_evidence"])
                self.assertIn("mesh_brain_live_canary_smoke_observed", blocked["missing_evidence"])
                self.assertIn("mesh_brain_single_crops_canary_lane_observed", blocked["missing_evidence"])
                self.assertIn("mesh_brain_rollback_drill_observed", blocked["missing_evidence"])
                self.assertIn("release_provenance_complete", blocked["missing_evidence"])
                self.assertIn("on_call_drill_verified", blocked["missing_evidence"])

                _record_mesh_brain_gate_evidence(coordinator)
                still_blocked = coordinator.generate_pilot_go_no_go()
                self.assertEqual(still_blocked["status"], "blocked")
                self.assertIn("release_provenance_complete", still_blocked["missing_evidence"])
                self.assertIn("on_call_drill_verified", still_blocked["missing_evidence"])
                release_provenance.write_text(
                    json.dumps(_complete_release_provenance("b" * 64))
                    + "\n",
                    encoding="utf-8",
                )
                no_drill = coordinator.generate_pilot_go_no_go()
                self.assertEqual(no_drill["status"], "blocked")
                self.assertIn("on_call_drill_verified", no_drill["missing_evidence"])
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "go")
                self.assertEqual(packet["missing_evidence"], [])
                self.assertEqual(packet["release_provenance"]["status"], "complete")
                self.assertEqual(packet["release_provenance"]["packet_sha256"], "b" * 64)
                self.assertEqual(packet["on_call_drill"]["status"], "pass")
                self.assertEqual(packet["on_call_drill"]["drill_id"], "on_call_drill_test")
                self.assertEqual(packet["mesh_brain_artifact_upload_proof"]["status"], "pass")
                self.assertEqual(packet["observed"]["mesh_brain_canary_lanes"], [{"tenant_id": "tenant_a", "task_type": "crops"}])
                self.assertEqual(len(packet["observed"]["mesh_brain_model_kernel_run_ids"]), 1)
                self.assertEqual(len(packet["observed"]["mesh_brain_live_canary_smoke_run_ids"]), 1)
                self.assertEqual(len(packet["observed"]["mesh_brain_rollback_drill_run_ids"]), 1)
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_requires_mesh_brain_artifact_upload_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    build_commit=RELEASE_GIT_COMMIT,
                    build_image_digest=RELEASE_IMAGE_DIGEST,
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)
                _record_mesh_brain_gate_evidence(coordinator)
                release_provenance.write_text(
                    json.dumps(_complete_release_provenance("b" * 64)) + "\n",
                    encoding="utf-8",
                )
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "blocked")
                self.assertIn("mesh_brain_artifact_upload_proof_verified", packet["missing_evidence"])
                self.assertEqual(packet["mesh_brain_artifact_upload_proof"]["status"], "missing")
                self.assertIn(
                    "mesh_brain_artifact_upload_proof_path",
                    packet["mesh_brain_artifact_upload_proof"]["missing"],
                )
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_rejects_failed_live_action_as_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    build_commit=RELEASE_GIT_COMMIT,
                    build_image_digest=RELEASE_IMAGE_DIGEST,
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)
                runs = coordinator.state_store.list_run_sessions()
                generic = next(run for run in runs if run.scenario_key == "search_latency_regression")
                generic.artifacts["execution"] = {
                    "status": "failed",
                    "external_refs": {"live_execution": True},
                    "failure": {"reason": "kubernetes_live_execution_failed"},
                }
                coordinator.state_store.save_run_session(generic)
                _record_mesh_brain_gate_evidence(coordinator)
                release_provenance.write_text(
                    json.dumps(_complete_release_provenance("b" * 64))
                    + "\n",
                    encoding="utf-8",
                )
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "blocked")
                self.assertIn("live_action_proof_observed", packet["missing_evidence"])
                self.assertEqual(packet["observed"]["live_action_run_ids"], [])
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_keeps_retained_evidence_outside_hot_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    mesh_brain_artifact_registry_path=str(Path(tmp) / "artifacts.json"),
                    mesh_brain_artifact_upload_proof_path=_write_mesh_brain_artifact_upload_proof(tmp),
                    build_commit=RELEASE_GIT_COMMIT,
                    build_image_digest=RELEASE_IMAGE_DIGEST,
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)
                _record_mesh_brain_gate_evidence(coordinator)
                release_provenance.write_text(
                    json.dumps(_complete_release_provenance("b" * 64))
                    + "\n",
                    encoding="utf-8",
                )
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                _record_filler_runs(coordinator, 125)

                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "go")
                self.assertEqual(packet["missing_evidence"], [])
                self.assertGreater(packet["observed"]["run_count"], 100)
                self.assertEqual(len(packet["observed"]["mesh_brain_live_canary_smoke_run_ids"]), 1)
                self.assertEqual(packet["observed"]["mesh_brain_canary_lanes"], [{"tenant_id": "tenant_a", "task_type": "crops"}])
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_rejects_release_provenance_without_ci_sha_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    build_commit=RELEASE_GIT_COMMIT,
                    build_image_digest=RELEASE_IMAGE_DIGEST,
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)
                _record_mesh_brain_gate_evidence(coordinator)
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                stale_release = _complete_release_provenance("b" * 64)
                stale_release["ci"]["attestation"]["sha_matches_git_commit"] = False
                release_provenance.write_text(
                    json.dumps(stale_release) + "\n",
                    encoding="utf-8",
                )

                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "blocked")
                self.assertIn("release_provenance_complete", packet["missing_evidence"])
                self.assertEqual(packet["release_provenance"]["status"], "incomplete")
                self.assertIn("ci_attestation_sha_matches_git_commit", packet["release_provenance"]["missing"])
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_rejects_release_provenance_for_different_runtime_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    build_commit="d" * 40,
                    build_image_digest=f"sha256:{'e' * 64}",
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)
                _record_mesh_brain_gate_evidence(coordinator)
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                release_provenance.write_text(
                    json.dumps(_complete_release_provenance("b" * 64)) + "\n",
                    encoding="utf-8",
                )

                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "blocked")
                self.assertIn("release_provenance_complete", packet["missing_evidence"])
                self.assertEqual(packet["release_provenance"]["status"], "incomplete")
                self.assertIn("runtime_build_commit_match", packet["release_provenance"]["missing"])
                self.assertIn("runtime_image_digest_match", packet["release_provenance"]["missing"])
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_rejects_release_provenance_without_runtime_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    build_commit="unknown",
                    build_image_digest="",
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)
                _record_mesh_brain_gate_evidence(coordinator)
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                release_provenance.write_text(
                    json.dumps(_complete_release_provenance("b" * 64)) + "\n",
                    encoding="utf-8",
                )

                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "blocked")
                self.assertIn("release_provenance_complete", packet["missing_evidence"])
                self.assertEqual(packet["release_provenance"]["status"], "incomplete")
                self.assertIn("runtime_build_commit", packet["release_provenance"]["missing"])
                self.assertIn("runtime_image_digest", packet["release_provenance"]["missing"])
            finally:
                coordinator.stop_background_workers()

    def test_pilot_go_no_go_rejects_release_provenance_without_packet_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_provenance = Path(tmp) / "release-provenance.json"
            on_call_drill = Path(tmp) / "on-call-drill.json"
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    release_provenance_path=str(release_provenance),
                    on_call_drill_path=str(on_call_drill),
                    build_commit=RELEASE_GIT_COMMIT,
                    build_image_digest=RELEASE_IMAGE_DIGEST,
                )
            )
            coordinator._readiness_cache = (time.monotonic(), build_readiness(_pilot_ready_config(tmp), force=True).to_dict())
            try:
                _record_generic_pilot_evidence(coordinator)
                _record_mesh_brain_gate_evidence(coordinator)
                on_call_drill.write_text(
                    json.dumps(_on_call_drill(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                packet_without_build_metadata = _complete_release_provenance("b" * 64)
                del packet_without_build_metadata["git"]
                del packet_without_build_metadata["image"]
                release_provenance.write_text(
                    json.dumps(packet_without_build_metadata) + "\n",
                    encoding="utf-8",
                )

                packet = coordinator.generate_pilot_go_no_go()

                self.assertEqual(packet["status"], "blocked")
                self.assertIn("release_provenance_complete", packet["missing_evidence"])
                self.assertEqual(packet["release_provenance"]["status"], "incomplete")
                self.assertIn("release_git_commit", packet["release_provenance"]["missing"])
                self.assertIn("release_image_digest", packet["release_provenance"]["missing"])
            finally:
                coordinator.stop_background_workers()


class OperatorRoleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = _config(
            self.temp_dir.name,
            environment="production",
            server_host="127.0.0.1",
            server_port=0,
            operator_identity_required=True,
            watch_enabled=True,
            watch_targets=(
                {
                    "deployment_name": "semantic-search",
                    "namespace": "search",
                    "kube_context": "mesh-compose",
                },
            ),
        )
        self.server, self.thread = start_server_in_thread(self.config, start_sidecar=False)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.coordinator._lock:
                active_workers = list(self.server.coordinator._threads.values())
            if not any(worker.is_alive() for worker in active_workers):
                break
            time.sleep(0.05)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_run_creation_and_approval_require_roles_and_stamp_operator(self) -> None:
        payload = {
            "scenario_key": "search_latency_regression",
            "evaluation_mode": "native",
            "orchestration_mode": "native",
            "steering_mode": "approval_gate",
        }
        with self.assertRaises(HTTPError) as missing:
            self._request("POST", "/api/runs", payload)
        self.assertEqual(missing.exception.code, 401)

        with self.assertRaises(HTTPError) as forbidden:
            self._request(
                "POST",
                "/api/runs",
                payload,
                headers={"X-Mesh-Operator": "viewer@example.com", "X-Mesh-Roles": "viewer"},
            )
        self.assertEqual(forbidden.exception.code, 403)

        run = self._request(
            "POST",
            "/api/runs",
            payload,
            headers={"X-Mesh-Operator": "launcher@example.com", "X-Mesh-Roles": "launcher"},
        )
        self.assertEqual(run["artifacts"]["operator"]["operator_id"], "launcher@example.com")
        self.assertTrue(run["artifacts"]["ownership_boundary"]["resolved"])
        self.assertEqual(run["artifacts"]["ownership_boundary"]["owner"]["owner_id"], "platform.gateway")
        self.assertEqual(run["artifacts"]["ownership_boundary"]["namespace"], "edge")
        self.assertEqual(run["artifacts"]["ownership_boundary"]["customer_boundary"], "single_customer")
        self.assertIn(
            "reservoir://tenant_a/ops-signals",
            run["artifacts"]["ownership_boundary"]["data_boundary"]["reservoir_refs"],
        )
        self.assertFalse(
            run["artifacts"]["ownership_boundary"]["data_boundary"]["legal_action_scope"]["allowed"]
        )
        paused = self._poll_run(run["run_id"], lambda item: item["stage"] == "awaiting_operator")
        ownership_events = [
            event for event in paused["events"] if event["event_type"] == "ownership_boundary_recorded"
        ]
        self.assertEqual(ownership_events[-1]["artifact_key"], "ownership_boundary")
        self.assertEqual(ownership_events[-1]["status"], "captured")

        with self.assertRaises(HTTPError) as approval_queue_missing:
            self._request("GET", "/api/approvals")
        self.assertEqual(approval_queue_missing.exception.code, 401)
        approval_queue = self._request(
            "GET",
            "/api/approvals",
            headers={"X-Mesh-Operator": "viewer@example.com", "X-Mesh-Roles": "viewer"},
        )
        self.assertEqual(approval_queue["schema_version"], "mesh.approval_queue.v1")
        self.assertEqual(approval_queue["pending_count"], 1)
        self.assertEqual(approval_queue["items"][0]["run_id"], paused["run_id"])
        self.assertEqual(approval_queue["items"][0]["approval_state"], "pending")
        self.assertEqual(approval_queue["items"][0]["requested_by"]["operator_id"], "launcher@example.com")
        self.assertIn("approve", approval_queue["items"][0]["allowed_commands"])

        with self.assertRaises(HTTPError) as steering_forbidden:
            self._request(
                "POST",
                f"/api/runs/{paused['run_id']}/steer",
                {"command": "approve"},
                headers={"X-Mesh-Operator": "launcher@example.com", "X-Mesh-Roles": "launcher"},
            )
        self.assertEqual(steering_forbidden.exception.code, 403)

        handed_off = self._request(
            "POST",
            f"/api/runs/{paused['run_id']}/steer",
            {
                "command": "handoff",
                "to_operator_id": "approver@example.com",
                "to_roles": ["approver"],
                "reason": "launcher shift change",
                "next_action": "review evaluation and approve only if blockers are clear",
                "urgency": "high",
            },
            headers={"X-Mesh-Operator": "launcher@example.com", "X-Mesh-Roles": "launcher"},
        )
        handoffs = handed_off["artifacts"]["operator_handoffs"]
        self.assertEqual(handoffs[-1]["schema_version"], "mesh.operator_handoff.v1")
        self.assertEqual(handoffs[-1]["from_operator"]["operator_id"], "launcher@example.com")
        self.assertEqual(handoffs[-1]["to_operator"]["operator_id"], "approver@example.com")
        self.assertEqual(handoffs[-1]["urgency"], "high")
        handoff_events = [event for event in handed_off["events"] if event["event_type"] == "operator_handoff_recorded"]
        self.assertEqual(handoff_events[-1]["artifact_key"], "operator_handoff")

        approved = self._request(
            "POST",
            f"/api/runs/{paused['run_id']}/steer",
            {"command": "approve"},
            headers={"X-Mesh-Operator": "approver@example.com", "X-Mesh-Roles": "approver"},
        )
        command_events = [event for event in approved["events"] if event["event_type"] == "steering_command"]
        self.assertEqual(command_events[-1]["payload"]["operator"]["operator_id"], "approver@example.com")

        with self.assertRaises(HTTPError) as export_forbidden:
            self._request(
                "POST",
                f"/api/runs/{paused['run_id']}/export",
                {},
                headers={"X-Mesh-Operator": "anonymous@example.com", "X-Mesh-Roles": ""},
            )
        self.assertEqual(export_forbidden.exception.code, 403)

        exported = self._request(
            "POST",
            f"/api/runs/{paused['run_id']}/export",
            {},
            headers={"X-Mesh-Operator": "viewer@example.com", "X-Mesh-Roles": "viewer"},
        )
        self.assertEqual(exported["run_id"], paused["run_id"])
        self.assertRegex(exported["package_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(exported["handoff_records"][-1]["to_operator"]["operator_id"], "approver@example.com")
        self.assertEqual([record["command_type"] for record in exported["approval_records"]], ["approve"])
        self.assertIn("## Operator Handoffs", exported["postmortem_markdown"])

        archive_headers, archive_body = self._request_bytes(
            "POST",
            f"/api/runs/{paused['run_id']}/export/archive",
            {},
            headers={"X-Mesh-Operator": "viewer@example.com", "X-Mesh-Roles": "viewer"},
        )
        self.assertEqual(archive_headers["Content-Type"], "application/zip")
        self.assertIn(f'{paused["run_id"]}.zip', archive_headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(archive_body)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("package.json", archive.namelist())
            self.assertIn("postmortem.md", archive.namelist())
            self.assertIn("records/handoffs.json", archive.namelist())

        policy_lifecycle = self._request("GET", "/api/policy/lifecycle")
        self.assertEqual(policy_lifecycle["status"], "complete")
        self.assertEqual(policy_lifecycle["signature"]["algorithm"], "hmac-sha256")
        failure_modes = self._request("GET", "/api/failure-modes")
        self.assertEqual(failure_modes["status"], "complete")
        self.assertEqual(failure_modes["schema_version"], "mesh.failure_mode_library.v1")
        self.assertEqual(failure_modes["missing_modes"], [])
        self.assertTrue(any(entry["id"] == "denied_namespace" for entry in failure_modes["entries"]))
        watchers = self._request("GET", "/api/watchers")
        self.assertEqual(watchers["ownership"]["status"], "complete")
        self.assertEqual(watchers["watchers"][0]["ownership"]["owner"]["owner_id"], "platform.search")
        watcher_ownership = self._request("GET", "/api/watchers/ownership")
        self.assertEqual(watcher_ownership["schema_version"], "mesh.watcher_ownership.v1")
        self.assertEqual(watcher_ownership["status"], "complete")
        self.assertEqual(watcher_ownership["watchers"][0]["targets"][0]["record_id"], "own_semantic_search_pilot")

    def _poll_run(
        self,
        run_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = self._request("GET", f"/api/runs/{run_id}")
            if predicate(payload):
                return payload
            time.sleep(0.1)
        raise AssertionError(f"run {run_id} did not satisfy predicate before timeout")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=request_headers, method=method)
        with urlopen(request, timeout=10) as response:
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))

    def _request_bytes(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], bytes]:
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=request_headers, method=method)
        with urlopen(request, timeout=10) as response:
            return dict(response.headers.items()), response.read()


class PolicySimulationAndKillSwitchTests(unittest.TestCase):
    def test_stop_background_workers_joins_agent_task_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            started = threading.Event()
            release = threading.Event()

            def worker() -> None:
                started.set()
                release.wait(timeout=1)

            thread = threading.Thread(target=worker)
            try:
                with coordinator._lock:
                    coordinator._agent_task_threads["run_test"] = thread
                thread.start()
                self.assertTrue(started.wait(timeout=1))

                release.set()
                coordinator.stop_background_workers(timeout=2)

                self.assertFalse(thread.is_alive())
                with coordinator._lock:
                    self.assertEqual(coordinator._agent_task_threads, {})
            finally:
                release.set()
                coordinator.stop_background_workers()

    def test_policy_simulator_does_not_create_runs_or_evaluation_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                result = coordinator.simulate_policy({"scenario_key": "search_latency_regression"})
                self.assertFalse(result["mutates"])
                self.assertTrue(result["triggered"])
                self.assertIn("decision_type", result["decision"])
                self.assertEqual(coordinator.list_runs(), [])
                self.assertFalse((Path(tmp) / "evaluated_triggers.json").exists())
            finally:
                coordinator.stop_background_workers()

    def test_kill_switch_disables_live_execution_and_forces_approval_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(
                _config(
                    tmp,
                    kubernetes_live_execution_enabled=True,
                    kubernetes_allowed_contexts=("ctx",),
                    kubernetes_allowed_namespaces=("default",),
                    default_steering_mode="interruptible_auto",
                )
            )
            try:
                status = coordinator.apply_kill_switch(
                    {
                        "stop_watchers": True,
                        "disable_live_execution": True,
                        "force_approval_gate": True,
                        "_operator": {"operator_id": "admin@example.com", "roles": ["admin"]},
                    }
                )
                self.assertIn("watchers_stopped", status["actions"])
                self.assertFalse(status["live_execution_enabled"])
                self.assertTrue(status["force_approval_gate"])

                run = coordinator.create_run(
                    {
                        "scenario_key": "search_latency_regression",
                        "evaluation_mode": "native",
                        "orchestration_mode": "native",
                        "steering_mode": "interruptible_auto",
                    }
                )
                self.assertEqual(run["steering_mode"], "approval_gate")
            finally:
                coordinator.stop_background_workers()


class RunExportPackageTests(unittest.TestCase):
    def test_run_export_package_contains_postmortem_records_merkle_and_vault_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp, vault_mirror_mode="sync"))
            try:
                goal_id = coordinator.state_store.ensure_default_goal().goal_id
                session = coordinator.state_store.create_run_session(
                    goal_id=goal_id,
                    scenario_key="search_latency_regression",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "input_signal": {
                            "signal_type": "latency_regression",
                            "service": "search",
                            "api_key": "sk-test-secret",
                        },
                        "decision": {"decision_type": "reduce_rollout", "risk_level": "medium", "requires_approval": True},
                        "evaluation": {"status": "passed", "passed": True},
                        "execution": {"status": "succeeded", "executor": "native"},
                        "feedback": {"outcome": "recovered"},
                        "lane_routing": {
                            "version": ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION,
                            "active_topology": "hybrid",
                            "rule_id": "search-kubernetes-hybrid",
                            "selected_agents": ["temporal", "kubernetes", "hermes"],
                            "selected_lanes": [
                                {
                                    "lane_id": "temporal",
                                    "role": "hybrid_lane",
                                    "authority": "proposal_only",
                                    "certified_state": "read-only",
                                }
                            ],
                            "routing_reason": "search rollback uses topology-governed lanes",
                            "reconciliation": "mesh_reconciles_hybrid_lane_outputs",
                            "blockers": [],
                        },
                        "evidence_graph": {"nodes": [{"id": "signal"}], "edges": []},
                        "operator": {"operator_id": "launcher@example.com", "roles": ["launcher"], "source": "proxy_header"},
                        "approvals": [{"operator_id": "approver@example.com", "command": "approve"}],
                    },
                )
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="trigger_ready",
                    event_type="trigger_ready",
                    payload={"trigger_id": "trigger_test", "authorization": "Bearer live-token"},
                    artifact_key="trigger",
                    status="ready",
                )
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="completed",
                    event_type="run_completed",
                    payload={"status": "completed"},
                    status="completed",
                )
                override_event = coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="awaiting_operator",
                    event_type="steering_command",
                    payload={
                        "command_id": "cmd_override_1",
                        "run_id": session.run_id,
                        "command_type": "override_decision",
                        "issued_at": "2026-05-05T00:00:00Z",
                        "payload": {"decision_type": "reduce_rollout"},
                        "operator": {
                            "operator_id": "approver@example.com",
                            "roles": ["approver"],
                            "source": "proxy_header",
                        },
                    },
                    artifact_key="operator_command",
                    status="received",
                )
                session = coordinator.state_store.get_run_session(session.run_id)
                assert session is not None
                session.stage = "completed"
                session.status = "completed"
                coordinator.state_store.save_run_session(session)

                package = coordinator.export_run_package(session.run_id)

                self.assertIsNotNone(package)
                assert package is not None
                self.assertEqual(package["package_version"], "mesh.run_export.v1")
                self.assertEqual(package["run_id"], session.run_id)
                self.assertEqual(package["decision_record"]["decision_type"], "reduce_rollout")
                self.assertTrue(package["evaluation_record"]["passed"])
                self.assertEqual(package["execution_record"]["status"], "succeeded")
                self.assertEqual(package["feedback_record"]["outcome"], "recovered")
                self.assertEqual(package["evidence_artifacts"]["input_signal"]["api_key"], "<redacted>")
                self.assertEqual(
                    package["evidence_artifacts"]["lane_routing"]["version"],
                    ORCHESTRATION_TOPOLOGY_RESOLUTION_VERSION,
                )
                self.assertEqual(package["evidence_artifacts"]["lane_routing"]["active_topology"], "hybrid")
                self.assertEqual(package["timeline_json"][0]["payload"]["authorization"], "<redacted>")
                self.assertEqual(package["evidence_artifacts"]["evidence_graph"]["nodes"][0]["id"], "signal")
                self.assertTrue(package["merkle"]["latest_event_proof"]["valid"])
                self.assertEqual(package["retention"]["retention_days"], 30)
                self.assertFalse(package["retention"]["reviewed"])
                self.assertIn("delete_after", package["retention"])
                self.assertFalse(package["size_control"]["truncated"])
                self.assertRegex(package["package_sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(Path(package["path"]).is_file())
                self.assertIn(f"# Mesh Run Export {session.run_id}", package["postmortem_markdown"])
                self.assertIn(f"Runs/{session.run_id}.md", {doc["path"] for doc in package["vault_documents"]})
                exported = json.loads(Path(package["path"]).read_text(encoding="utf-8"))
                self.assertEqual(exported["package_sha256"], package["package_sha256"])
                with self.assertRaises(ValueError):
                    coordinator.steer_run(
                        session.run_id,
                        {
                            "command": "override_review",
                            "override_event_id": override_event.event_id,
                            "verdict": "accepted",
                            "reason": "override operator cannot self-review",
                            "_operator": {
                                "operator_id": "approver@example.com",
                                "roles": ["approver"],
                                "source": "proxy_header",
                            },
                        },
                    )
                override_reviewed = coordinator.steer_run(
                    session.run_id,
                    {
                        "command": "override_review",
                        "override_event_id": override_event.event_id,
                        "verdict": "accepted",
                        "reason": "override was bounded to the documented rollout reduction",
                        "findings": ["override event and package timeline match"],
                        "action_items": ["review override in pilot postmortem"],
                        "_operator": {
                            "operator_id": "override-reviewer@example.com",
                            "roles": ["viewer"],
                            "source": "proxy_header",
                        },
                    },
                )
                self.assertEqual(
                    override_reviewed["artifacts"]["override_reviews"][-1]["schema_version"],
                    "mesh.override_review.v1",
                )
                self.assertTrue(override_reviewed["artifacts"]["override_reviews"][-1]["independent_reviewer"])
                with self.assertRaises(ValueError):
                    coordinator.steer_run(
                        session.run_id,
                        {
                            "command": "postmortem_review",
                            "verdict": "accepted",
                            "findings": ["launcher cannot self-review"],
                            "_operator": {
                                "operator_id": "launcher@example.com",
                                "roles": ["launcher"],
                                "source": "proxy_header",
                            },
                        },
                    )
                reviewed = coordinator.steer_run(
                    session.run_id,
                    {
                        "command": "postmortem_review",
                        "verdict": "accepted",
                        "findings": ["timeline, Merkle proof, and export package reviewed"],
                        "action_items": ["carry proof into pilot readout"],
                        "reviewed_export_id": package["export_id"],
                        "reviewed_package_sha256": package["package_sha256"],
                        "_operator": {
                            "operator_id": "reviewer@example.com",
                            "roles": ["viewer"],
                            "source": "proxy_header",
                        },
                    },
                )
                self.assertEqual(reviewed["artifacts"]["postmortem_reviews"][-1]["schema_version"], "mesh.postmortem_review.v1")
                self.assertTrue(reviewed["artifacts"]["postmortem_reviews"][-1]["independent_reviewer"])
                package = coordinator.export_run_package(session.run_id)
                assert package is not None
                self.assertEqual(
                    package["override_review_records"][-1]["reviewer"]["operator_id"],
                    "override-reviewer@example.com",
                )
                self.assertIn("## Override Reviews", package["postmortem_markdown"])
                self.assertEqual(package["postmortem_review_records"][-1]["reviewer"]["operator_id"], "reviewer@example.com")
                self.assertIn("## Postmortem Reviews", package["postmortem_markdown"])
                current = coordinator.state_store.get_run_session(session.run_id)
                assert current is not None
                self.assertIn("run_export_package", current.artifacts)

                archive = coordinator.export_run_archive(session.run_id)
                self.assertIsNotNone(archive)
                assert archive is not None
                self.assertTrue(Path(archive["path"]).is_file())
                self.assertRegex(archive["sha256"], r"^[0-9a-f]{64}$")
                with zipfile.ZipFile(archive["path"]) as zipped:
                    names = set(zipped.namelist())
                    self.assertIn("manifest.json", names)
                    self.assertIn("package.json", names)
                    self.assertIn("timeline.json", names)
                    self.assertIn("postmortem.md", names)
                    self.assertIn("records/decision.json", names)
                    self.assertIn("records/override-reviews.json", names)
                    self.assertIn("records/postmortem-reviews.json", names)
                    manifest = json.loads(zipped.read("manifest.json").decode("utf-8"))
                    self.assertEqual(manifest["archive_version"], "mesh.run_export_archive.v1")
                    self.assertEqual(manifest["run_id"], session.run_id)
                    self.assertEqual(manifest["retention"]["retention_days"], 30)
            finally:
                coordinator.stop_background_workers()

    def test_run_export_derives_approval_records_from_steering_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                session = coordinator.state_store.create_run_session(
                    goal_id=coordinator.state_store.ensure_default_goal().goal_id,
                    scenario_key="approval_event_export",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "decision": {"decision_type": "rollback_deployment"},
                        "evaluation": {"passed": True, "final_recommendation": "execute"},
                        "execution": {"status": "succeeded"},
                        "feedback": {"outcome": "successful"},
                    },
                )
                approval_event = coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="awaiting_operator",
                    event_type="steering_command",
                    payload={
                        "command_id": "cmd_approve_1",
                        "run_id": session.run_id,
                        "command_type": "approve",
                        "issued_at": "2026-05-06T00:00:00Z",
                        "payload": {"summary": "operator approval"},
                        "operator": {
                            "operator_id": "approver@example.com",
                            "roles": ["approver"],
                            "source": "proxy_header",
                        },
                    },
                    artifact_key="operator_command",
                    status="received",
                )
                current = coordinator.state_store.get_run_session(session.run_id)
                assert current is not None
                current.stage = "completed"
                current.status = "completed"
                coordinator.state_store.save_run_session(current)

                package = coordinator.export_run_package(session.run_id)

                assert package is not None
                self.assertEqual(package["approval_records"][0]["event_id"], approval_event.event_id)
                self.assertEqual(package["approval_records"][0]["command_type"], "approve")
                self.assertEqual(package["approval_records"][0]["operator"]["operator_id"], "approver@example.com")
            finally:
                coordinator.stop_background_workers()

    def test_run_export_package_compacts_large_payloads_under_size_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp, vault_mirror_mode="sync", run_export_max_bytes=12000))
            try:
                session = coordinator.state_store.create_run_session(
                    goal_id=coordinator.state_store.ensure_default_goal().goal_id,
                    scenario_key="large_export",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=[],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "input_signal": {"service": "search", "payload": "x" * 20_000},
                        "decision": {"decision_type": "noop"},
                        "evaluation": {"passed": True},
                        "execution": {"status": "skipped"},
                        "feedback": {"outcome": "not_applicable"},
                    },
                )
                session.operator_notes.append("operator note " + ("y" * 20_000))
                coordinator.state_store.save_run_session(session)
                coordinator.state_store.append_run_event(
                    session.run_id,
                    stage="completed",
                    event_type="run_completed",
                    payload={"blob": "z" * 20_000, "token": "secret-token"},
                    status="completed",
                )
                session = coordinator.state_store.get_run_session(session.run_id)
                assert session is not None
                session.stage = "completed"
                session.status = "completed"
                coordinator.state_store.save_run_session(session)

                package = coordinator.export_run_package(session.run_id)

                self.assertIsNotNone(package)
                assert package is not None
                encoded = json.dumps(package, sort_keys=True, default=str).encode("utf-8")
                self.assertLessEqual(len(encoded), 12000)
                self.assertTrue(package["size_control"]["truncated"])
                self.assertIn("vault_documents", package["size_control"]["omitted_fields"])
                self.assertIn("timeline_json", package["size_control"]["omitted_fields"])
                self.assertEqual(package["timeline_json"][0]["payload"], {"omitted": "run export size cap"})
                self.assertTrue(Path(package["path"]).is_file())
            finally:
                coordinator.stop_background_workers()


class PilotFeedbackGateTests(unittest.TestCase):
    def test_live_feedback_required_escalates_when_only_stub_observations_exist(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        normalized = IngestService().normalize_signal(signal)
        trigger = TriggerService().detect(normalized)
        self.assertIsNotNone(trigger)
        assert trigger is not None
        decision = DecisionService().decide(trigger)
        execution = ExecutionRecord(
            execution_id="exec_test",
            decision_id=decision.decision_id,
            started_at=signal["observed_at"],
            completed_at=signal["observed_at"],
            executor="native",
            status="succeeded",
            idempotency_key="exec_test",
            applied_action=decision.execution_plan,
            external_refs={"flag_change_id": "ffchg_test"},
        )

        feedback = FeedbackService(require_live_observations=True).record(
            trigger,
            decision,
            execution,
            normalized,
        )

        self.assertEqual(feedback.outcome, "escalated")
        self.assertTrue(feedback.metric_comparison["live_feedback_required"])
        self.assertFalse(feedback.metric_comparison["live_feedback_source_present"])


if __name__ == "__main__":
    unittest.main()
