from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    MeshBrainDataRefinery,
    SourceRecord,
    build_data_plane_e2e,
    extract_tool_schema,
    label_outcome,
)


class MeshBrainDataRefineryTests(unittest.TestCase):
    def test_refinery_isolates_tenant_deduplicates_redacts_and_writes_outputs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=temp_dir)
            output_dir = Path(temp_dir)

            self.assertEqual(result.report.accepted_records, 1)
            self.assertEqual(result.report.duplicate_records, 1)
            self.assertEqual(result.report.rejected_records, 1)
            self.assertEqual(result.report.chunks, 1)
            self.assertEqual(result.report.row_count, 5)
            self.assertEqual(set(result.report.output_files), {
                "sft.jsonl",
                "preference_pairs.jsonl",
                "rl_trajectories.jsonl",
                "eval_cases.jsonl",
                "red_team_cases.jsonl",
                "dataset_manifest.json",
            })
            for filename in result.report.output_files:
                self.assertTrue((output_dir / filename).exists())

            sft_rows = _read_jsonl(output_dir / "sft.jsonl")

        self.assertEqual(len(sft_rows), 1)
        self.assertEqual(sft_rows[0]["tenant_id"], "tenant_a")
        self.assertEqual(sft_rows[0]["redaction_status"], "redacted")
        self.assertNotIn("abcdefghi123456789", json.dumps(sft_rows, sort_keys=True))
        self.assertEqual(sft_rows[0]["payload"]["tool_schemas"][0]["name"], "kubernetes.get_deployment")

    def test_refinery_chunks_long_records_and_preserves_audit_only_rows(self) -> None:
        refinery = MeshBrainDataRefinery(tenant_id="tenant_a", chunk_chars=20)
        result = refinery.build(
            source_manifest_id="manifest_chunks",
            records=[
                SourceRecord(
                    tenant_id="tenant_a",
                    source="runbook",
                    content="alpha beta gamma delta epsilon zeta eta theta",
                    provenance_pointer="runbook://1",
                    timestamp="2026-04-30T00:00:00+00:00",
                    audit_only=True,
                    outcome="successful",
                )
            ],
        )

        self.assertGreater(result.report.chunks, 1)
        self.assertTrue(all(row.excluded_from_training for row in result.bundle.rows))
        self.assertEqual(result.normalized_records[0].outcome_label, "positive")

    def test_tool_schema_extraction_and_outcome_labeling_are_deterministic(self) -> None:
        schema = extract_tool_schema(
            {
                "name": "repo.patch",
                "arguments": {"path": "app.py", "dry_run": True, "attempt": 2},
            }
        )

        self.assertEqual(schema["name"], "repo.patch")
        self.assertEqual(schema["schema"]["properties"]["attempt"]["type"], "number")
        self.assertEqual(schema["schema"]["properties"]["dry_run"]["type"], "boolean")
        self.assertEqual(schema["schema"]["properties"]["path"]["type"], "string")
        self.assertEqual(schema["schema"]["required"], ["attempt", "dry_run", "path"])
        self.assertEqual(label_outcome("approval_required", {}), "needs_review")
        self.assertEqual(label_outcome("regressed", {}), "negative")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
