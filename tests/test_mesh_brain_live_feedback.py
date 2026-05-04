from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.live_feedback import export_live_feedback_dataset


class MeshBrainLiveFeedbackTests(unittest.TestCase):
    def test_blocked_live_run_exports_feedback_dataset(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = export_live_feedback_dataset(
                live_summary=_summary("block"),
                output_directory=Path(temp_dir),
                tenant_id="tenant_a",
            )
            manifest = json.loads((Path(temp_dir) / "dataset_manifest.json").read_text(encoding="utf-8"))
            report = json.loads((Path(temp_dir) / "live_feedback_report.json").read_text(encoding="utf-8"))

        self.assertEqual(result.status, "exported")
        self.assertEqual(result.row_count, 5)
        self.assertEqual(manifest["row_count"], 5)
        self.assertEqual(report["status"], "exported")
        self.assertIn("sft.jsonl", result.artifact_paths)
        self.assertIn("eval_cases.jsonl", result.artifact_paths)

    def test_promoted_live_run_skips_training_feedback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = export_live_feedback_dataset(
                live_summary=_summary("promote"),
                output_directory=Path(temp_dir),
                tenant_id="tenant_a",
            )
            report = json.loads((Path(temp_dir) / "live_feedback_report.json").read_text(encoding="utf-8"))

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.row_count, 0)
        self.assertEqual(report["report"]["reason"], "release_passed")
        self.assertFalse(result.artifact_paths)


def _summary(decision: str) -> dict[str, object]:
    return {
        "tenant_id": "tenant_a",
        "status": decision,
        "model": "nvidia/nemotron-3-nano-4b",
        "requested_model": "nvidia/nemotron-3-nano-4b",
        "backend_name": "mlx",
        "hardware_tier": "apple_silicon",
        "request_id": "mb_req_test",
        "completion_id": "chatcmpl_test",
        "content_preview": "I restarted the deployment and restart completed.",
        "gate": {"decision": "pass", "reasons": []},
        "response_eval": {"decision": "block", "reasons": ["unsupported_tool_execution_claim"]},
        "judge_eval": {"decision": "block", "reasons": ["unsupported_tool_execution_claim"]},
        "release_gate": {"decision": decision, "reasons": ["live_judge_eval_blocked"] if decision == "block" else []},
        "deployment_record": {"status": "blocked" if decision == "block" else "eligible_for_promote"},
    }


if __name__ == "__main__":
    unittest.main()
