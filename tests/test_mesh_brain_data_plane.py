from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    MeshBrainDataRefinery,
    SourceRecord,
    build_context_training_data_plane,
    build_data_plane_e2e,
    extract_tool_schema,
    label_outcome,
)
from shared.mesh_runtime.monitoring_corpus import build_public_monitoring_corpus_rows


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

    def test_context_training_data_plane_ingests_corpus_and_runtime_context(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result, summary = build_context_training_data_plane(
                tenant_id="tenant_a",
                output_directory=temp_dir,
                corpus_rows=build_public_monitoring_corpus_rows()[:2],
                runtime_sessions=[
                    {
                        "run_id": "run_live",
                        "stage": "completed",
                        "status": "completed",
                        "scenario_key": "runtime_context",
                        "created_at": "2026-04-30T00:00:00+00:00",
                        "updated_at": "2026-04-30T00:00:01+00:00",
                        "artifacts": {
                            "decision": {"decision_type": "patch"},
                            "feedback": {"outcome": "successful"},
                        },
                    }
                ],
                runtime_events=[
                    {
                        "run_id": "run_live",
                        "event_id": "evt_1",
                        "sequence": 1,
                        "stage": "feedback",
                        "event_type": "feedback_recorded",
                        "recorded_at": "2026-04-30T00:00:02+00:00",
                        "payload": {"outcome": "successful"},
                        "summary": {"outcome": "successful"},
                        "status": "completed",
                    }
                ],
            )
            manifest = json.loads((Path(temp_dir) / "dataset_manifest.json").read_text(encoding="utf-8"))
            sft_rows = _read_jsonl(Path(temp_dir) / "sft.jsonl")

        self.assertEqual(summary.corpus_record_count, 2)
        self.assertEqual(summary.runtime_session_count, 1)
        self.assertEqual(summary.runtime_event_count, 1)
        self.assertEqual(result.report.accepted_records, 5)
        self.assertGreaterEqual(manifest["output_counts"]["sft.jsonl"], 5)
        self.assertTrue(any(row["source"] == "runtime:run_event" for row in sft_rows))
        self.assertTrue(any(row["source"].startswith("corpus:") for row in sft_rows))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
