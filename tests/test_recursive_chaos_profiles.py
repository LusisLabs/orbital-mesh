from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.recursive_chaos import (
    P0_ARENA_PROFILE_IDS,
    REQUIRED_ARENA_PROFILE_IDS,
    get_recursive_chaos_arena_profile,
    load_recursive_chaos_arena_profiles,
    recursive_chaos_arena_profiles_ready,
    resolve_recursive_chaos_safety_class,
    safety_class_allows_mutation,
    validate_arena_evidence_bundle,
    validate_chaos_learning_packet,
    validate_ghost_state_recovery_packet,
    validate_recursive_chaos_cycle_packet,
    validate_recursive_chaos_experiment_manifest,
    verify_recursive_chaos_arena_profiles,
)
from shared.mesh_runtime.schema_validation import SchemaValidationError, validate_payload
from tests.test_recursive_chaos_contracts import (
    _sample_cycle_packet,
    _sample_evidence_bundle,
    _sample_learning_packet,
    _sample_manifest,
    _sample_recovery_packet,
)


class RecursiveChaosProfileTests(unittest.TestCase):
    def test_default_registry_passes_for_priority_arenas(self) -> None:
        verification = verify_recursive_chaos_arena_profiles("config/recursive-chaos.arena-profiles.json")
        registry = load_recursive_chaos_arena_profiles("config/recursive-chaos.arena-profiles.json")

        self.assertEqual(verification["status"], "pass")
        self.assertEqual(set(verification["profile_ids"]), REQUIRED_ARENA_PROFILE_IDS)
        self.assertEqual(set(verification["p0_profile_ids"]), P0_ARENA_PROFILE_IDS)
        self.assertTrue(recursive_chaos_arena_profiles_ready("config/recursive-chaos.arena-profiles.json"))
        validate_payload("recursive-chaos-arena-profiles.schema.json", registry)

    def test_get_profile_and_hetzner_safety_resolution(self) -> None:
        profile = get_recursive_chaos_arena_profile(
            "kubernetes_service_platform",
            "config/recursive-chaos.arena-profiles.json",
        )

        self.assertEqual(profile["arena_domain"], "kubernetes_service_platform")
        self.assertEqual(resolve_recursive_chaos_safety_class(profile, "local"), "staging_owned")
        self.assertEqual(resolve_recursive_chaos_safety_class(profile, "hetzner"), "production_probe_only")
        self.assertFalse(safety_class_allows_mutation("production_probe_only"))
        self.assertFalse(safety_class_allows_mutation("production_mutating_blocked"))
        self.assertTrue(safety_class_allows_mutation("local_disposable"))
        self.assertTrue(safety_class_allows_mutation("staging_owned"))

    def test_manifest_validator_blocks_mutating_faults_in_probe_only_class(self) -> None:
        payload = _sample_manifest()
        validate_recursive_chaos_experiment_manifest(payload)

        payload["experiments"][0]["mutates_target"] = True
        payload["safety_gates"]["allow_mutation"] = True
        with self.assertRaises(SchemaValidationError):
            validate_recursive_chaos_experiment_manifest(payload)

    def test_packet_validators_enforce_sealed_advisory_evidence(self) -> None:
        cycle = _sample_cycle_packet()
        recovery = _sample_recovery_packet()
        learning = _sample_learning_packet()
        bundle = _sample_evidence_bundle()

        validate_recursive_chaos_cycle_packet(cycle)
        validate_ghost_state_recovery_packet(recovery)
        validate_chaos_learning_packet(learning)
        validate_arena_evidence_bundle(bundle)

        unsealed_learning = copy.deepcopy(learning)
        unsealed_learning["sealed_source_required"] = False
        with self.assertRaises(SchemaValidationError):
            validate_chaos_learning_packet(unsealed_learning)

        overclaim_bundle = copy.deepcopy(bundle)
        overclaim_bundle["production_readiness_claim"] = True
        with self.assertRaises(SchemaValidationError):
            validate_arena_evidence_bundle(overclaim_bundle)

    def test_cli_exits_nonzero_for_invalid_registry(self) -> None:
        payload = _registry_copy()
        payload["profiles"][0]["production_mutation_allowed"] = True
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recursive-chaos.arena-profiles.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_recursive_chaos_arena_profiles.py",
                    "--profiles",
                    str(path),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("production_mutation_not_blocked", completed.stdout)


def _registry_copy() -> dict[str, object]:
    return copy.deepcopy(load_recursive_chaos_arena_profiles("config/recursive-chaos.arena-profiles.json"))


if __name__ == "__main__":
    unittest.main()
