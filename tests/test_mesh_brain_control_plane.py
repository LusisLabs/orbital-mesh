from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from urllib.request import Request, urlopen

from mesh_brain import (
    MESH_BRAIN_BACKEND_MATRIX_ARTIFACT_KEYS,
    MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS,
    MESH_BRAIN_MODEL_KERNEL_ARTIFACT_KEYS,
    MESH_BRAIN_ROLLBACK_DRILL_ARTIFACT_KEYS,
    backend_matrix_to_run_record,
    build_backend_matrix_artifact_bundle,
    build_live_serving_artifact_bundle,
    build_model_kernel_artifact_bundle,
    build_rollback_drill_artifact_bundle,
    live_serving_smoke_to_run_record,
    model_kernel_probe_to_run_record,
    rollback_drill_to_run_record,
    run_model_kernel_probe,
    verify_production_artifact_record,
)
from control_plane_server import start_server_in_thread
from mesh_brain.backend_matrix import BackendMatrixTarget, run_backend_matrix_smoke
from mesh_brain.rollback_drill import run_mesh_brain_rollback_drill
from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig


class MeshBrainControlPlaneTests(unittest.TestCase):
    def test_model_kernel_probe_converts_to_artifact_bundle_and_run_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_model_kernel_probe(output_directory=Path(temp_dir), benchmark_iterations=20)
            bundle = build_model_kernel_artifact_bundle(result=result)
            run_record = model_kernel_probe_to_run_record(
                result=result,
                bundle=bundle,
                run_id="run_model_kernel_1",
            )

        self.assertEqual(set(bundle.artifacts), set(MESH_BRAIN_MODEL_KERNEL_ARTIFACT_KEYS))
        self.assertEqual(bundle.workflow_id, result.result_id)
        self.assertEqual(bundle.tenant_id, "mesh_system")
        self.assertEqual(bundle.release_decision, "pass")
        self.assertFalse(bundle.deployment_record["deployed"])
        self.assertEqual(bundle.deployment_record["deterministic_digest"], result.correctness.deterministic_digest)
        self.assertTrue(all(ref.exists for ref in bundle.artifacts.values()))
        self.assertTrue(all(ref.sha256 for ref in bundle.artifacts.values()))
        self.assertEqual(run_record["run_id"], "run_model_kernel_1")
        self.assertEqual(run_record["stage"], "completed")
        self.assertEqual(run_record["final_release_decision"], "pass")
        self.assertIn("max_gradient_relative_error", run_record["summary_metrics"])

    def test_coordinator_records_model_kernel_probe_as_completed_mesh_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                run = coordinator.run_mesh_brain_model_kernel_probe({"benchmark_iterations": 20})
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()
            artifact_records = json.loads((Path(temp_dir) / "artifacts.json").read_text(encoding="utf-8"))["artifacts"]

        self.assertEqual(run["scenario_key"], "mesh_brain_model_kernel_probe")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["evaluation_mode"], "mesh_brain_model_kernel")
        self.assertIn("mesh_brain_model_kernel_run_record", run["artifacts"])
        self.assertIn("mesh_brain_model_kernel_probe_summary", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_model_kernel_run_record"]["final_release_decision"], "pass")
        self.assertEqual([event.event_type for event in events], ["run_queued", "integration_artifact_recorded", "run_completed"])
        self.assertIn("mesh_brain_model_kernel_probe_summary", {record["artifact_key"] for record in artifact_records})

    def test_coordinator_registers_model_kernel_artifacts_with_durable_uris_when_configured(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                mesh_brain_artifact_uri_prefix="s3://mesh-prod-artifacts/mesh-brain",
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                run = coordinator.run_mesh_brain_model_kernel_probe({"benchmark_iterations": 20})
            finally:
                coordinator.stop_background_workers()
            artifact_records = json.loads((Path(temp_dir) / "artifacts.json").read_text(encoding="utf-8"))["artifacts"]

        mesh_brain_records = [record for record in artifact_records if str(record.get("artifact_key", "")).startswith("mesh_brain_")]
        self.assertEqual(run["stage"], "completed")
        self.assertTrue(mesh_brain_records)
        self.assertTrue(all(str(record["uri"]).startswith("s3://mesh-prod-artifacts/mesh-brain/") for record in mesh_brain_records))
        self.assertTrue(all(verify_production_artifact_record(record)["status"] == "pass" for record in mesh_brain_records))

    def test_http_route_records_model_kernel_probe_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/mesh-brain/model-kernel-probe",
                    data=json.dumps({"benchmark_iterations": 20}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["scenario_key"], "mesh_brain_model_kernel_probe")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifacts"]["mesh_brain_model_kernel_run_record"]["final_release_decision"], "pass")

    def test_coordinator_records_meshmodel_probe_as_blocked_governance_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                run = coordinator.run_mesh_brain_meshmodel_probe({})
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
                go_no_go = coordinator.generate_pilot_go_no_go()
            finally:
                coordinator.stop_background_workers()
            artifact_records = json.loads((Path(temp_dir) / "artifacts.json").read_text(encoding="utf-8"))["artifacts"]

        self.assertEqual(run["scenario_key"], "mesh_brain_meshmodel_probe")
        self.assertEqual(run["stage"], "failed")
        self.assertEqual(run["status"], "blocked")
        self.assertIn("mesh_brain_meshmodel_run_record", run["artifacts"])
        self.assertIn("mesh_brain_meshmodel_rgs_evidence_binding", run["artifacts"])
        self.assertIn("mesh_brain_meshmodel_release_readiness", run["artifacts"])
        record = run["artifacts"]["mesh_brain_meshmodel_run_record"]
        self.assertEqual(record["final_release_decision"], "block")
        self.assertEqual(record["rgs_evidence_binding"]["status"], "blocked")
        self.assertIn("rgs_evidence_source_not_configured", record["release_readiness"]["blockers"])
        self.assertIn("rgs_cl12_live_external_runtime_not_admitted", record["release_readiness"]["blockers"])
        self.assertFalse(record["deployment_record"]["deployed"])
        self.assertFalse(record["deployment_record"]["production_serving"])
        self.assertFalse(record["deployment_record"]["policy_bypass"])
        self.assertEqual(record["policy_events"][0]["decision"], "block_release")
        self.assertIn("policy_decision", [event.event_type for event in events])
        self.assertIn(
            "mesh_brain_meshmodel_probe_summary",
            {artifact["artifact_key"] for artifact in artifact_records},
        )
        self.assertNotIn("mesh_brain_meshmodel_run_ids", go_no_go["observed"])

    def test_http_route_records_meshmodel_advisory_without_production_readiness(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/mesh-brain/meshmodel-probe",
                    data=json.dumps(
                        {
                            "rgs_evidence": {
                                "status": "pass",
                                "local_repo_commit": "a9ec57b7a74643b27c5b908add21704ebbc26767",
                                "bounded_breakthrough_evidence_admitted": True,
                                "threshold_admitted": False,
                                "full_live_external_runtime_threshold_admitted": False,
                                "claim_boundary": {
                                    "cl12_live_external_runtime_replication": False,
                                    "production_authority": False,
                                    "serving_authority": False,
                                },
                                "blocked_items": [
                                    {
                                        "item": "live_external_runtime_replication",
                                        "state_slice": "breakthrough-threshold-audit",
                                    }
                                ],
                            },
                            "release_readiness": {
                                "release_decision": "advisory_governance_candidate",
                                "blockers": [],
                            }
                        }
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-Mesh-Operator": "local-admin",
                        "X-Mesh-Roles": "admin",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                go_no_go_request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/pilot/go-no-go",
                    headers={"X-Mesh-Operator": "local-admin", "X-Mesh-Roles": "admin"},
                )
                with urlopen(go_no_go_request, timeout=10) as response:
                    go_no_go = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["scenario_key"], "mesh_brain_meshmodel_probe")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["status"], "completed")
        record = payload["artifacts"]["mesh_brain_meshmodel_run_record"]
        self.assertEqual(record["final_release_decision"], "advisory_governance_candidate")
        self.assertFalse(record["deployment_record"]["deployed"])
        self.assertFalse(record["deployment_record"]["production_serving"])
        self.assertFalse(record["deployment_record"]["promotion_authority"])
        self.assertEqual(record["rgs_evidence_binding"]["status"], "advisory_ready")
        self.assertTrue(record["rgs_evidence_binding"]["bounded_breakthrough_evidence_admitted"])
        self.assertFalse(record["rgs_evidence_binding"]["cl12_live_external_runtime_replication_admitted"])
        self.assertIn("production_serving_disabled", record["release_readiness"]["blockers"])
        self.assertIn("rgs_cl12_live_external_runtime_not_admitted", record["release_readiness"]["blockers"])
        self.assertNotIn("mesh_brain_meshmodel_run_ids", go_no_go["observed"])

    def test_live_serving_smoke_converts_to_artifact_bundle_and_run_record(self) -> None:
        from mesh_brain.run_live_serving_smoke import run_live_serving_smoke

        with TemporaryDirectory() as temp_dir:
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                summary = run_live_serving_smoke(
                    base_url="http://127.0.0.1:1234",
                    model="nvidia/nemotron-3-nano-4b",
                    output_directory=Path(temp_dir),
                    deterministic_release_decision="canary",
                )
            bundle = build_live_serving_artifact_bundle(summary=summary)
            run_record = live_serving_smoke_to_run_record(
                summary=summary,
                bundle=bundle,
                run_id="run_live_smoke_1",
            )

        self.assertEqual(set(bundle.artifacts), set(MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS))
        self.assertEqual(bundle.release_decision, "canary")
        self.assertEqual(bundle.deployment_record["status"], "eligible_for_canary")
        self.assertTrue(all(ref.exists for ref in bundle.artifacts.values()))
        self.assertTrue(all(ref.sha256 for ref in bundle.artifacts.values()))
        self.assertEqual(run_record["run_id"], "run_live_smoke_1")
        self.assertEqual(run_record["stage"], "completed")
        self.assertEqual(run_record["final_release_decision"], "canary")
        self.assertEqual(run_record["summary_metrics"]["live_smoke_gate"], "pass")
        self.assertEqual(run_record["summary_metrics"]["live_response_eval"], "pass")
        self.assertEqual(run_record["summary_metrics"]["live_judge_eval"], "pass")

    def test_coordinator_records_live_serving_smoke_as_completed_mesh_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                    run = coordinator.run_mesh_brain_live_serving_smoke(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    )
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()
            artifact_records = json.loads((Path(temp_dir) / "artifacts.json").read_text(encoding="utf-8"))["artifacts"]

        self.assertEqual(run["scenario_key"], "mesh_brain_live_serving_smoke")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["evaluation_mode"], "mesh_brain_live_serving_smoke")
        self.assertIn("mesh_brain_live_serving_run_record", run["artifacts"])
        self.assertIn("mesh_brain_live_serving_summary", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_live_serving_run_record"]["final_release_decision"], "canary")
        self.assertEqual([event.event_type for event in events], ["run_queued", "integration_artifact_recorded", "run_completed"])
        self.assertIn("mesh_brain_live_serving_summary", {record["artifact_key"] for record in artifact_records})

    def test_coordinator_uses_configured_live_serving_backend_defaults(self) -> None:
        requested_urls: list[str] = []

        def fake_urlopen(request: Any, timeout: float) -> _FakeOpenAIResponse:
            requested_urls.append(str(request.full_url))
            return _fake_live_urlopen(request, timeout)

        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                mesh_brain_serving_base_url="http://mesh-brain-serving.private:8000",
                mesh_brain_serving_model="nvidia/nemotron-3-nano-4b",
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
                    run = coordinator.run_mesh_brain_live_serving_smoke({"deterministic_release_decision": "canary"})
            finally:
                coordinator.stop_background_workers()

        self.assertEqual(run["stage"], "completed")
        self.assertEqual(requested_urls, ["http://mesh-brain-serving.private:8000/v1/chat/completions"])

    def test_coordinator_blocks_live_serving_smoke_on_infrastructure_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=RuntimeError("backend down")):
                    run = coordinator.run_mesh_brain_live_serving_smoke(
                        {"base_url": "http://127.0.0.1:1234", "model": "nvidia/nemotron-3-nano-4b"}
                    )
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()

        self.assertEqual(run["stage"], "failed")
        self.assertEqual(run["status"], "failed")
        self.assertIn("mesh_brain_live_serving_failure", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_live_serving_failure"]["release_decision"], "block")
        self.assertEqual([event.event_type for event in events], ["run_queued", "run_failed"])

    def test_http_route_records_live_serving_smoke_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/mesh-brain/live-serving-smoke",
                    data=json.dumps(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                    with urlopen(request, timeout=10) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["scenario_key"], "mesh_brain_live_serving_smoke")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifacts"]["mesh_brain_live_serving_run_record"]["final_release_decision"], "canary")

    def test_rollback_drill_converts_to_artifact_bundle_and_run_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_mesh_brain_rollback_drill(output_directory=Path(temp_dir), tenant_id="tenant_a", task_type="crops")
            bundle = build_rollback_drill_artifact_bundle(result=result)
            run_record = rollback_drill_to_run_record(result=result, bundle=bundle, run_id="run_rollback_1")

        self.assertEqual(set(bundle.artifacts), set(MESH_BRAIN_ROLLBACK_DRILL_ARTIFACT_KEYS))
        self.assertEqual(bundle.release_decision, "pass")
        self.assertEqual(bundle.deployment_record["restored_artifact_id"], result.previous_artifact_id)
        self.assertTrue(all(ref.exists for ref in bundle.artifacts.values()))
        self.assertTrue(all(ref.sha256 for ref in bundle.artifacts.values()))
        self.assertEqual(run_record["run_id"], "run_rollback_1")
        self.assertEqual(run_record["stage"], "completed")
        self.assertEqual(run_record["summary_metrics"]["restored_previous_artifact"], True)
        self.assertEqual(len(run_record["audit_events"]), 3)

    def test_coordinator_records_rollback_drill_as_completed_mesh_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                run = coordinator.run_mesh_brain_rollback_drill({"tenant_id": "tenant_a", "task_type": "crops"})
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()
            artifact_records = json.loads((Path(temp_dir) / "artifacts.json").read_text(encoding="utf-8"))["artifacts"]

        self.assertEqual(run["scenario_key"], "mesh_brain_rollback_drill")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["evaluation_mode"], "mesh_brain_rollback_drill")
        self.assertIn("mesh_brain_rollback_drill_run_record", run["artifacts"])
        self.assertIn("mesh_brain_rollback_drill_summary", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_rollback_drill_run_record"]["final_release_decision"], "pass")
        self.assertEqual([event.event_type for event in events], ["run_queued", "integration_artifact_recorded", "run_completed"])
        self.assertIn("mesh_brain_rollback_drill_summary", {record["artifact_key"] for record in artifact_records})

    def test_http_route_records_rollback_drill_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/mesh-brain/rollback-drill",
                    data=json.dumps({"tenant_id": "tenant_a", "task_type": "crops"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["scenario_key"], "mesh_brain_rollback_drill")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifacts"]["mesh_brain_rollback_drill_run_record"]["final_release_decision"], "pass")

    def test_backend_matrix_converts_to_artifact_bundle_and_run_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                summary = run_backend_matrix_smoke(
                    targets=[BackendMatrixTarget(name="primary", base_url="http://127.0.0.1:1234")],
                    output_directory=Path(temp_dir),
                    deterministic_release_decision="canary",
                )
            bundle = build_backend_matrix_artifact_bundle(summary=summary)
            run_record = backend_matrix_to_run_record(summary=summary, bundle=bundle, run_id="run_backend_matrix_1")

        self.assertEqual(set(bundle.artifacts), set(MESH_BRAIN_BACKEND_MATRIX_ARTIFACT_KEYS) - {"mesh_brain_backend_matrix_record"})
        self.assertEqual(bundle.release_decision, "pass")
        self.assertEqual(bundle.deployment_record["result_count"], 1)
        self.assertTrue(all(ref.exists for ref in bundle.artifacts.values()))
        self.assertTrue(all(ref.sha256 for ref in bundle.artifacts.values()))
        self.assertEqual(run_record["run_id"], "run_backend_matrix_1")
        self.assertEqual(run_record["stage"], "completed")
        self.assertEqual(run_record["summary_metrics"]["passed_count"], 1)

    def test_coordinator_records_backend_matrix_as_completed_mesh_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            coordinator = RunCoordinator(config)
            try:
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                    coordinator.run_mesh_brain_live_serving_smoke(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    )
                    run = coordinator.run_mesh_brain_backend_matrix(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    )
                events = coordinator.state_store.list_run_events(str(run["run_id"]))
            finally:
                coordinator.stop_background_workers()
            artifact_records = json.loads((Path(temp_dir) / "artifacts.json").read_text(encoding="utf-8"))["artifacts"]

        self.assertEqual(run["scenario_key"], "mesh_brain_backend_matrix")
        self.assertEqual(run["stage"], "completed")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["evaluation_mode"], "mesh_brain_backend_matrix")
        self.assertIn("mesh_brain_backend_matrix_record", run["artifacts"])
        self.assertIn("mesh_brain_backend_matrix_summary", run["artifacts"])
        self.assertEqual(run["artifacts"]["mesh_brain_backend_matrix_record"]["final_release_decision"], "pass")
        self.assertEqual([event.event_type for event in events], ["run_queued", "integration_artifact_recorded", "run_completed"])
        self.assertIn("mesh_brain_backend_matrix_summary", {record["artifact_key"] for record in artifact_records})

    def test_coordinator_rejects_backend_matrix_before_stable_live_smoke(self) -> None:
        with TemporaryDirectory() as temp_dir:
            coordinator = RunCoordinator(
                RuntimeConfig(
                    state_directory=temp_dir,
                    vault_path=str(Path(temp_dir) / "vault"),
                    integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                    promptfoo_command="/missing/promptfoo",
                    hermes_command="/missing/hermes",
                    goose_command="/missing/goose",
                    evo_command="/missing/evo",
                )
            )
            try:
                with self.assertRaisesRegex(ValueError, "prior stable live serving smoke"):
                    coordinator.run_mesh_brain_backend_matrix(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    )
            finally:
                coordinator.stop_background_workers()

    def test_http_route_records_backend_matrix_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                vault_path=str(Path(temp_dir) / "vault"),
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                server_host="127.0.0.1",
                server_port=0,
                promptfoo_command="/missing/promptfoo",
                hermes_command="/missing/hermes",
                goose_command="/missing/goose",
                evo_command="/missing/evo",
            )
            server, thread = start_server_in_thread(config, start_sidecar=False)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/mesh-brain/backend-matrix",
                    data=json.dumps(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=_fake_live_urlopen):
                    server.coordinator.run_mesh_brain_live_serving_smoke(
                        {
                            "base_url": "http://127.0.0.1:1234",
                            "model": "nvidia/nemotron-3-nano-4b",
                            "deterministic_release_decision": "canary",
                        }
                    )
                    with urlopen(request, timeout=10) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["scenario_key"], "mesh_brain_backend_matrix")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifacts"]["mesh_brain_backend_matrix_record"]["final_release_decision"], "pass")


class _FakeOpenAIResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeOpenAIResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _fake_live_urlopen(request: Any, timeout: float) -> _FakeOpenAIResponse:
    return _FakeOpenAIResponse(
        {
            "id": "chatcmpl_live_control_plane_test",
            "model": "nvidia/nemotron-3-nano-4b",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Evidence indicates CROPS search latency. Use bounded reversible remediation, "
                            "keep rollback ready, and require operator approval before restart."
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 24, "total_tokens": 34},
        }
    )


if __name__ == "__main__":
    unittest.main()
