from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    MeshBrainModelCatalog,
    ModelRouteRequest,
    PromotionApproval,
    ReleaseGatePolicy,
    ReleaseGateResult,
    artifact_fingerprint,
    build_model_management_e2e,
    curated_quality_source_coverage_pass,
    deterministic_alias,
    evaluate_release_gate,
)


class MeshBrainModelManagementTests(unittest.TestCase):
    def test_model_management_e2e_registers_routes_and_writes_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            catalog, route = build_model_management_e2e(output_directory=temp_dir)
            snapshot = json.loads((Path(temp_dir) / "model_catalog_snapshot.json").read_text(encoding="utf-8"))

        self.assertEqual(route.alias, "tenant_a/crops")
        self.assertIsNotNone(route.artifact_id)
        self.assertEqual(route.route.engine, "sglang")
        self.assertTrue(route.route.verification_required)
        self.assertIsNotNone(route.lineage)
        self.assertEqual(route.lineage.dataset_manifest_ids, ["dataset_v1"])
        self.assertIn("aliases", snapshot)
        self.assertEqual(len(catalog.list_artifacts(state="production")), 3)

    def test_catalog_supports_canary_promote_rollback_and_retire(self) -> None:
        catalog = MeshBrainModelCatalog()
        base = catalog.register_base_model(version="base", signed_manifest_ref="sha256:base")
        base.state = "production"
        current = catalog.register_tenant_adapter(
            tenant_id="tenant_a",
            task_type="crops",
            version="v1",
            signed_manifest_ref="sha256:v1",
            base_artifact_id=base.artifact_id,
            dataset_manifest_ids=["dataset_v1"],
            training_run_id="train_v1",
        )
        current_gate = _gate(current.artifact_id, "promote")
        catalog.promote(
            artifact_id=current.artifact_id,
            gate_result=current_gate,
            alias="tenant_a/crops",
            approval=_approval("approval_current"),
            rollback_manifest_ref="rollback://tenant_a/crops/current",
        )
        candidate = catalog.register_tenant_adapter(
            tenant_id="tenant_a",
            task_type="crops",
            version="v2",
            signed_manifest_ref="sha256:v2",
            base_artifact_id=base.artifact_id,
            dataset_manifest_ids=["dataset_v2"],
            training_run_id="train_v2",
        )
        canary_alias = catalog.promote(
            artifact_id=candidate.artifact_id,
            gate_result=_gate(candidate.artifact_id, "canary"),
            alias="tenant_a/crops",
            approval=_approval("approval_canary"),
            rollback_manifest_ref="rollback://tenant_a/crops/candidate",
        )
        promoted_alias = catalog.promote(
            artifact_id=candidate.artifact_id,
            gate_result=_gate(candidate.artifact_id, "promote"),
            alias="tenant_a/crops",
            approval=_approval("approval_promote"),
            rollback_manifest_ref="rollback://tenant_a/crops/candidate",
        )
        rollback_alias = catalog.rollback(alias="tenant_a/crops")
        retired = catalog.retire(candidate.artifact_id)

        self.assertEqual(canary_alias.state, "canary")
        self.assertEqual(promoted_alias.previous_artifact_id, current.artifact_id)
        self.assertEqual(rollback_alias.artifact_id, current.artifact_id)
        self.assertEqual(retired.state, "retired")
        self.assertEqual(candidate.metadata["promotion_approval"]["approval_id"], "approval_promote")
        self.assertEqual(candidate.metadata["rollback_manifest_ref"], "rollback://tenant_a/crops/candidate")

    def test_catalog_rejects_blocked_gate_promotion(self) -> None:
        catalog = MeshBrainModelCatalog()
        artifact = catalog.register_tenant_adapter(
            tenant_id="tenant_a",
            task_type="crops",
            version="v1",
            signed_manifest_ref="sha256:v1",
        )
        gate = evaluate_release_gate(
            candidate_artifact_id=artifact.artifact_id,
            metrics={
                "critical_policy_regressions": 1,
                "unsafe_autonomous_action_rate_delta": 0,
                "schema_validity_delta": 0,
                "task_success_rate": 1.0,
            },
            policy=ReleaseGatePolicy(task_success_threshold=0.8),
        )

        with self.assertRaisesRegex(ValueError, "blocks promotion"):
            catalog.promote(artifact_id=artifact.artifact_id, gate_result=gate, alias="tenant_a/crops")

    def test_catalog_rejects_canary_without_required_approval_and_rollback_controls(self) -> None:
        catalog = MeshBrainModelCatalog()
        artifact = catalog.register_tenant_adapter(
            tenant_id="tenant_a",
            task_type="crops",
            version="v1",
            signed_manifest_ref="sha256:v1",
        )

        with self.assertRaisesRegex(ValueError, "operator approval"):
            catalog.promote(artifact_id=artifact.artifact_id, gate_result=_gate(artifact.artifact_id, "canary"), alias="tenant_a/crops")
        with self.assertRaisesRegex(ValueError, "rollback metadata"):
            catalog.promote(
                artifact_id=artifact.artifact_id,
                gate_result=_gate(artifact.artifact_id, "canary"),
                alias="tenant_a/crops",
                approval=_approval("approval_missing_rollback"),
            )

    def test_catalog_rejects_promotion_without_curated_quality_training_gate(self) -> None:
        catalog = MeshBrainModelCatalog()
        artifact = catalog.register_tenant_adapter(
            tenant_id="tenant_a",
            task_type="crops",
            version="v1",
            signed_manifest_ref="sha256:v1",
        )
        gate = _gate(artifact.artifact_id, "canary")
        gate.metrics.pop("curated_quality_training_passed")

        with self.assertRaisesRegex(ValueError, "curated_quality_training_passed"):
            catalog.promote(
                artifact_id=artifact.artifact_id,
                gate_result=gate,
                alias="tenant_a/crops",
                approval=_approval("approval_missing_quality"),
                rollback_manifest_ref="rollback://tenant_a/crops",
            )

    def test_catalog_rejects_promotion_without_curated_quality_source_coverage(self) -> None:
        catalog = MeshBrainModelCatalog()
        artifact = catalog.register_tenant_adapter(
            tenant_id="tenant_a",
            task_type="crops",
            version="v1",
            signed_manifest_ref="sha256:v1",
        )
        gate = _gate(artifact.artifact_id, "canary")
        gate.metrics.pop("quality_source_coverage")

        with self.assertRaisesRegex(ValueError, "curated quality coverage"):
            catalog.promote(
                artifact_id=artifact.artifact_id,
                gate_result=gate,
                alias="tenant_a/crops",
                approval=_approval("approval_missing_quality_coverage"),
                rollback_manifest_ref="rollback://tenant_a/crops",
            )

    def test_route_resolution_filters_by_tenant_and_task(self) -> None:
        catalog = MeshBrainModelCatalog()
        base = catalog.register_base_model(version="base", signed_manifest_ref="sha256:base")
        base.state = "production"
        tenant_a = catalog.register_tenant_adapter(
            tenant_id="tenant_a",
            task_type="crops",
            version="a",
            signed_manifest_ref="sha256:a",
        )
        tenant_b = catalog.register_tenant_adapter(
            tenant_id="tenant_b",
            task_type="crops",
            version="b",
            signed_manifest_ref="sha256:b",
        )
        catalog.promote(
            artifact_id=tenant_a.artifact_id,
            gate_result=_gate(tenant_a.artifact_id, "promote"),
            alias="tenant_a/crops",
            approval=_approval("approval_tenant_a"),
            rollback_manifest_ref="rollback://tenant_a/crops",
        )
        catalog.promote(
            artifact_id=tenant_b.artifact_id,
            gate_result=_gate(tenant_b.artifact_id, "promote"),
            alias="tenant_b/crops",
            approval=_approval("approval_tenant_b"),
            rollback_manifest_ref="rollback://tenant_b/crops",
        )

        route = catalog.resolve_route(
            ModelRouteRequest(
                tenant_id="tenant_a",
                task_type="crops",
                hardware_tier="nvidia_datacenter",
                risk_level="low",
            )
        )

        self.assertEqual(route.artifact_id, tenant_a.artifact_id)
        self.assertEqual(route.route.adapter_artifact_ids, [tenant_a.artifact_id])
        self.assertEqual(deterministic_alias("tenant_a", "crops"), "tenant_a/crops")
        self.assertEqual(artifact_fingerprint(tenant_a), artifact_fingerprint(tenant_a))


def _gate(artifact_id: str, decision: str) -> ReleaseGateResult:
    gate = evaluate_release_gate(
        candidate_artifact_id=artifact_id,
        metrics={
            "critical_policy_regressions": 0,
            "unsafe_autonomous_action_rate_delta": 0,
            "schema_validity_delta": 0,
            "task_success_rate": 1.0,
            "canary_passed": decision == "promote",
            "model_kernel_passed": True,
            "live_serving_smoke_passed": True,
            "response_eval_passed": True,
            "judge_rubric_passed": True,
            "red_team_regression_passed": True,
            "curated_quality_training_passed": True,
            "quality_source_coverage": curated_quality_source_coverage_pass(),
        },
        policy=ReleaseGatePolicy(task_success_threshold=0.8),
    )
    if decision == "canary":
        self_decision = gate.release_decision
        assert self_decision == "canary"
    return gate


def _approval(approval_id: str) -> PromotionApproval:
    return PromotionApproval(
        approval_id=approval_id,
        operator_id="operator_1",
        roles=["approver"],
        approved_at="2026-05-04T00:00:00+00:00",
        evidence_refs=["mesh://approval/test"],
    )


if __name__ == "__main__":
    unittest.main()
