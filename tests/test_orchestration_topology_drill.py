from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.integrations import build_readiness
from shared.mesh_runtime.orchestration_drill import (
    build_orchestration_topology_drill_packet,
    orchestration_topology_drill_ready,
    verify_orchestration_topology_drill,
)


class OrchestrationTopologyDrillTests(unittest.TestCase):
    def test_orchestration_topology_drill_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "orchestration-topology-drill.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_orchestration_topology_drill(proof_path)

        self.assertEqual(result["schema_version"], "mesh.orchestration_topology_drill_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checks"]["multi_lane_topology"])
        self.assertTrue(result["checks"]["bounded_action_lanes_certified"])

    def test_orchestration_topology_drill_blocks_local_single_lane_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof = _proof()
            proof["environment"] = "local"
            proof["state_backend"] = "file"
            proof["topology_resolution"]["selected_agents"] = ["hermes"]
            proof["topology_resolution"]["selected_lanes"] = [proof["topology_resolution"]["selected_lanes"][0]]
            proof_path = Path(tmp) / "orchestration-topology-drill.json"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_orchestration_topology_drill(proof_path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["production_like_environment"])
        self.assertFalse(result["checks"]["postgres_state_backend"])
        self.assertFalse(result["checks"]["multi_lane_topology"])
        self.assertFalse(orchestration_topology_drill_ready(proof_path))

    def test_non_kubernetes_bounded_action_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof = _proof()
            proof["topology_resolution"]["selected_lanes"][1]["lane_id"] = "n8n"
            proof_path = Path(tmp) / "orchestration-topology-drill.json"
            proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = verify_orchestration_topology_drill(proof_path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["bounded_action_lanes_certified"])

    def test_expansion_readiness_requires_orchestration_topology_drill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            readiness = build_readiness(
                RuntimeConfig(
                    state_directory=tmp,
                    vault_path=str(Path(tmp) / "vault"),
                    readiness_profile="expansion",
                    orchestration_topology_drill_path=str(Path(tmp) / "missing-topology-drill.json"),
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("orchestration_topology_drill_verified", readiness["blockers"])

    def test_cli_verifies_orchestration_topology_drill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof_path = Path(tmp) / "orchestration-topology-drill.json"
            proof_path.write_text(json.dumps(_proof(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_orchestration_topology_drill.py",
                    "--proof",
                    str(proof_path),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass")

    def test_builds_drill_packet_from_run_export(self) -> None:
        packet = build_orchestration_topology_drill_packet(
            run_export=_run_export(),
            operator_id="platform@example.com",
            environment="staging",
            state_backend="postgres",
            profile_ref="config/orchestration-topology.profile.json",
            operator_approval_recorded=True,
            bounded_action_execution_ref="execution://kubernetes/rollback/run_topology_drill",
            drill_id="generated_topology_drill",
        )

        self.assertEqual(packet["schema_version"], "mesh.orchestration_topology_drill.v1")
        self.assertEqual(packet["run_id"], "run_topology_drill")
        self.assertEqual(packet["topology_resolution"]["version"], "mesh.orchestration_topology_resolution.v1")
        self.assertIn("artifact://lane_routing", packet["evidence_refs"])
        self.assertIn("artifact://agent_tasks", packet["evidence_refs"])

    def test_generator_cli_builds_and_verifies_drill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_export_path = Path(tmp) / "run-export.json"
            output_path = Path(tmp) / "topology-drill.json"
            run_export_path.write_text(json.dumps(_run_export(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_orchestration_topology_drill.py",
                    "--run-export",
                    str(run_export_path),
                    "--output",
                    str(output_path),
                    "--operator-id",
                    "platform@example.com",
                    "--operator-approval-recorded",
                    "--bounded-action-execution-ref",
                    "execution://kubernetes/rollback/run_topology_drill",
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        packet = json.loads(completed.stdout)
        self.assertEqual(packet["schema_version"], "mesh.orchestration_topology_drill.v1")
        self.assertTrue(packet["drill_id"].startswith("orchestration_topology_drill_"))


def _proof() -> dict:
    return {
        "schema_version": "mesh.orchestration_topology_drill.v1",
        "drill_id": "orchestration_topology_drill_test",
        "generated_at": "2026-05-06T12:00:00Z",
        "environment": "staging",
        "operator_id": "platform@example.com",
        "state_backend": "postgres",
        "run_id": "run_topology_drill",
        "run_export_ref": "run-export://topology/staging/run_topology_drill",
        "readiness_ref": "artifact://integration_readiness",
        "profile_ref": "config/orchestration-topology.profile.json",
        "operator_approval_recorded": True,
        "bounded_action_execution_ref": "execution://kubernetes/rollback/run_topology_drill",
        "topology_resolution": {
            "version": "mesh.orchestration_topology_resolution.v1",
            "active_topology": "hybrid",
            "rule_id": "search-hybrid",
            "routing_reason": "search rollback uses durable workflow plus Kubernetes actuator lane",
            "selected_agents": ["temporal", "kubernetes"],
            "selected_lanes": [
                {
                    "lane_id": "temporal",
                    "role": "hybrid_lane",
                    "topology_role": "supervisor_lane",
                    "model_binding": {
                        "supported": False,
                        "binding_status": "not_supported",
                        "provider": "none",
                        "model": "none",
                        "secret_material_present": False,
                    },
                    "authority": "proposal_only",
                    "certified_state": "proposal-only",
                    "source_evidence": {
                        "profile_rule_ref": "config/orchestration-topology.profile.json#rules.search-hybrid",
                        "connector_certification_ref": "config/connector-certification.registry.json#temporal",
                    },
                    "reconciliation_mode": "supervisor_summary_before_mesh_reconciliation",
                    "blockers": [],
                },
                {
                    "lane_id": "kubernetes",
                    "role": "hybrid_lane",
                    "topology_role": "bounded_actuator_lane",
                    "model_binding": {
                        "supported": False,
                        "binding_status": "not_supported",
                        "provider": "none",
                        "model": "none",
                        "secret_material_present": False,
                    },
                    "authority": "bounded_action",
                    "certified_state": "pilot-ready",
                    "source_evidence": {
                        "profile_rule_ref": "config/orchestration-topology.profile.json#rules.search-hybrid",
                        "connector_certification_ref": "config/connector-certification.registry.json#kubernetes",
                    },
                    "reconciliation_mode": "bounded_action_evidence",
                    "blockers": [],
                },
            ],
            "reconciliation": "mesh_reconciles_per_rule_topology_outputs",
            "source_evidence": {
                "organization_profile": {"matched": True, "domain": "platform_sre"},
                "ownership_boundary": {"matched": True, "tenant_id": "tenant_a"},
                "connector_certification": {"kubernetes": {"state": "pilot-ready"}},
                "policy_lifecycle": {"source_ref": "config/policy-lifecycle.manifest.json"},
                "threat_model": {"source_ref": "config/threat-model.register.json"},
                "readiness": {"status": "ready"},
                "historical_outcomes": {"source_ref": "state://runs"},
                "trust_ladder": {"source_ref": "state://learning/trust_ladder.json"},
            },
        },
        "evidence_refs": [
            "artifact://lane_routing",
            "artifact://agent_tasks",
            "artifact://integration_readiness",
        ],
        "raw_secret_material_present": False,
    }


def _run_export() -> dict:
    proof = _proof()
    topology = proof["topology_resolution"]
    return {
        "package_version": "mesh.run_export.v1",
        "run_id": "run_topology_drill",
        "export_id": "run_export_topology_drill",
        "artifacts": {
            "lane_routing": topology,
            "agent_tasks": [
                {
                    "task_id": "task_run_topology_drill_root_cause",
                    "orchestration_topology": topology,
                }
            ],
            "integration_readiness": {"status": "ready"},
        },
    }


if __name__ == "__main__":
    unittest.main()
