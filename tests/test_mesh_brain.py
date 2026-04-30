from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from shared.mesh_runtime.mesh_brain import (
    InferenceRequestContext,
    MeshBrainRegistry,
    ModelArtifact,
    ReleaseGatePolicy,
    evaluate_release_gate,
    new_model_artifact,
    select_serving_route,
)


class MeshBrainReleaseGateTests(unittest.TestCase):
    def test_release_gate_blocks_policy_regression(self) -> None:
        result = evaluate_release_gate(
            candidate_artifact_id="adapter_candidate",
            metrics={
                "critical_policy_regressions": 1,
                "task_success_rate": 0.95,
                "unsafe_autonomous_action_rate_delta": 0,
                "schema_validity_delta": 0,
            },
            policy=ReleaseGatePolicy(task_success_threshold=0.8),
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.release_decision, "block")
        self.assertEqual(result.reasons, ["critical_policy_regression"])

    def test_release_gate_canaries_before_full_promotion(self) -> None:
        result = evaluate_release_gate(
            candidate_artifact_id="adapter_candidate",
            metrics={
                "critical_policy_regressions": 0,
                "task_success_rate": 0.92,
                "unsafe_autonomous_action_rate_delta": 0,
                "schema_validity_delta": 0,
                "latency_p95_ms": 700,
                "cost_per_completed_task": 0.08,
            },
            policy=ReleaseGatePolicy(
                task_success_threshold=0.8,
                latency_p95_budget_ms=1000,
                cost_per_completed_task_budget=0.1,
            ),
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.release_decision, "canary")

    def test_release_gate_promotes_after_canary_pass(self) -> None:
        result = evaluate_release_gate(
            candidate_artifact_id="adapter_candidate",
            metrics={
                "critical_policy_regressions": 0,
                "task_success_rate": 0.92,
                "unsafe_autonomous_action_rate_delta": 0,
                "schema_validity_delta": 0,
                "canary_passed": True,
            },
            policy=ReleaseGatePolicy(task_success_threshold=0.8),
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.release_decision, "promote")


class MeshBrainRegistryTests(unittest.TestCase):
    def test_promotion_records_rollback_target_and_rollback_restores_previous(self) -> None:
        with TemporaryDirectory() as temp_dir:
            registry = MeshBrainRegistry(temp_dir)
            current = registry.register_artifact(_artifact("base_v1", state="registered"))
            gate = evaluate_release_gate(
                candidate_artifact_id=current.artifact_id,
                metrics={
                    "critical_policy_regressions": 0,
                    "task_success_rate": 0.9,
                    "unsafe_autonomous_action_rate_delta": 0,
                    "schema_validity_delta": 0,
                    "canary_passed": True,
                },
                policy=ReleaseGatePolicy(task_success_threshold=0.8),
            )
            promoted_current = registry.promote_artifact(current.artifact_id, gate, alias="tenant_a/crops")

            candidate = registry.register_artifact(_artifact("base_v2", state="registered"))
            candidate_gate = evaluate_release_gate(
                candidate_artifact_id=candidate.artifact_id,
                metrics={
                    "critical_policy_regressions": 0,
                    "task_success_rate": 0.93,
                    "unsafe_autonomous_action_rate_delta": 0,
                    "schema_validity_delta": 0,
                    "canary_passed": True,
                },
                policy=ReleaseGatePolicy(task_success_threshold=0.8),
            )

            promoted_candidate = registry.promote_artifact(candidate.artifact_id, candidate_gate, alias="tenant_a/crops")
            restored = registry.rollback("tenant_a/crops")

        self.assertEqual(promoted_current.state, "production")
        self.assertEqual(promoted_candidate.rollback_artifact_id, promoted_current.artifact_id)
        self.assertEqual(restored.artifact_id, promoted_current.artifact_id)
        self.assertEqual(restored.state, "production")

    def test_register_artifact_requires_signed_manifest_for_deployable_artifacts(self) -> None:
        with self.assertRaises(ValueError):
            ModelArtifact(
                artifact_id="bad",
                artifact_type="tenant_adapter",
                version="v1",
                created_at="2026-01-01T00:00:00+00:00",
            )


class MeshBrainRoutingTests(unittest.TestCase):
    def test_high_risk_datacenter_route_uses_verification_and_constrained_decoding(self) -> None:
        route = select_serving_route(
            context=InferenceRequestContext(
                tenant_id="tenant_a",
                task_type="crops",
                hardware_tier="nvidia_datacenter",
                risk_level="high",
                context_tokens=32000,
                structured_output=True,
            ),
            artifacts=[
                _artifact("base", state="production"),
                _artifact("tenant_adapter", artifact_type="tenant_adapter", state="production", tenant_id="tenant_a", task_type="crops"),
                _artifact("other_adapter", artifact_type="tenant_adapter", state="production", tenant_id="tenant_b", task_type="crops"),
            ],
        )

        self.assertEqual(route.engine, "sglang")
        self.assertEqual(route.secondary_engine, "vllm")
        self.assertTrue(route.verification_required)
        self.assertTrue(route.constrained_decoding)
        self.assertTrue(route.chunked_prefill)
        self.assertTrue(route.kv_aware_routing)
        self.assertEqual(route.adapter_artifact_ids, ["tenant_adapter"])

    def test_cpu_edge_route_uses_llama_cpp_without_batching(self) -> None:
        route = select_serving_route(
            context=InferenceRequestContext(
                tenant_id="tenant_a",
                task_type="support",
                hardware_tier="cpu_edge",
                risk_level="low",
                sla="batch",
            ),
            artifacts=[],
        )

        self.assertEqual(route.engine, "llama.cpp")
        self.assertIsNone(route.secondary_engine)
        self.assertFalse(route.continuous_batching)
        self.assertFalse(route.speculative_decoding)


def _artifact(
    artifact_id: str,
    *,
    artifact_type: str = "base_model",
    state: str = "production",
    tenant_id: str | None = None,
    task_type: str | None = None,
) -> ModelArtifact:
    artifact = new_model_artifact(
        artifact_type=artifact_type,
        version="2026.04.30",
        signed_manifest_ref=f"sigstore://{artifact_id}",
        tenant_id=tenant_id,
        task_type=task_type,
    )
    artifact.artifact_id = artifact_id
    artifact.state = state
    return artifact


if __name__ == "__main__":
    unittest.main()
