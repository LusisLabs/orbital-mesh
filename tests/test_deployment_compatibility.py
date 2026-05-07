from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.deployment_compatibility import (
    build_deployment_compatibility_matrix,
    verify_deployment_compatibility_registry,
)
from shared.mesh_runtime.schema_validation import validate_payload


class DeploymentCompatibilityTests(unittest.TestCase):
    def test_default_registry_passes_and_marks_ecs_as_next_target(self) -> None:
        verification = verify_deployment_compatibility_registry("config/deployment-compatibility.registry.json")
        matrix = build_deployment_compatibility_matrix("config/deployment-compatibility.registry.json")

        self.assertEqual(verification["status"], "pass")
        self.assertIn("docker_compose", verification["validated_targets"])
        self.assertIn("kubernetes", verification["validated_targets"])
        self.assertEqual(verification["next_validated_targets"], ["ecs_fargate"])
        self.assertEqual(matrix["targets"]["ecs_fargate"]["level"], "next_validated_target")
        self.assertIn("ecs_fargate_smoke_missing", matrix["targets"]["ecs_fargate"]["promotion_blockers"])
        validate_payload("deployment-compatibility-matrix.schema.json", matrix)

    def test_validated_target_without_release_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deployment-compatibility.registry.json"
            payload = _registry()
            payload["targets"][0]["release_packet_required"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_deployment_compatibility_registry(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("docker_compose:validated_release_packet_not_required", result["blockers"])

    def test_recipe_cannot_become_validated_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deployment-compatibility.registry.json"
            payload = _registry()
            payload["targets"][2]["level"] = "validated"
            payload["targets"][2]["validation_commands"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_deployment_compatibility_registry(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("ecs_fargate_not_single_next_validated_target", result["blockers"])
        self.assertIn("ecs_fargate:validated_commands_missing", result["blockers"])


def _registry() -> dict:
    return {
        "schema_version": "mesh.deployment_compatibility.registry.v1",
        "generated_from": ["docs/deployment-compatibility.md"],
        "targets": [
            _target("docker_compose", "validated", blockers=[]),
            _target("kubernetes", "validated", blockers=[]),
            _target("ecs_fargate", "next_validated_target", blockers=["ecs_fargate_smoke_missing"]),
        ],
    }


def _target(target_id: str, level: str, *, blockers: list[str]) -> dict:
    return {
        "target_id": target_id,
        "display_name": target_id,
        "category": "test",
        "level": level,
        "product_stance": "test stance",
        "authority_boundary": "test authority boundary",
        "validation_commands": ["test command"],
        "required_evidence": [
            "health",
            "readiness",
            "persistence",
            "feedback",
            "audit",
            "rollback",
            "release_packet",
        ],
        "evidence_refs": ["docs/deployment-compatibility.md"],
        "readiness_required": level in {"validated", "next_validated_target"},
        "release_packet_required": level in {"validated", "next_validated_target"},
        "promotion_blockers": blockers,
    }
