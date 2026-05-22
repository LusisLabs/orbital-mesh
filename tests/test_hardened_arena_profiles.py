from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.hardened_arena import (
    REQUIRED_PROFILE_IDS,
    REQUIRED_PROOF_GATES,
    get_hardened_arena_profile,
    load_hardened_arena_profiles,
    verify_hardened_arena_profiles,
)
from shared.mesh_runtime.schema_validation import validate_payload


class HardenedArenaProfileTests(unittest.TestCase):
    def test_default_registry_passes_with_exact_recipe_profiles(self) -> None:
        verification = verify_hardened_arena_profiles("config/hardened-arena.profiles.json")
        registry = load_hardened_arena_profiles("config/hardened-arena.profiles.json")

        self.assertEqual(verification["status"], "pass")
        self.assertEqual(set(verification["profile_ids"]), REQUIRED_PROFILE_IDS)
        self.assertEqual(verification["profile_count"], 3)
        for profile in registry["profiles"]:
            self.assertEqual(profile["lifecycle_state"], "recipe")
            self.assertFalse(profile["production_readiness_claim"])
            self.assertIn(profile["ai_lane"], {"proposal_only", "none"})
            self.assertTrue(REQUIRED_PROOF_GATES.issubset(set(profile["proof_gates"]["required"])))
            self.assertTrue(profile["cleanup"]["required"])
            self.assertTrue(profile["probe_plan"]["required"])
            self.assertTrue(profile["data_boundary"]["raw_secret_policy"])
        validate_payload("hardened-arena-profiles.schema.json", registry)

    def test_get_profile_returns_named_profile(self) -> None:
        profile = get_hardened_arena_profile("solo_project_default", "config/hardened-arena.profiles.json")

        self.assertEqual(profile["profile_id"], "solo_project_default")
        self.assertEqual(profile["readiness_posture"], "recipe_only")

    def test_missing_registry_fails_closed(self) -> None:
        result = verify_hardened_arena_profiles("/tmp/orbital-mesh-missing-hardened-arena-profiles.json")

        self.assertEqual(result["status"], "fail")
        self.assertIn("hardened_arena_profile_registry_missing", result["blockers"])

    def test_dhi_source_without_slug_fails(self) -> None:
        payload = _registry_copy()
        payload["profiles"][0]["components"][0]["source"]["dhi_slug"] = ""

        result = _verify_payload(payload)

        self.assertEqual(result["status"], "fail")
        self.assertIn("solo_project_default:solo_ingress_gateway:dhi_slug_missing", result["blockers"])

    def test_dhi_source_without_refs_or_blockers_fails(self) -> None:
        payload = _registry_copy()
        source = payload["profiles"][0]["components"][0]["source"]
        source["digest_ref"] = None
        source["sbom_ref"] = None
        source["provenance_ref"] = None
        source["blockers"] = []

        result = _verify_payload(payload)

        self.assertEqual(result["status"], "fail")
        self.assertIn("solo_project_default:solo_ingress_gateway:dhi_proof_refs_or_blockers_missing", result["blockers"])

    def test_mutating_component_without_rollback_proof_fails(self) -> None:
        payload = _registry_copy()
        payload["profiles"][0]["components"][1]["rollback_proof_requirements"] = []

        result = _verify_payload(payload)

        self.assertEqual(result["status"], "fail")
        self.assertIn("solo_project_default:solo_postgres:mutating_component_rollback_proof_missing", result["blockers"])

    def test_cli_exits_nonzero_for_invalid_registry(self) -> None:
        payload = _registry_copy()
        payload["profiles"][0]["ai_lane"] = "autonomous"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_hardened_arena_profiles.py",
                    "--profiles",
                    str(path),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("hardened_arena_profile_registry_invalid", completed.stdout)


def _registry_copy() -> dict:
    return copy.deepcopy(load_hardened_arena_profiles("config/hardened-arena.profiles.json"))


def _verify_payload(payload: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hardened-arena.profiles.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return verify_hardened_arena_profiles(path)


if __name__ == "__main__":
    unittest.main()
