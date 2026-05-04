from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    DatasetBundle,
    DatasetRow,
    SharedAdapterApproval,
    TrainingJobSpec,
    build_data_plane_e2e,
    build_posttraining_e2e,
    plan_posttraining_run,
)


class MeshBrainPosttrainingTests(unittest.TestCase):
    def test_posttraining_e2e_produces_signed_artifact_lineage_and_rollback_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            run = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            output_dir = Path(temp_dir) / "posttraining"

            self.assertTrue((output_dir / "training_manifest.json").exists())
            self.assertTrue((output_dir / "artifact_manifest.json").exists())
            self.assertTrue((output_dir / "lineage_graph.json").exists())
            self.assertTrue((output_dir / "rollback_manifest.json").exists())
            self.assertTrue((output_dir / "model_card.json").exists())

            model_card = json.loads((output_dir / "model_card.json").read_text(encoding="utf-8"))

        self.assertEqual(run.training_manifest.method, "lora")
        self.assertTrue(run.training_manifest.signed_manifest_ref.startswith("sha256:"))
        self.assertEqual(run.artifact.artifact_type, "tenant_adapter")
        self.assertEqual(run.artifact.tenant_id, "tenant_a")
        self.assertEqual(run.artifact.dataset_manifest_ids, [data_result.bundle.dataset_version])
        self.assertEqual(run.rollback_manifest.previous_artifact_id, "adapter_previous")
        self.assertEqual([node.node_type for node in run.lineage_graph], ["dataset", "training_code", "training_run", "model_artifact"])
        self.assertTrue(model_card["eval_required_before_deployment"])

    def test_training_rejects_cross_tenant_trainable_rows(self) -> None:
        bundle = DatasetBundle(
            dataset_version="dataset_bad",
            source_manifest_id="manifest_bad",
            created_at="2026-04-30T00:00:00+00:00",
            rows=[
                _row("tenant_a", "row_a"),
                _row("tenant_b", "row_b"),
            ],
        )
        spec = TrainingJobSpec(
            method="lora",
            tenant_id="tenant_a",
            task_type="crops",
            dataset_bundle=bundle,
            code_version="code",
        )

        with self.assertRaisesRegex(ValueError, "another tenant"):
            plan_posttraining_run(spec=spec)

    def test_shared_adapter_requires_customer_and_legal_approval(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=temp_dir)

        missing_approval = TrainingJobSpec(
            method="lora",
            tenant_id="tenant_a",
            task_type="crops",
            dataset_bundle=data_result.bundle,
            code_version="code",
            shared_adapter=True,
        )
        with self.assertRaisesRegex(ValueError, "shared adapters require"):
            plan_posttraining_run(spec=missing_approval)

        approved = TrainingJobSpec(
            method="lora",
            tenant_id="tenant_a",
            task_type="crops",
            dataset_bundle=data_result.bundle,
            code_version="code",
            shared_adapter=True,
            shared_adapter_approval=SharedAdapterApproval(
                approval_id="approval_1",
                customer_approved=True,
                legal_approved=True,
                approved_at="2026-04-30T00:00:00+00:00",
                evidence_refs=["legal://approval"],
            ),
        )
        run = plan_posttraining_run(spec=approved)

        self.assertIsNone(run.artifact.tenant_id)
        self.assertTrue(run.model_card["shared_adapter"])

    def test_audit_only_rows_are_excluded_from_training_lineage(self) -> None:
        bundle = DatasetBundle(
            dataset_version="dataset_audit",
            source_manifest_id="manifest_audit",
            created_at="2026-04-30T00:00:00+00:00",
            rows=[
                _row("tenant_a", "trainable"),
                _row("tenant_a", "audit", excluded=True),
            ],
        )
        spec = TrainingJobSpec(
            method="sft",
            tenant_id="tenant_a",
            task_type="support",
            dataset_bundle=bundle,
            code_version="code",
        )
        run = plan_posttraining_run(spec=spec)

        self.assertEqual(run.training_manifest.lineage["row_ids"], ["trainable"])


def _row(tenant_id: str, row_id: str, *, excluded: bool = False) -> DatasetRow:
    return DatasetRow(
        row_id=row_id,
        tenant_id=tenant_id,
        source="test",
        timestamp="2026-04-30T00:00:00+00:00",
        redaction_status="clean",
        license_usage_class="internal_enterprise",
        provenance_pointer=f"test://{row_id}",
        row_type="sft",
        payload={"instruction": "do work", "context": "ctx", "expected_response": "ok"},
        excluded_from_training=excluded,
    )


if __name__ == "__main__":
    unittest.main()
