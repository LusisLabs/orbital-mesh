from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    MeshBrainServingFabric,
    ModelArtifact,
    OpenAIChatRequest,
    ServingPool,
    TenantQuota,
    build_data_plane_e2e,
    build_posttraining_e2e,
    build_serving_fabric_e2e,
    new_model_artifact,
    write_serving_plan,
)


class MeshBrainServingFabricTests(unittest.TestCase):
    def test_serving_fabric_e2e_plans_openai_compatible_high_risk_streaming_request(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            base = _artifact("base_model", "base", state="production")
            posttraining.artifact.state = "production"
            fabric, plan = build_serving_fabric_e2e(artifacts=[base, posttraining.artifact])
            written = write_serving_plan(plan=plan, output_directory=Path(temp_dir) / "serving")
            saved_plan = json.loads(Path(written["serving_plan.json"]).read_text(encoding="utf-8"))

        self.assertIsInstance(fabric, MeshBrainServingFabric)
        self.assertTrue(plan.openai_compatible)
        self.assertTrue(plan.streaming)
        self.assertTrue(plan.structured_output)
        self.assertEqual(plan.backend_name, "sgl-project/sglang")
        self.assertEqual(plan.route.route_mode, "verification")
        self.assertEqual(plan.model_artifact_id, base.artifact_id)
        self.assertEqual(plan.adapter_artifact_ids, [posttraining.artifact.artifact_id])
        self.assertEqual(saved_plan["trace"]["tenant_id"], "tenant_a")

    def test_serving_fabric_enforces_tenant_quota(self) -> None:
        fabric = MeshBrainServingFabric(
            pools=[ServingPool(pool_id="cpu", hardware_tier="cpu_edge", backend_name="ggml-org/llama.cpp")],
            artifacts=[],
            quotas={"tenant_a": TenantQuota(tenant_id="tenant_a", max_requests_per_minute=1, max_tokens_per_minute=10)},
        )
        request = OpenAIChatRequest(
            tenant_id="tenant_a",
            messages=[{"role": "user", "content": "one"}],
            task_type="support",
            hardware_tier="cpu_edge",
            risk_level="low",
        )

        fabric.plan_chat_completion(request)
        with self.assertRaisesRegex(ValueError, "quota exceeded"):
            fabric.plan_chat_completion(request)

    def test_canary_hot_swap_and_rollback_update_adapter_routing(self) -> None:
        base = _artifact("base_model", "base", state="production")
        production = _artifact("tenant_adapter", "adapter_prod", state="production", tenant_id="tenant_a", task_type="crops")
        canary = _artifact("tenant_adapter", "adapter_canary", state="canary", tenant_id="tenant_a", task_type="crops")
        fabric = MeshBrainServingFabric(
            pools=[ServingPool(pool_id="nvidia", hardware_tier="nvidia_datacenter", backend_name="sgl-project/sglang")],
            artifacts=[base, production],
            canary_weight=1.0,
        )
        fabric.hot_swap_adapter(canary)

        request = OpenAIChatRequest(
            tenant_id="tenant_a",
            messages=[{"role": "user", "content": "inspect search"}],
            task_type="crops",
            hardware_tier="nvidia_datacenter",
            risk_level="low",
        )
        canary_plan = fabric.plan_chat_completion(request)
        fabric.rollback_adapter(current_artifact_id=canary.artifact_id, rollback_artifact_id=production.artifact_id)
        production_plan = fabric.plan_chat_completion(request)

        self.assertEqual(canary_plan.adapter_artifact_ids, [canary.artifact_id])
        self.assertEqual(production_plan.adapter_artifact_ids, [production.artifact_id])
        self.assertEqual(canary.state, "retired")
        self.assertEqual(production.state, "production")

    def test_engine_metrics_include_pool_health_and_prefill_decode_split(self) -> None:
        fabric = MeshBrainServingFabric(
            pools=[
                ServingPool(
                    pool_id="cluster",
                    hardware_tier="nvidia_large_cluster",
                    backend_name="ai-dynamo/dynamo",
                    prefill_pool="prefill",
                    decode_pool="decode",
                    metrics={"cache_hit_rate": 0.8},
                )
            ],
            artifacts=[],
        )

        metrics = fabric.engine_metrics()

        self.assertEqual(metrics["nvidia_large_cluster"]["backend_name"], "ai-dynamo/dynamo")
        self.assertEqual(metrics["nvidia_large_cluster"]["prefill_pool"], "prefill")
        self.assertEqual(metrics["nvidia_large_cluster"]["decode_pool"], "decode")


def _artifact(
    artifact_type: str,
    artifact_id: str,
    *,
    state: str,
    tenant_id: str | None = None,
    task_type: str | None = None,
) -> ModelArtifact:
    artifact = new_model_artifact(
        artifact_type=artifact_type,
        version="2026.04.30",
        signed_manifest_ref=f"sha256:{artifact_id}",
        tenant_id=tenant_id,
        task_type=task_type,
    )
    artifact.artifact_id = artifact_id
    artifact.state = state
    return artifact


if __name__ == "__main__":
    unittest.main()
