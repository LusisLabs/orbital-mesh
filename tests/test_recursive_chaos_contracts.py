from __future__ import annotations

import copy
import subprocess
import sys
import unittest

from shared.mesh_runtime import (
    RECURSIVE_CHAOS_SAFETY_CLASSES,
    RecursiveChaosArenaProfile,
    RecursiveChaosCyclePacket,
    RecursiveChaosEvidenceBundle,
    RecursiveChaosExperimentManifest,
    RecursiveChaosGhostRecoveryPacket,
    RecursiveChaosLearningPacket,
    SchemaValidationError,
    load_schema,
    validate_payload,
)
from shared.mesh_runtime.recursive_chaos import (
    P0_ARENA_PROFILE_IDS,
    REQUIRED_ARENA_PROFILE_IDS,
    get_recursive_chaos_arena_profile,
    load_recursive_chaos_arena_profiles,
    resolve_recursive_chaos_safety_class,
    validate_arena_evidence_bundle,
    validate_chaos_learning_packet,
    validate_ghost_state_recovery_packet,
    validate_recursive_chaos_cycle_packet,
    validate_recursive_chaos_experiment_manifest,
    verify_recursive_chaos_arena_profiles,
)


class RecursiveChaosContractTests(unittest.TestCase):
    def test_recursive_chaos_schemas_are_loadable(self) -> None:
        expected_titles = {
            "recursive-chaos-arena-profiles.schema.json": "RecursiveChaosArenaProfiles",
            "recursive-chaos-arena-profile.schema.json": "RecursiveChaosArenaProfile",
            "recursive-chaos-experiment-manifest.schema.json": "RecursiveChaosExperimentManifest",
            "recursive-chaos-cycle-packet.schema.json": "RecursiveChaosCyclePacket",
            "recursive-chaos-ghost-recovery-packet.schema.json": "RecursiveChaosGhostRecoveryPacket",
            "recursive-chaos-learning-packet.schema.json": "RecursiveChaosLearningPacket",
            "recursive-chaos-evidence-bundle.schema.json": "RecursiveChaosEvidenceBundle",
            "recursive-chaos-automation-summary.schema.json": "RecursiveChaosAutomationSummary",
            "recursive-chaos-feedback-gate.schema.json": "RecursiveChaosFeedbackGate",
            "recursive-chaos-sandbox-execution-summary.schema.json": "RecursiveChaosSandboxExecutionSummary",
        }
        for schema_name, title in expected_titles.items():
            with self.subTest(schema_name=schema_name):
                self.assertEqual(load_schema(schema_name)["title"], title)

    def test_default_profile_registry_covers_priority_arenas_without_production_mutation(self) -> None:
        registry = load_recursive_chaos_arena_profiles()
        result = verify_recursive_chaos_arena_profiles()

        self.assertEqual(result["status"], "pass")
        self.assertEqual(set(result["profile_ids"]), REQUIRED_ARENA_PROFILE_IDS)
        self.assertEqual(set(result["p0_profile_ids"]), P0_ARENA_PROFILE_IDS)
        self.assertEqual(len(registry["profiles"]), 16)
        for profile in registry["profiles"]:
            self.assertFalse(profile["production_mutation_allowed"], profile["profile_id"])
            self.assertEqual(profile["profile_id"], profile["arena_domain"])
            self.assertGreater(len(profile["existing_mesh_surfaces"]), 0)
            self.assertGreater(len(profile["ghost_state_bindings"]), 0)
            self.assertGreater(len(profile["learning_outputs"]), 0)
        validate_payload("recursive-chaos-arena-profiles.schema.json", registry)

    def test_hetzner_targets_resolve_to_probe_only(self) -> None:
        profile = get_recursive_chaos_arena_profile("kubernetes_service_platform")

        self.assertEqual(resolve_recursive_chaos_safety_class(profile, "hetzner"), "production_probe_only")
        self.assertIn("production_mutating_blocked", RECURSIVE_CHAOS_SAFETY_CLASSES)

    def test_arena_profile_contract_bounds_safety_classes(self) -> None:
        payload = _arena_profile()
        model = RecursiveChaosArenaProfile.from_dict(payload)

        self.assertEqual(model.safety_class, "production_probe_only")

        mutated = copy.deepcopy(payload)
        mutated["safety_class"] = "hetzner_mutating"
        with self.assertRaises(SchemaValidationError):
            validate_payload("recursive-chaos-arena-profile.schema.json", mutated)

    def test_experiment_manifest_requires_sealed_mesh_integration(self) -> None:
        payload = _sample_manifest()
        model = RecursiveChaosExperimentManifest.from_dict(payload)

        self.assertTrue(model.mesh_integration["seals_packets_before_learning"])
        validate_recursive_chaos_experiment_manifest(payload)

        mutated = copy.deepcopy(payload)
        mutated["mesh_integration"]["seals_packets_before_learning"] = False
        with self.assertRaises(SchemaValidationError):
            validate_recursive_chaos_experiment_manifest(mutated)

    def test_cycle_packet_binds_run_decision_recovery_and_safety(self) -> None:
        payload = _sample_cycle_packet()
        model = RecursiveChaosCyclePacket.from_dict(payload)

        self.assertEqual(model.run_id, "run_recursive_chaos_001")
        self.assertEqual(model.decision_id, "dec_recursive_chaos_001")
        self.assertFalse(model.safety_verdict["mutation_allowed"])
        validate_recursive_chaos_cycle_packet(payload)

    def test_ghost_recovery_packet_requires_complete_state_chain(self) -> None:
        payload = _sample_recovery_packet()
        model = RecursiveChaosGhostRecoveryPacket.from_dict(payload)

        self.assertTrue(model.recovered)
        self.assertEqual(model.residual_drift["status"], "none")
        validate_ghost_state_recovery_packet(payload)

        mutated = copy.deepcopy(payload)
        del mutated["post_state"]
        with self.assertRaises(SchemaValidationError):
            validate_ghost_state_recovery_packet(mutated)

    def test_learning_packet_is_advisory_and_source_sealed(self) -> None:
        payload = _sample_learning_packet()
        model = RecursiveChaosLearningPacket.from_dict(payload)

        self.assertTrue(model.sealed_source_required)
        self.assertTrue(model.advisory_only)
        self.assertFalse(model.training_allowed)
        self.assertEqual(model.mesh_model_mode, "recommend_only")
        self.assertFalse(model.mesh_model_training_allowed)
        validate_chaos_learning_packet(payload)

    def test_evidence_bundle_blocks_production_readiness_claim_by_default(self) -> None:
        payload = _sample_evidence_bundle()
        model = RecursiveChaosEvidenceBundle.from_dict(payload)

        self.assertFalse(model.production_readiness_claim)
        self.assertTrue(model.sealed)
        validate_arena_evidence_bundle(payload)

    def test_verify_cli_exposes_registry_pass_status(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/verify_recursive_chaos_arena_profiles.py", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('"status": "pass"', completed.stdout)
        self.assertIn('"profile_count": 16', completed.stdout)


def _arena_profile() -> dict[str, object]:
    return {
        "schema_version": "mesh.recursive_chaos.arena_profile.v1",
        "profile_id": "hetzner-k8s-probe",
        "display_name": "Hetzner Kubernetes probe-only arena",
        "arena_domain": "kubernetes_service_platform",
        "safety_class": "production_probe_only",
        "environment": "hetzner",
        "target_refs": ["k8s://mesh-prod/search-api"],
        "allowed_faults": ["pod_kill_one"],
        "blocked_faults": ["crash_loop", "bad_image", "scale_to_zero"],
        "max_recursion_depth": 2,
        "cycle_budget": {
            "max_cycles": 3,
            "max_duration_seconds": 900,
            "max_parallel_faults": 1,
        },
        "recovery_objectives": {
            "max_recovery_seconds": 180,
            "max_residual_drift": 0.0,
            "requires_post_state_probe": True,
        },
        "evidence_requirements": {
            "bind_run_id": True,
            "bind_decision_id": True,
            "bind_environment": True,
            "bind_image_digest": True,
            "require_recovery_packet": True,
        },
    }


def _sample_manifest() -> dict[str, object]:
    return {
        "schema_version": "mesh.recursive_chaos.experiment_manifest.v1",
        "manifest_id": "manifest_recursive_chaos_001",
        "profile_id": "hetzner-k8s-probe",
        "created_at": "2026-05-31T12:00:00Z",
        "runner": "compose_k8s_catalog_runner",
        "safety_class": "production_probe_only",
        "target_refs": ["k8s://mesh-prod/search-api"],
        "experiments": [
            {
                "experiment_id": "k8s_pod_churn_probe",
                "fault_family": "pod_churn",
                "target_ref": "k8s://mesh-prod/search-api",
                "mutates_target": False,
                "expected_mesh_decision": "no_action",
            }
        ],
        "safety_gates": {
            "allow_mutation": False,
            "requires_probe_only": True,
            "forbidden_actions": ["production_mutation", "raw_secret_capture"],
        },
        "mesh_integration": {
            "creates_run": True,
            "records_decision": True,
            "operator_approval_respected": True,
            "seals_packets_before_learning": True,
        },
        "environment": "hetzner",
    }


def _sample_cycle_packet() -> dict[str, object]:
    return {
        "schema_version": "mesh.recursive_chaos.cycle_packet.v1",
        "cycle_id": "cycle_recursive_chaos_001",
        "manifest_id": "manifest_recursive_chaos_001",
        "profile_id": "hetzner-k8s-probe",
        "run_id": "run_recursive_chaos_001",
        "decision_id": "dec_recursive_chaos_001",
        "started_at": "2026-05-31T12:00:01Z",
        "completed_at": "2026-05-31T12:02:00Z",
        "recursion_depth": 1,
        "selected_experiment": {
            "experiment_id": "k8s_pod_churn_probe",
            "fault": "pod_kill_one",
            "severity": "low",
            "capability_axes": ["suppress_transient_pod_churn"],
        },
        "target": {
            "substrate": "kubernetes",
            "environment": "hetzner",
            "namespace": "mesh-prod",
            "resource_ref": "deployment/search-api",
        },
        "pre_state_ref": "artifact://recursive-chaos/pre-state.json",
        "fault_state_ref": "artifact://recursive-chaos/fault-state.json",
        "mesh_observation": {"stage": "decision_ready", "decision_type": "no_action"},
        "safety_verdict": {
            "safety_class": "production_probe_only",
            "mutation_allowed": False,
            "forbidden_actions_enforced": True,
        },
        "recovery_packet_id": "recovery_recursive_chaos_001",
        "learning_packet_id": "learn_recursive_chaos_001",
        "evidence_refs": ["artifact://recursive-chaos/cycle.json"],
        "sealed": True,
    }


def _sample_recovery_packet() -> dict[str, object]:
    return {
        "schema_version": "mesh.recursive_chaos.ghost_recovery_packet.v1",
        "recovery_packet_id": "recovery_recursive_chaos_001",
        "cycle_id": "cycle_recursive_chaos_001",
        "run_id": "run_recursive_chaos_001",
        "decision_id": "dec_recursive_chaos_001",
        "pre_state": {"ready_replicas": 2, "image_digest": "sha256:test"},
        "fault_state": {"ready_replicas": 1, "fault": "pod_kill_one"},
        "recovery_action": {
            "action_type": "observe_reconcile",
            "actor": "mesh",
            "started_at": "2026-05-31T12:00:30Z",
            "completed_at": "2026-05-31T12:01:30Z",
            "result": "post_state_restored",
        },
        "post_state": {"ready_replicas": 2, "image_digest": "sha256:test"},
        "residual_drift": {"status": "none", "changed_paths": [], "drift_score": 0.0},
        "recovered": True,
        "evidence_refs": ["artifact://recursive-chaos/recovery.json"],
        "sealed_at": "2026-05-31T12:02:00Z",
    }


def _sample_learning_packet() -> dict[str, object]:
    return {
        "schema_version": "mesh.recursive_chaos.learning_packet.v1",
        "learning_packet_id": "learn_recursive_chaos_001",
        "cycle_id": "cycle_recursive_chaos_001",
        "run_id": "run_recursive_chaos_001",
        "source_packet_refs": ["cycle_recursive_chaos_001", "recovery_recursive_chaos_001"],
        "sealed_source_required": True,
        "mesh_brain_mode": "recommend_only",
        "mesh_model_mode": "recommend_only",
        "recommendations": [
            {
                "recommendation_type": "scheduler_weight",
                "summary": "Keep pod churn as false-positive probe for this profile.",
                "confidence": 0.8,
                "evidence_refs": ["artifact://recursive-chaos/cycle.json"],
            }
        ],
        "training_allowed": False,
        "mesh_model_training_allowed": False,
        "advisory_only": True,
        "sealed_at": "2026-05-31T12:02:10Z",
    }


def _sample_evidence_bundle() -> dict[str, object]:
    return {
        "schema_version": "mesh.recursive_chaos.evidence_bundle.v1",
        "bundle_id": "bundle_recursive_chaos_001",
        "generated_at": "2026-05-31T12:03:00Z",
        "profile_id": "hetzner-k8s-probe",
        "manifest_id": "manifest_recursive_chaos_001",
        "environment": "hetzner",
        "safety_class": "production_probe_only",
        "cycle_packet_refs": ["cycle_recursive_chaos_001"],
        "ghost_recovery_packet_refs": ["recovery_recursive_chaos_001"],
        "learning_packet_refs": ["learn_recursive_chaos_001"],
        "run_refs": ["run_recursive_chaos_001"],
        "decision_refs": ["dec_recursive_chaos_001"],
        "artifact_refs": ["artifact://recursive-chaos/events.jsonl"],
        "gate_results": [
            {
                "gate": "contract_validation",
                "status": "pass",
                "evidence_ref": "artifact://recursive-chaos/contracts.json",
            }
        ],
        "production_readiness_claim": False,
        "sealed": True,
    }


def _experiment_manifest() -> dict[str, object]:
    return _sample_manifest()


def _cycle_packet() -> dict[str, object]:
    return _sample_cycle_packet()


def _ghost_recovery_packet() -> dict[str, object]:
    return _sample_recovery_packet()


def _learning_packet() -> dict[str, object]:
    return _sample_learning_packet()


def _evidence_bundle() -> dict[str, object]:
    return _sample_evidence_bundle()


if __name__ == "__main__":
    unittest.main()
